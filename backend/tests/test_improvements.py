from __future__ import annotations

import time
from datetime import UTC, datetime

from starlette.testclient import TestClient

from watchagent_backend.api import create_app


def _command_payload(session_id: str) -> dict:
    return {
        "session_id": session_id,
        "utterance": "工作进展",
        "device_context": {"watch_model": "Apple Watch S9"},
        "input_mode": "voice",
        "entry_mode": "siri",
        "intent_id": "intent-work-refill",
        "trace_id": f"trace-{session_id}",
        "timestamp": datetime.now(UTC).isoformat(),
    }


def _wait_for_run_completed(client: TestClient, session_id: str, timeout_sec: float = 15.0) -> bool:
    start = time.time()
    while time.time() - start < timeout_sec:
        events = client.get(f"/v1/skills/{session_id}/events?after_event_id=0&limit=200")
        assert events.status_code == 200
        if any(e["event_type"] == "run_completed" for e in events.json()["events"]):
            return True
        time.sleep(0.2)
    return False


def test_work_progress_run_completes_after_queue_is_drained() -> None:
    """work_progress command still completes even after the codex queue is drained."""
    client = TestClient(create_app())

    queue_resp = client.get("/v1/codex/queue?only_pending=true")
    assert queue_resp.status_code == 200
    pending = queue_resp.json()["items"]
    assert pending

    # Drain the queue
    for item in pending:
        decision = client.post(
            "/v1/codex/decision",
            json={
                "session_id": "drain-user",
                "approval_id": item["approval_id"],
                "decision": "approve",
                "input_mode": "gesture",
            },
        )
        assert decision.status_code == 200

    empty_queue = client.get("/v1/codex/queue?only_pending=true")
    assert empty_queue.status_code == 200
    assert empty_queue.json()["items"] == []

    # work_progress should still complete (with empty codex queue)
    session_id = "work-refill-check"
    command = client.post("/v1/watch/command", json=_command_payload(session_id))
    assert command.status_code == 200
    assert command.json()["speech_text"]

    assert _wait_for_run_completed(client, session_id), "run_completed never emitted"


def test_run_server_bind_config_from_environment(monkeypatch) -> None:
    import run_server

    monkeypatch.delenv("WATCHAGENT_HOST", raising=False)
    monkeypatch.delenv("WATCHAGENT_PORT", raising=False)
    assert run_server.get_bind_config() == ("0.0.0.0", 8787)

    monkeypatch.setenv("WATCHAGENT_HOST", "127.0.0.1")
    monkeypatch.setenv("WATCHAGENT_PORT", "18787")
    assert run_server.get_bind_config() == ("127.0.0.1", 18787)
