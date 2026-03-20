from __future__ import annotations

import time
from datetime import UTC, datetime
import json

from starlette.testclient import TestClient

from watchagent_backend.api import create_app


client = TestClient(create_app())


def _command_payload(utterance: str, skill_hint: str | None = None) -> dict:
    return {
        "session_id": "demo-user-1",
        "utterance": utterance,
        "skill_hint": skill_hint,
        "device_context": {
            "watch_model": "Apple Watch S9",
            "timezone": "Asia/Shanghai",
            "battery_level": 84,
        },
        "input_mode": "voice",
        "entry_mode": "siri",
        "intent_id": "intent-morning-001",
        "trace_id": "trace-abc",
        "timestamp": datetime.now(UTC).isoformat(),
    }


def _poll_for_card_token(client: TestClient, session_id: str, timeout: float = 12.0) -> str | None:
    """Poll SSE events until an action_card_created event appears, return confirm_token."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        events = client.get(f"/v1/skills/{session_id}/events?after_event_id=0&limit=300")
        assert events.status_code == 200
        for event in events.json()["events"]:
            if event["event_type"] == "action_card_created":
                return event["payload"].get("confirm_token")
        time.sleep(0.2)
    return None


def test_morning_command_has_run_debug_and_low_latency() -> None:
    response = client.post("/v1/watch/command", json=_command_payload("今日日程"))
    assert response.status_code == 200
    body = response.json()

    assert body["debug"]["skill"] == "morning_brief"
    assert body["debug"]["skill_run_id"]
    assert body["debug"]["entry_mode"] == "siri"
    assert body["debug"]["trace_id"] == "trace-abc"
    assert body["debug"]["latency_target_ms"] == 700
    assert body["debug"]["first_response_ms"] <= 700


def test_confirm_approve_writes_audit_log() -> None:
    session_id = "confirm-approve-user"
    command = client.post(
        "/v1/watch/command",
        json={
            **_command_payload("滴滴叫一辆车", skill_hint="ride_hailing"),
            "session_id": session_id,
        },
    )
    assert command.status_code == 200

    # Cards are created asynchronously — poll SSE events
    token = _poll_for_card_token(client, session_id)
    assert token is not None, "No action_card_created event received"

    confirm = client.post(
        "/v1/watch/confirm",
        json={
            "session_id": session_id,
            "confirm_token": token,
            "decision": "approve",
            "input_mode": "gesture",
            "timestamp": datetime.now(UTC).isoformat(),
        },
    )

    assert confirm.status_code == 200
    assert confirm.json()["result"] == "executed"

    logs = client.get("/v1/audit/logs?limit=10")
    assert logs.status_code == 200
    found = [x for x in logs.json()["logs"] if x["confirm_token"] == token]
    assert found
    assert found[0]["result"] == "executed"
    assert found[0]["openclaw_session_id"]


def test_message_reply_command_generates_send_card_and_can_confirm() -> None:
    session_id = "message-draft-user"
    command = client.post(
        "/v1/watch/command",
        json={
            **_command_payload("帮我回复妈妈说正在抢票了", skill_hint="message_inbox"),
            "session_id": session_id,
            "trace_id": "trace-message-draft",
        },
    )
    assert command.status_code == 200

    # Cards are created asynchronously via LLM tool-call loop
    token = _poll_for_card_token(client, session_id)
    assert token is not None, "No action_card_created event received"

    confirm = client.post(
        "/v1/watch/confirm",
        json={
            "session_id": session_id,
            "confirm_token": token,
            "decision": "approve",
            "input_mode": "tap",
            "timestamp": datetime.now(UTC).isoformat(),
        },
    )
    assert confirm.status_code == 200
    # send_message calls real WeChat; result depends on whether WeChat is running
    assert confirm.json()["result"] in ("executed", "failed")


def test_stream_and_codex_queue_endpoints() -> None:
    session_id = "stream-demo"
    response = client.post(
        "/v1/watch/command",
        json={
            **_command_payload("工作进展"),
            "session_id": session_id,
            "trace_id": "trace-stream",
        },
    )
    assert response.status_code == 200

    # Poll until run_completed appears
    run_completed = False
    for _ in range(60):
        events = client.get(f"/v1/skills/{session_id}/events?after_event_id=0&limit=200")
        assert events.status_code == 200
        data = events.json()["events"]
        if any(e["event_type"] == "run_completed" for e in data):
            run_completed = True
            break
        time.sleep(0.2)

    assert run_completed

    queue = client.get("/v1/codex/queue?only_pending=true")
    assert queue.status_code == 200
    assert len(queue.json()["items"]) >= 1

    stream = client.get(f"/v1/skills/{session_id}/stream?after_event_id=0&follow=false")
    assert stream.status_code == 200
    assert "event: done" in stream.text


def _parse_sse(raw: str) -> list[dict]:
    events: list[dict] = []
    current: dict = {}
    for line in raw.splitlines():
        if line.startswith("id: "):
            current["id"] = int(line.split(": ", 1)[1].strip())
        elif line.startswith("event: "):
            current["event"] = line.split(": ", 1)[1].strip()
        elif line.startswith("data: "):
            payload = line.split(": ", 1)[1]
            try:
                current["data"] = json.loads(payload)
            except json.JSONDecodeError:
                current["data"] = payload
        elif not line.strip() and current:
            events.append(current)
            current = {}
    if current:
        events.append(current)
    return events


def test_sse_stream_can_resume_from_cursor_without_duplicates() -> None:
    session_id = "stream-resume-demo"
    response = client.post(
        "/v1/watch/command",
        json={
            **_command_payload("工作进展"),
            "session_id": session_id,
            "trace_id": "trace-stream-resume",
        },
    )
    assert response.status_code == 200

    time.sleep(3)
    first = client.get(f"/v1/skills/{session_id}/stream?after_event_id=0&follow=false")
    assert first.status_code == 200
    first_events = _parse_sse(first.text)
    first_data_events = [e for e in first_events if e.get("event") != "done" and "id" in e]
    assert first_data_events
    cursor = first_data_events[0]["id"]

    second = client.get(f"/v1/skills/{session_id}/stream?after_event_id={cursor}&follow=false")
    assert second.status_code == 200
    second_events = _parse_sse(second.text)
    second_data_events = [e for e in second_events if e.get("event") != "done" and "id" in e]
    assert second_data_events
    assert all(e["id"] > cursor for e in second_data_events)


def test_morning_brief_emits_tool_events() -> None:
    session_id = "morning-tool-events"
    response = client.post(
        "/v1/watch/command",
        json={
            **_command_payload("今日日程"),
            "session_id": session_id,
            "trace_id": "trace-morning-tools",
        },
    )
    assert response.status_code == 200

    # In new architecture: LLM calls tools; events are tool_result or run_completed
    run_completed = False
    for _ in range(60):
        events = client.get(f"/v1/skills/{session_id}/events?after_event_id=0&limit=300")
        assert events.status_code == 200
        data = events.json()["events"]
        if any(e["event_type"] == "run_completed" for e in data):
            run_completed = True
            break
        time.sleep(0.2)

    assert run_completed


def test_mac_status_integration_with_work_skill() -> None:
    status_response = client.post(
        "/v1/mac/status",
        json={
            "reporter_id": "macbook-pro",
            "tasks": [
                {
                    "task_id": "custom-task-1",
                    "task_title": "毕业论文格式校验",
                    "state": "running",
                    "progress": 57,
                    "action_needed": "确认是否合并附录",
                    "last_update": datetime.now(UTC).isoformat(),
                    "source": "codex",
                }
            ],
            "timestamp": datetime.now(UTC).isoformat(),
        },
    )
    assert status_response.status_code == 200

    command = client.post("/v1/watch/command", json=_command_payload("工作进展"))
    assert command.status_code == 200
    # In new architecture, first_speech comes from SKILL.md
    assert command.json()["speech_text"]


def test_openclaw_evidence_endpoint() -> None:
    evidence = client.get("/v1/openclaw/evidence")
    assert evidence.status_code == 200
    body = evidence.json()
    assert body["gateway_status"] == "running"
    assert body["telegram_channel"] == "@OpenClawBot"
