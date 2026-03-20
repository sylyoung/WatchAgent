from __future__ import annotations

import time
from datetime import UTC, datetime

from starlette.testclient import TestClient

from watchagent_backend.api import create_app
from watchagent_backend.store import InMemoryStore


def _wait_for_run_completed(client: TestClient, session_id: str, timeout_sec: float = 15.0) -> bool:
    start = time.time()
    while time.time() - start < timeout_sec:
        events = client.get(f"/v1/skills/{session_id}/events?after_event_id=0&limit=300")
        assert events.status_code == 200
        if any(e["event_type"] == "run_completed" for e in events.json()["events"]):
            return True
        time.sleep(0.1)
    return False


def test_codex_queue_returns_pending_items() -> None:
    """In-memory codex queue is seeded and accessible via the queue endpoint."""
    store = InMemoryStore()
    client = TestClient(create_app(store=store))

    pending_queue = client.get("/v1/codex/queue?only_pending=true")
    assert pending_queue.status_code == 200
    pending_items = pending_queue.json()["items"]
    assert pending_items

    for item in pending_items:
        assert item["approval_id"]
        assert item["acp_thread_id"]
        assert item["openclaw_session_id"]
        assert item["status"] == "pending"


def test_codex_cards_can_be_approved_sequentially_until_queue_is_empty() -> None:
    """Codex items can be approved one by one via /v1/codex/decision until queue is empty."""
    store = InMemoryStore()
    client = TestClient(create_app(store=store))
    session_id = "codex-sequential-approve-user"

    pending_queue = client.get("/v1/codex/queue?only_pending=true")
    assert pending_queue.status_code == 200
    pending_items = pending_queue.json()["items"]
    assert pending_items

    for item in pending_items:
        decision = client.post(
            "/v1/codex/decision",
            json={
                "session_id": session_id,
                "approval_id": item["approval_id"],
                "decision": "approve",
                "input_mode": "gesture",
            },
        )
        assert decision.status_code == 200
        assert decision.json()["status"] == "approved"

    queue = client.get("/v1/codex/queue?only_pending=true")
    assert queue.status_code == 200
    assert queue.json()["items"] == []

    logs = client.get("/v1/audit/logs?limit=100")
    assert logs.status_code == 200
    entries = [
        item for item in logs.json()["logs"]
        if item["who"] == session_id and "Codex审批" in item["what"]
    ]
    assert len(entries) == len(pending_items)
    for entry in entries:
        assert entry["metadata"]["approval_id"]
        assert entry["metadata"]["acp_thread_id"]
        assert entry["openclaw_session_id"]


def test_work_progress_command_emits_run_completed() -> None:
    """work_progress command always completes (even without LLM or real macOS providers)."""
    store = InMemoryStore()
    client = TestClient(create_app(store=store))
    session_id = "codex-all-pending-user"

    command = client.post(
        "/v1/watch/command",
        json={
            "session_id": session_id,
            "utterance": "工作进展",
            "device_context": {"watch_model": "Apple Watch S11"},
            "input_mode": "voice",
            "entry_mode": "siri",
            "intent_id": "intent-codex-serial",
            "trace_id": "trace-codex-serial",
            "timestamp": datetime.now(UTC).isoformat(),
        },
    )
    assert command.status_code == 200
    assert command.json()["speech_text"]

    assert _wait_for_run_completed(client, session_id), "run_completed event never emitted"
