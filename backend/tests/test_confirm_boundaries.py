from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta

from starlette.testclient import TestClient

from watchagent_backend.api import create_app
from watchagent_backend.store import InMemoryStore


def _command_payload(session_id: str, utterance: str = "滴滴叫车") -> dict:
    return {
        "session_id": session_id,
        "utterance": utterance,
        "skill_hint": "ride_hailing",
        "device_context": {"watch_model": "Apple Watch S9"},
        "input_mode": "voice",
        "entry_mode": "tap",
        "timestamp": datetime.now(UTC).isoformat(),
    }


def _poll_for_card_token(client: TestClient, session_id: str, store: InMemoryStore | None = None, timeout: float = 15.0) -> str | None:
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


def test_confirm_missing_token_returns_404() -> None:
    client = TestClient(create_app())
    response = client.post(
        "/v1/watch/confirm",
        json={
            "session_id": "missing-token-user",
            "confirm_token": "not-exist",
            "decision": "approve",
            "input_mode": "tap",
            "timestamp": datetime.now(UTC).isoformat(),
        },
    )
    assert response.status_code == 404
    assert response.json()["result"] == "missing"


def test_confirm_expired_token_returns_410() -> None:
    store = InMemoryStore()
    client = TestClient(create_app(store=store))
    session_id = "expired-user"

    client.post("/v1/watch/command", json=_command_payload(session_id))

    # Poll SSE events to get the token
    token = _poll_for_card_token(client, session_id, store=store)
    assert token is not None, "No action_card_created event received"

    pending = store.get_pending(token)
    assert pending is not None
    pending.expires_at = datetime.now(UTC) - timedelta(seconds=1)

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
    assert confirm.status_code == 410
    assert confirm.json()["result"] == "expired"


def test_confirm_replay_same_token_returns_missing_after_first_use() -> None:
    client = TestClient(create_app())
    session_id = "replay-user"

    client.post("/v1/watch/command", json=_command_payload(session_id))

    token = _poll_for_card_token(client, session_id)
    assert token is not None, "No action_card_created event received"

    first = client.post(
        "/v1/watch/confirm",
        json={
            "session_id": session_id,
            "confirm_token": token,
            "decision": "approve",
            "input_mode": "tap",
            "timestamp": datetime.now(UTC).isoformat(),
        },
    )
    assert first.status_code == 200
    # ride confirm always succeeds (demo mode)
    assert first.json()["result"] == "executed"

    second = client.post(
        "/v1/watch/confirm",
        json={
            "session_id": session_id,
            "confirm_token": token,
            "decision": "approve",
            "input_mode": "tap",
            "timestamp": datetime.now(UTC).isoformat(),
        },
    )
    assert second.status_code == 404
    assert second.json()["result"] == "missing"
