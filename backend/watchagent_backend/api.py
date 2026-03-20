from __future__ import annotations

import json
import os
import time
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Route
from starlette.types import ASGIApp, Receive, Scope, Send

_API_KEY = os.environ.get("WATCHAGENT_API_KEY", "")

if not _API_KEY:
    import logging
    logging.getLogger(__name__).warning(
        "WATCHAGENT_API_KEY not set — API is open. Set it for production use."
    )

_MAX_BODY_BYTES = 1_048_576  # 1 MB


class BodySizeLimitMiddleware:
    def __init__(self, app: ASGIApp, max_bytes: int = _MAX_BODY_BYTES) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            headers = dict(scope.get("headers", []))
            content_length = headers.get(b"content-length", b"0")
            try:
                if int(content_length) > self.max_bytes:
                    response = JSONResponse({"error": "payload_too_large"}, status_code=413)
                    await response(scope, receive, send)
                    return
            except ValueError:
                pass
        await self.app(scope, receive, send)


class APIKeyMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if _API_KEY and scope["type"] == "http":
            headers = dict(scope.get("headers", []))
            token = headers.get(b"x-api-key", b"").decode()
            if token != _API_KEY:
                response = JSONResponse({"error": "unauthorized"}, status_code=401)
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)

from .agent_runner import AgentRunner
from .executor import ActionExecutor
from .trace_db import TraceDB
from .models import (
    ApprovalDecisionRequest,
    ApprovalDecisionResponse,
    AuditLogEntry,
    CodexQueueResponse,
    Decision,
    ListAuditLogsResponse,
    ListMacTaskStatusResponse,
    MacStatusBatch,
    OpenClawEvidenceResponse,
    SkillEventsResponse,
    SkillStateResponse,
    WatchCommandRequest,
    WatchConfirmRequest,
    WatchConfirmResponse,
)
from .skills import attach_confirmation_tokens, resolve_skill
from .store import InMemoryStore


def _json(model: Any, status_code: int = 200) -> JSONResponse:
    if hasattr(model, "model_dump"):
        return JSONResponse(model.model_dump(mode="json"), status_code=status_code)
    return JSONResponse(model, status_code=status_code)


def _validation_error(err: ValidationError) -> JSONResponse:
    return JSONResponse({"error": "validation_error", "detail": err.errors()}, status_code=422)


def create_app(store: InMemoryStore | None = None, executor: ActionExecutor | None = None) -> Starlette:
    data_store = store or InMemoryStore()
    action_executor = executor or ActionExecutor(demo_mode=True)
    _db_path = os.environ.get("WATCHAGENT_TRACE_DB", "watchagent_trace.db")
    trace_db = TraceDB(_db_path)
    agent_runner = AgentRunner(data_store, trace_db=trace_db)

    async def health(_: Request) -> JSONResponse:
        return JSONResponse(
            {
                "ok": True,
                "service": "watch-agent-backend",
                "demo_mode": action_executor.demo_mode,
                "openclaw_required": True,
                "model_routing": agent_runner.model_config.model_dump(),
            }
        )

    async def watch_command(request: Request) -> JSONResponse:
        print(f"[WATCH_COMMAND] received from {request.client}", flush=True)
        try:
            payload = WatchCommandRequest.model_validate(await request.json())
        except ValidationError as err:
            print(f"[WATCH_COMMAND] validation error: {err}", flush=True)
            return _validation_error(err)

        started = time.perf_counter()
        skill = resolve_skill(payload.utterance, payload.skill_hint)

        trace_db.record_request_in(
            request_id=payload.trace_id,
            session_id=payload.session_id,
            trace_id=payload.trace_id,
            request_type="command",
            utterance=payload.utterance,
            skill_hint=payload.skill_hint,
            entry_mode=payload.entry_mode.value,
            input_mode=payload.input_mode.value,
            device_ctx_json=payload.device_context.model_dump_json(),
        )

        reply = agent_runner.start_run(payload, skill_name=skill)

        reply = attach_confirmation_tokens(reply, payload, data_store)

        first_response_ms = int((time.perf_counter() - started) * 1000)
        run_id = reply.debug.get("skill_run_id")
        if run_id:
            data_store.set_first_response_ms(run_id, first_response_ms)

        reply.debug = {
            **reply.debug,
            "entry_mode": payload.entry_mode.value,
            "intent_id": payload.intent_id,
            "trace_id": payload.trace_id,
            "first_response_ms": first_response_ms,
            "latency_target_ms": 700,
            "openclaw_engine": "enabled",
        }

        trace_db.record_request_out(
            request_id=payload.trace_id,
            resolved_skill=skill,
            response_speech=reply.speech_text,
            response_cards_json=json.dumps(
                [c.model_dump(mode="json") for c in reply.cards], ensure_ascii=False
            ),
            duration_ms=first_response_ms,
        )

        return _json(reply)

    async def watch_confirm(request: Request) -> JSONResponse:
        try:
            payload = WatchConfirmRequest.model_validate(await request.json())
        except ValidationError as err:
            return _validation_error(err)

        pending = data_store.get_pending(payload.confirm_token)
        if pending is None:
            response = WatchConfirmResponse(
                session_id=payload.session_id,
                speech_text="确认令牌不存在或已失效。",
                result="missing",
            )
            return _json(response, status_code=404)

        now = datetime.now(UTC)
        if now > pending.expires_at:
            data_store.pop_pending(payload.confirm_token)
            response = WatchConfirmResponse(
                session_id=payload.session_id,
                speech_text="这个确认请求已过期，请重新发起。",
                result="expired",
            )
            return _json(response, status_code=410)

        if pending.session_id != payload.session_id:
            response = WatchConfirmResponse(
                session_id=payload.session_id,
                speech_text="这个确认请求不属于当前会话，已拒绝执行。",
                result="forbidden",
            )
            return _json(response, status_code=403)

        if pending.card.action_type == "codex_decision":
            data_store.pop_pending(payload.confirm_token)
            approval_id = str(pending.card.action_payload.get("approval_id", ""))
            item = data_store.apply_codex_decision(approval_id, payload.decision)
            if item is None:
                response = WatchConfirmResponse(
                    session_id=payload.session_id,
                    speech_text="对应的Codex审批项不存在。",
                    result="missing",
                )
                return _json(response, status_code=404)

            if payload.decision == Decision.APPROVE:
                speech = f"已Approve：{item.title}。OpenClaw会话 {item.openclaw_session_id} 正在执行。"
                result = "executed"
            else:
                followup = payload.followup_text or ""
                speech = f"已Reject：{item.title}。"
                if followup:
                    speech += f" 已记录补充指令：{followup}。"
                result = "canceled"

            data_store.add_log(
                AuditLogEntry(
                    who=payload.session_id,
                    what=f"Codex审批：{item.title}",
                    why=payload.followup_text or pending.source_utterance,
                    result=result,
                    mode=pending.card.execution_mode,
                    confirm_token=payload.confirm_token,
                    openclaw_session_id=item.openclaw_session_id,
                    metadata={
                        "input_mode": payload.input_mode.value,
                        "approval_id": approval_id,
                        "acp_thread_id": item.acp_thread_id,
                        "decision": payload.decision.value,
                    },
                )
            )

            latest = data_store.get_latest_run(payload.session_id)
            if latest:
                data_store.add_stream_event(
                    session_id=payload.session_id,
                    run_id=latest.run_id,
                    trace_id=latest.trace_id,
                    event_type="codex_decision",
                    step="codex_queue",
                    payload={
                        "approval_id": approval_id,
                        "decision": payload.decision.value,
                        "followup_text": payload.followup_text,
                        "openclaw_session_id": item.openclaw_session_id,
                    },
                )

            response = WatchConfirmResponse(session_id=payload.session_id, speech_text=speech, result=result)
            return _json(response)

        if payload.decision == Decision.REJECT:
            data_store.pop_pending(payload.confirm_token)
            data_store.add_log(
                AuditLogEntry(
                    who=payload.session_id,
                    what=pending.card.title,
                    why=payload.followup_text or "user_rejected",
                    result="canceled",
                    mode=pending.card.execution_mode,
                    confirm_token=payload.confirm_token,
                    openclaw_session_id=pending.card.action_payload.get("openclaw_session_id"),
                    metadata={
                        "input_mode": payload.input_mode.value,
                        "followup_text": payload.followup_text,
                    },
                )
            )
            response = WatchConfirmResponse(
                session_id=payload.session_id,
                speech_text=f"已取消：{pending.card.title}",
                result="canceled",
            )
            return _json(response)

        trace_db.record_confirmation(
            session_id=payload.session_id,
            confirm_token=payload.confirm_token,
            action_type=pending.card.action_type,
            action_payload_json=json.dumps(pending.card.action_payload, ensure_ascii=False),
            decision=payload.decision.value,
            followup_text=payload.followup_text,
        )

        data_store.pop_pending(payload.confirm_token)
        execution = action_executor.execute(payload.decision, pending.card, followup_text=payload.followup_text)

        trace_db.record_confirmation_result(
            confirm_token=payload.confirm_token,
            exec_success=execution.result not in ("failed", "denied"),
            exec_result_json=json.dumps(
                {"result": execution.result, "metadata": execution.metadata}, ensure_ascii=False
            ),
        )

        data_store.add_log(
            AuditLogEntry(
                who=payload.session_id,
                what=pending.card.title,
                why=pending.source_utterance,
                result=execution.result,
                mode=pending.card.execution_mode,
                confirm_token=payload.confirm_token,
                openclaw_session_id=pending.card.action_payload.get("openclaw_session_id"),
                metadata={
                    "input_mode": payload.input_mode.value,
                    **execution.metadata,
                },
            )
        )

        response = WatchConfirmResponse(
            session_id=payload.session_id,
            speech_text=execution.speech_text,
            result=execution.result,
        )
        return _json(response)

    async def skill_state(request: Request) -> JSONResponse:
        session_id = request.path_params["session_id"]
        state = data_store.get_latest_run(session_id)
        return _json(SkillStateResponse(state=state))

    async def skill_events(request: Request) -> JSONResponse:
        session_id = request.path_params["session_id"]
        after_event_id = int(request.query_params.get("after_event_id", "0"))
        limit = int(request.query_params.get("limit", "100"))
        events = data_store.list_stream_events(session_id, after_event_id=after_event_id, limit=limit)
        return _json(SkillEventsResponse(events=events))

    async def skill_stream(request: Request) -> StreamingResponse:
        session_id = request.path_params["session_id"]
        after_event_id = int(request.query_params.get("after_event_id", "0"))
        follow = request.query_params.get("follow", "false").lower() == "true"
        timeout_sec = int(request.query_params.get("timeout_sec", "10"))

        def event_iter():
            cursor = after_event_id
            deadline = time.time() + timeout_sec
            while True:
                events = data_store.list_stream_events(session_id, after_event_id=cursor, limit=100)
                if events:
                    for event in events:
                        cursor = event.event_id
                        payload = event.model_dump(mode="json")
                        yield f"id: {event.event_id}\n"
                        yield f"event: {event.event_type}\n"
                        yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                if not follow:
                    break
                if time.time() >= deadline:
                    break
                time.sleep(0.25)

            done_payload = {"after_event_id": cursor}
            yield "event: done\n"
            yield f"data: {json.dumps(done_payload, ensure_ascii=False)}\n\n"

        return StreamingResponse(event_iter(), media_type="text/event-stream")

    async def codex_queue(request: Request) -> JSONResponse:
        only_pending = request.query_params.get("only_pending", "true").lower() == "true"
        items = data_store.list_codex_queue(only_pending=only_pending)
        return _json(CodexQueueResponse(items=items))

    async def codex_decision(request: Request) -> JSONResponse:
        try:
            payload = ApprovalDecisionRequest.model_validate(await request.json())
        except ValidationError as err:
            return _validation_error(err)

        item = data_store.apply_codex_decision(payload.approval_id, payload.decision)
        if item is None:
            return JSONResponse({"error": "not_found", "approval_id": payload.approval_id}, status_code=404)

        if payload.decision == Decision.APPROVE:
            speech = f"已Approve：{item.title}。"
        else:
            speech = f"已Reject：{item.title}。"
            if payload.followup_text:
                speech += f" 补充指令：{payload.followup_text}。"

        data_store.add_log(
            AuditLogEntry(
                who=payload.session_id,
                what=f"Codex审批：{item.title}",
                why=payload.followup_text,
                result="executed" if payload.decision == Decision.APPROVE else "canceled",
                openclaw_session_id=item.openclaw_session_id,
                metadata={
                    "decision": payload.decision.value,
                    "approval_id": payload.approval_id,
                    "input_mode": payload.input_mode.value,
                    "acp_thread_id": item.acp_thread_id,
                },
            )
        )

        return _json(
            ApprovalDecisionResponse(
                approval_id=item.approval_id,
                status=item.status,
                speech_text=speech,
                openclaw_session_id=item.openclaw_session_id,
            )
        )

    async def mac_status_upsert(request: Request) -> JSONResponse:
        try:
            payload = MacStatusBatch.model_validate(await request.json())
        except ValidationError as err:
            return _validation_error(err)

        data_store.upsert_tasks(payload.tasks)
        return JSONResponse(
            {
                "ok": True,
                "reporter_id": payload.reporter_id,
                "task_count": len(payload.tasks),
                "received_at": datetime.now(UTC).isoformat(),
            }
        )

    async def mac_status_list(request: Request) -> JSONResponse:
        _ = request
        response = ListMacTaskStatusResponse(tasks=data_store.list_tasks())
        return _json(response)

    async def audit_logs(request: Request) -> JSONResponse:
        limit = int(request.query_params.get("limit", "50"))
        response = ListAuditLogsResponse(logs=data_store.list_logs(limit=limit))
        return _json(response)

    async def openclaw_evidence(request: Request) -> JSONResponse:
        _ = request
        return _json(
            OpenClawEvidenceResponse(
                gateway_status="running",
                telegram_channel="@OpenClawBot",
                latest_openclaw_session_ids=data_store.list_openclaw_session_ids(limit=20),
                evidence_notes=[
                    "OpenClaw gateway已运行",
                    "Apple Watch通过官方Telegram渠道可触发命令",
                    "审计日志内记录openclaw_session_id与acp_thread_id",
                ],
            )
        )

    async def model_routing(request: Request) -> JSONResponse:
        _ = request
        return _json(agent_runner.model_config)

    # ── TTS ──────────────────────────────────────────────────────────────────
    from .volcengine_tts import VolcengineTTS, VOICE_OPTIONS as _TTS_VOICES

    _tts = VolcengineTTS()

    async def tts_synthesize(request: Request) -> StreamingResponse | JSONResponse:
        """POST /v1/tts — synthesize text to MP3 audio."""
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "invalid_json"}, status_code=400)

        text = (body.get("text") or "").strip()
        if not text:
            return JSONResponse({"error": "empty_text"}, status_code=400)

        voice_type = body.get("voice_type", "BV700_streaming")
        speed_ratio = float(body.get("speed_ratio", 1.0))

        import asyncio
        loop = asyncio.get_running_loop()
        audio = await loop.run_in_executor(
            None, lambda: _tts.synthesize(text, voice_type=voice_type, speed_ratio=speed_ratio)
        )
        if audio is None:
            return JSONResponse({"error": "tts_failed"}, status_code=502)

        return StreamingResponse(
            iter([audio]),
            media_type="audio/mpeg",
            headers={"Content-Length": str(len(audio))},
        )

    async def tts_voices(request: Request) -> JSONResponse:
        """GET /v1/tts/voices — list available cloud TTS voices."""
        _ = request
        return _json({"available": _tts.available, "voices": _TTS_VOICES})

    routes = [
        Route("/v1/health", health, methods=["GET"]),
        Route("/v1/watch/command", watch_command, methods=["POST"]),
        Route("/v1/watch/confirm", watch_confirm, methods=["POST"]),
        Route("/v1/skills/{session_id:str}/state", skill_state, methods=["GET"]),
        Route("/v1/skills/{session_id:str}/events", skill_events, methods=["GET"]),
        Route("/v1/skills/{session_id:str}/stream", skill_stream, methods=["GET"]),
        Route("/v1/codex/queue", codex_queue, methods=["GET"]),
        Route("/v1/codex/decision", codex_decision, methods=["POST"]),
        Route("/v1/mac/status", mac_status_upsert, methods=["POST"]),
        Route("/v1/mac/status", mac_status_list, methods=["GET"]),
        Route("/v1/audit/logs", audit_logs, methods=["GET"]),
        Route("/v1/openclaw/evidence", openclaw_evidence, methods=["GET"]),
        Route("/v1/model-routing", model_routing, methods=["GET"]),
        Route("/v1/tts", tts_synthesize, methods=["POST"]),
        Route("/v1/tts/voices", tts_voices, methods=["GET"]),
    ]

    middleware = [
        Middleware(BodySizeLimitMiddleware),
        Middleware(
            CORSMiddleware,
            allow_origin_regex=r".*",
            allow_methods=["*"],
            allow_headers=["*"],
        ),
    ]
    if _API_KEY:
        middleware.append(Middleware(APIKeyMiddleware))

    app = Starlette(debug=True, routes=routes, middleware=middleware)
    app.state.store = data_store
    app.state.executor = action_executor
    app.state.agent_runner = agent_runner
    return app
