from __future__ import annotations

import time
from datetime import UTC, datetime

from starlette.testclient import TestClient

from watchagent_backend.api import create_app


def _poll_for_card_token(client: TestClient, session_id: str, timeout_sec: float = 15.0) -> str | None:
    start = time.time()
    while time.time() - start < timeout_sec:
        events = client.get(f"/v1/skills/{session_id}/events?after_event_id=0&limit=300")
        assert events.status_code == 200
        for event in events.json()["events"]:
            if event["event_type"] == "action_card_created":
                return event["payload"].get("confirm_token")
        time.sleep(0.2)
    return None


def test_audit_logs_keep_approve_reject_followup_and_openclaw_consistency() -> None:
    client = TestClient(create_app())
    session_id = "audit-consistency-user"
    followup = "No, and do switch to browser-search fallback."

    # 1. Approve a codex item via /v1/codex/decision (in-memory queue)
    queue = client.get("/v1/codex/queue?only_pending=true")
    assert queue.status_code == 200
    items = queue.json()["items"]
    assert len(items) >= 2

    approve = client.post(
        "/v1/codex/decision",
        json={
            "session_id": session_id,
            "approval_id": items[0]["approval_id"],
            "decision": "approve",
            "input_mode": "gesture",
        },
    )
    assert approve.status_code == 200

    reject = client.post(
        "/v1/codex/decision",
        json={
            "session_id": session_id,
            "approval_id": items[1]["approval_id"],
            "decision": "reject",
            "input_mode": "voice",
            "followup_text": followup,
        },
    )
    assert reject.status_code == 200

    # 2. Ride hailing via command → SSE card → confirm
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

    ride_token = _poll_for_card_token(client, ride_session)
    assert ride_token is not None, "No ride action_card_created event"

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

    # 3. Check audit logs
    logs = client.get("/v1/audit/logs?limit=200")
    assert logs.status_code == 200
    all_entries = logs.json()["logs"]

    codex_entries = [e for e in all_entries if "Codex审批" in e.get("what", "") and e["who"] == session_id]
    ride_entries = [e for e in all_entries if "滴滴叫车" in e.get("what", "") and e["who"] == ride_session]

    assert any(e["result"] == "executed" for e in codex_entries)
    assert any(e["result"] == "canceled" for e in codex_entries)
    assert any(e["result"] == "executed" for e in ride_entries)

    for item in codex_entries + ride_entries:
        assert item["who"]
        assert item["when"]
        assert item["what"]
        assert item["result"]
        assert item["openclaw_session_id"]

    reject_entry = next(
        (e for e in codex_entries if e["result"] == "canceled"), None
    )
    assert reject_entry is not None
    # followup_text is stored in the "why" field of the audit log entry
    assert followup in (reject_entry.get("why") or "")
