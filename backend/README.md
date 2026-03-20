# Backend Quickstart

## Run
```bash
python3 run_server.py
```

## Test
```bash
python3 -m pytest -q
```

## API
- `POST /v1/watch/command`
- `POST /v1/watch/confirm`
- `GET /v1/skills/{session_id}/state`
- `GET /v1/skills/{session_id}/events`
- `GET /v1/skills/{session_id}/stream` (SSE)
- `GET /v1/codex/queue`
- `POST /v1/codex/decision`
- `POST /v1/mac/status`
- `GET /v1/mac/status`
- `GET /v1/audit/logs`
- `GET /v1/model-routing`
- `GET /v1/health`

## Notes
- Confirm tokens are one-time and session-scoped.
- Morning skill uses subagent fan-out and SSE incremental updates.
- Codex approvals are pushed as a serial queue; `primary_action=approve`, `reject_mode=voice_only`.
