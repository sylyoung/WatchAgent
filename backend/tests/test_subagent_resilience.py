from __future__ import annotations

import time
from datetime import UTC, datetime

from starlette.testclient import TestClient

import watchagent_backend.agent_runner as agent_runner_mod
import watchagent_backend.tools_registry as tools_registry_mod
from watchagent_backend.api import create_app


def test_subagent_failure_does_not_block_run_completed(monkeypatch) -> None:
    original_build_handlers = tools_registry_mod.build_handlers

    def _patched_build_handlers(request, providers):
        handlers = original_build_handlers(request, providers)

        def _weather_broken():
            raise RuntimeError("weather service unavailable")

        handlers["get_weather"] = _weather_broken
        return handlers

    # Patch where agent_runner imports it (not tools_registry module itself)
    monkeypatch.setattr(agent_runner_mod, "build_handlers", _patched_build_handlers)
    client = TestClient(create_app())
    session_id = "resilience-user"

    command = client.post(
        "/v1/watch/command",
        json={
            "session_id": session_id,
            "utterance": "今日日程",
            "device_context": {"watch_model": "Apple Watch S9"},
            "input_mode": "voice",
            "entry_mode": "siri",
            "intent_id": "intent-resilience",
            "trace_id": "trace-resilience",
            "timestamp": datetime.now(UTC).isoformat(),
        },
    )
    assert command.status_code == 200

    has_tool_error = False
    has_run_completed = False

    for _ in range(120):
        events = client.get(f"/v1/skills/{session_id}/events?after_event_id=0&limit=300")
        assert events.status_code == 200
        for event in events.json()["events"]:
            if event["event_type"] == "tool_error" and event["step"] == "get_weather":
                has_tool_error = True
            if event["event_type"] == "run_completed":
                has_run_completed = True

        if has_tool_error and has_run_completed:
            break
        time.sleep(0.1)

    assert has_tool_error is True
    assert has_run_completed is True
