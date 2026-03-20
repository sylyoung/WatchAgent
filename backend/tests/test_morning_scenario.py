from __future__ import annotations

import time
from datetime import UTC, datetime

from starlette.testclient import TestClient

from watchagent_backend.api import create_app


client = TestClient(create_app())


def _command(session_id: str, utterance: str, skill_hint: str | None = None, entry_mode: str = "complication") -> dict:
    response = client.post(
        "/v1/watch/command",
        json={
            "session_id": session_id,
            "utterance": utterance,
            "skill_hint": skill_hint,
            "device_context": {"watch_model": "Apple Watch S9", "battery_level": 78},
            "input_mode": "voice",
            "entry_mode": entry_mode,
            "timestamp": datetime.now(UTC).isoformat(),
        },
    )
    assert response.status_code == 200
    return response.json()


def _confirm(session_id: str, token: str, decision: str = "approve", mode: str = "gesture", followup_text: str | None = None) -> dict:
    payload = {
        "session_id": session_id,
        "confirm_token": token,
        "decision": decision,
        "input_mode": mode,
        "timestamp": datetime.now(UTC).isoformat(),
    }
    if followup_text is not None:
        payload["followup_text"] = followup_text

    response = client.post("/v1/watch/confirm", json=payload)
    assert response.status_code == 200
    return response.json()


def _poll_card_token(session_id: str, timeout_sec: float = 15.0) -> str | None:
    """Poll SSE events until an action_card_created event appears, return confirm_token."""
    start = time.time()
    while time.time() - start < timeout_sec:
        events = client.get(f"/v1/skills/{session_id}/events?after_event_id=0&limit=300")
        assert events.status_code == 200
        for event in events.json()["events"]:
            if event["event_type"] == "action_card_created":
                return event["payload"].get("confirm_token")
        time.sleep(0.2)
    return None


def _wait_for_run_completed(session_id: str) -> bool:
    for _ in range(60):
        events = client.get(f"/v1/skills/{session_id}/events?after_event_id=0&limit=200")
        assert events.status_code == 200
        if any(e["event_type"] == "run_completed" for e in events.json()["events"]):
            return True
        time.sleep(0.2)
    return False


def test_morning_story_flow_end_to_end() -> None:
    session_id = "morning-e2e"

    mac_status = client.post(
        "/v1/mac/status",
        json={
            "reporter_id": "macbook-pro",
            "tasks": [
                {
                    "task_id": "thesis-32",
                    "task_title": "毕业论文修改第32轮",
                    "state": "running",
                    "progress": 82,
                    "action_needed": "确认是否发送当前 PDF",
                    "last_update": datetime.now(UTC).isoformat(),
                    "source": "codex",
                },
                {
                    "task_id": "neurips-crawl",
                    "task_title": "NeurIPS 2025 论文检索",
                    "state": "blocked",
                    "progress": 42,
                    "blocked_reason": "Google Scholar crawler blocked",
                    "action_needed": "是否重试",
                    "last_update": datetime.now(UTC).isoformat(),
                    "source": "codex",
                },
            ],
            "timestamp": datetime.now(UTC).isoformat(),
        },
    )
    assert mac_status.status_code == 200

    # Morning brief
    morning = _command(session_id, "今日日程", entry_mode="siri")
    assert morning["debug"]["skill"] == "morning_brief"
    assert morning["speech_text"]
    assert _wait_for_run_completed(session_id)

    # Work progress
    work = _command(session_id, "工作进展")
    assert work["debug"]["skill"] == "work_progress"
    assert work["speech_text"]

    # Approve/reject codex items via in-memory queue + /v1/codex/decision
    queue = client.get("/v1/codex/queue?only_pending=true")
    assert queue.status_code == 200
    items = queue.json()["items"]
    assert len(items) >= 2

    approve_result = client.post(
        "/v1/codex/decision",
        json={
            "session_id": session_id,
            "approval_id": items[0]["approval_id"],
            "decision": "approve",
            "input_mode": "gesture",
        },
    )
    assert approve_result.status_code == 200

    reject_result = client.post(
        "/v1/codex/decision",
        json={
            "session_id": session_id,
            "approval_id": items[1]["approval_id"],
            "decision": "reject",
            "input_mode": "voice",
            "followup_text": "No, and do switch to browser-search fallback.",
        },
    )
    assert reject_result.status_code == 200

    # Ride hailing via SSE card
    ride_session = f"{session_id}-ride"
    _command(ride_session, "滴滴叫一辆车")
    ride_token = _poll_card_token(ride_session)
    assert ride_token is not None, "No ride card emitted"
    _confirm(ride_session, ride_token, "approve")

    # Message inbox - first_speech returned immediately, no cards in initial response
    inbox = _command(session_id, "我的消息", skill_hint="message_inbox")
    assert inbox["speech_text"]

    # Skill state endpoint works
    state = client.get(f"/v1/skills/{session_id}/state")
    assert state.status_code == 200
    assert state.json()["state"] is not None

    # Stream has run_completed
    assert _wait_for_run_completed(session_id) is True
    stream = client.get(f"/v1/skills/{session_id}/stream?after_event_id=0&follow=false")
    assert stream.status_code == 200
    assert "event: run_completed" in stream.text

    # Audit logs have the activity
    logs = client.get("/v1/audit/logs?limit=50")
    assert logs.status_code == 200
    entries = logs.json()["logs"]
    assert any(x["openclaw_session_id"] for x in entries)
    assert any(
        "No, and do switch to browser-search fallback." in (x.get("why") or "") or
        "No, and do switch to browser-search fallback." in (x.get("metadata", {}).get("followup_text", "") or "")
        for x in entries
    )
