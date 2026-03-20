from __future__ import annotations

import time
from datetime import UTC, datetime

from starlette.testclient import TestClient

from watchagent_backend.api import create_app


def _poll_card_token(client: TestClient, session_id: str, timeout_sec: float = 15.0) -> str | None:
    start = time.time()
    while time.time() - start < timeout_sec:
        events = client.get(f"/v1/skills/{session_id}/events?after_event_id=0&limit=300")
        assert events.status_code == 200
        for event in events.json()["events"]:
            if event["event_type"] == "action_card_created":
                return event["payload"].get("confirm_token")
        time.sleep(0.2)
    return None


def _wait_for_run_completed(client: TestClient, session_id: str, timeout_sec: float = 15.0) -> bool:
    start = time.time()
    while time.time() - start < timeout_sec:
        events = client.get(f"/v1/skills/{session_id}/events?after_event_id=0&limit=300")
        assert events.status_code == 200
        if any(e["event_type"] == "run_completed" for e in events.json()["events"]):
            return True
        time.sleep(0.2)
    return False


def _run_one_round(client: TestClient, session_id: str, queue_item: dict | None) -> None:
    """One test round: work_progress, optional codex approve/reject, ride hailing."""
    morning = client.post(
        "/v1/watch/command",
        json={
            "session_id": session_id,
            "utterance": "工作进展",
            "device_context": {"watch_model": "Apple Watch S9"},
            "input_mode": "voice",
            "entry_mode": "siri",
            "intent_id": f"intent-{session_id}",
            "trace_id": f"trace-{session_id}",
            "timestamp": datetime.now(UTC).isoformat(),
        },
    )
    assert morning.status_code == 200
    assert _wait_for_run_completed(client, session_id), f"run_completed not emitted for {session_id}"

    # Approve a codex item from the in-memory queue if available
    if queue_item:
        approve = client.post(
            "/v1/codex/decision",
            json={
                "session_id": session_id,
                "approval_id": queue_item["approval_id"],
                "decision": "approve",
                "input_mode": "gesture",
            },
        )
        assert approve.status_code == 200

        reject = client.post(
            "/v1/codex/decision",
            json={
                "session_id": session_id,
                "approval_id": queue_item["approval_id"],
                "decision": "reject",
                "input_mode": "voice",
                "followup_text": "No, and do switch to browser-search fallback.",
            },
        )
        # Second attempt on same item returns 404 (already decided), which is fine
        assert reject.status_code in (200, 404)

    ride_session = f"{session_id}-ride"
    ride = client.post(
        "/v1/watch/command",
        json={
            "session_id": ride_session,
            "utterance": "滴滴叫一辆车",
            "skill_hint": "ride_hailing",
            "device_context": {"watch_model": "Apple Watch S9"},
            "input_mode": "voice",
            "entry_mode": "complication",
            "timestamp": datetime.now(UTC).isoformat(),
        },
    )
    assert ride.status_code == 200

    ride_token = _poll_card_token(client, ride_session)
    assert ride_token is not None, f"No ride card for {session_id}"

    ride_confirm = client.post(
        "/v1/watch/confirm",
        json={
            "session_id": ride_session,
            "confirm_token": ride_token,
            "decision": "approve",
            "input_mode": "gesture",
            "timestamp": datetime.now(UTC).isoformat(),
        },
    )
    assert ride_confirm.status_code == 200


def test_morning_flow_is_stable_for_10_consecutive_rounds() -> None:
    client = TestClient(create_app())

    # Get initial codex queue items (seeded by store)
    queue = client.get("/v1/codex/queue?only_pending=true")
    assert queue.status_code == 200
    items = queue.json()["items"]

    sessions = [f"stability-round-{idx}" for idx in range(10)]

    for idx, session_id in enumerate(sessions):
        queue_item = items[idx % len(items)] if items else None
        _run_one_round(client, session_id, queue_item)

    logs = client.get("/v1/audit/logs?limit=1000")
    assert logs.status_code == 200
    all_entries = logs.json()["logs"]

    for session_id in sessions:
        ride_session = f"{session_id}-ride"
        ride_entries = [item for item in all_entries if item["who"] == ride_session]
        assert ride_entries, f"No audit entries for {ride_session}"
        assert any(item["result"] == "executed" for item in ride_entries)
        assert any("滴滴叫车" in item["what"] for item in ride_entries)
