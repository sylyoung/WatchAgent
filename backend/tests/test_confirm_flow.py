from __future__ import annotations

import time
from datetime import UTC, datetime

from starlette.testclient import TestClient

from watchagent_backend.api import create_app


client = TestClient(create_app())


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


def test_reject_does_not_execute_and_keeps_followup() -> None:
    session_id = "demo-user-2"
    client.post(
        "/v1/watch/command",
        json={
            "session_id": session_id,
            "utterance": "滴滴叫车",
            "skill_hint": "ride_hailing",
            "device_context": {"watch_model": "Apple Watch Ultra 2"},
            "entry_mode": "tap",
            "timestamp": datetime.now(UTC).isoformat(),
        },
    )

    token = _poll_for_card_token(client, session_id)
    assert token is not None, "No action_card_created event received"

    confirm = client.post(
        "/v1/watch/confirm",
        json={
            "session_id": session_id,
            "confirm_token": token,
            "decision": "reject",
            "input_mode": "tap",
            "followup_text": "No, and do set destination to South Gate.",
            "timestamp": datetime.now(UTC).isoformat(),
        },
    )

    assert confirm.status_code == 200
    assert confirm.json()["result"] == "canceled"

    logs = client.get("/v1/audit/logs").json()["logs"]
    matched = [x for x in logs if x["confirm_token"] == token]
    assert matched
    assert matched[0]["result"] == "canceled"
    assert matched[0]["metadata"]["followup_text"] == "No, and do set destination to South Gate."


def test_token_is_scoped_to_session() -> None:
    session_id = "owner-session"
    client.post(
        "/v1/watch/command",
        json={
            "session_id": session_id,
            "utterance": "滴滴叫车",
            "skill_hint": "ride_hailing",
            "device_context": {"watch_model": "Apple Watch Ultra 2"},
            "timestamp": datetime.now(UTC).isoformat(),
        },
    )

    token = _poll_for_card_token(client, session_id)
    assert token is not None, "No action_card_created event received"

    hijack = client.post(
        "/v1/watch/confirm",
        json={
            "session_id": "other-session",
            "confirm_token": token,
            "decision": "approve",
            "input_mode": "tap",
            "timestamp": datetime.now(UTC).isoformat(),
        },
    )

    assert hijack.status_code == 403
    assert hijack.json()["result"] == "forbidden"


def test_codex_decision_endpoint_supports_followup() -> None:
    queue = client.get("/v1/codex/queue?only_pending=true")
    assert queue.status_code == 200
    item = queue.json()["items"][0]

    decision = client.post(
        "/v1/codex/decision",
        json={
            "session_id": "codex-user",
            "approval_id": item["approval_id"],
            "decision": "reject",
            "input_mode": "voice",
            "followup_text": "No, and do switch to proxy retry with backoff.",
        },
    )

    assert decision.status_code == 200
    body = decision.json()
    assert body["status"] == "rejected"
    assert "补充指令" in body["speech_text"]
    assert body["openclaw_session_id"]
