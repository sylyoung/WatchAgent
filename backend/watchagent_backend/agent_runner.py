"""LLM agent tool-call runner — replaces MainAgentOrchestrator."""

from __future__ import annotations

import json
import logging
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml  # PyYAML

from .llm_client import LLMClient
from .mac_data_providers import ChromeProvider, CodexAppProvider, CodexProvider, WeChatProvider
from .models import (
    ActionCard,
    ExecutionMode,
    ModelRoutingConfig,
    SkillRunState,
    SubAgentState,
    SubAgentTaskStatus,
    WatchCommandRequest,
    WatchReply,
)
from .store import InMemoryStore
from .tools_registry import build_handlers, get_schemas_for
from .trace_db import TraceDB

log = logging.getLogger(__name__)

_SKILLS_DIR = Path(__file__).parent.parent / "skills"
_MAX_ROUNDS = 3

# Default action card specs per skill, used when LLM is unavailable
_DEFAULT_CARDS: dict[str, dict | None] = {
    "ride_hailing": {
        "title": "滴滴叫车（默认设置）",
        "detail": "现在出发，请确认目的地",
        "action_type": "book_ride",
        "action_payload": {
            "destination": "",
            "depart": "now",
            "profile": "default",
            "openclaw_session_id": "ocw-ride-01",
        },
    },
    "message_inbox": {
        "title": "发送微信消息",
        "detail": "代发消息待确认",
        "action_type": "send_message",
        "action_payload": {
            "to": "联系人",
            "message": "",
            "channel": "wechat",
            "openclaw_session_id": "ocw-msg-01",
        },
    },
}

_pool = ThreadPoolExecutor(max_workers=8, thread_name_prefix="agent")


@dataclass
class SkillDef:
    skill_id: str
    first_speech: str
    tools: list[str]
    system_prompt: str  # body of the .md after the frontmatter


@dataclass
class _RunContext:
    run: SkillRunState
    session_id: str
    trace_id: str
    action_cards: list[ActionCard] = field(default_factory=list)
    final_speech: str = ""


class AgentRunner:
    def __init__(
        self,
        store: InMemoryStore,
        model_config: ModelRoutingConfig | None = None,
        trace_db: TraceDB | None = None,
    ) -> None:
        self.store = store
        self.model_config = model_config or ModelRoutingConfig()
        self.trace_db = trace_db
        self.llm = LLMClient()
        self.chrome = ChromeProvider()
        self.wechat = WeChatProvider()
        self.codex = CodexProvider()
        self.codex_app = CodexAppProvider()

    # ── Public API ───────────────────────────────────────────────────────────

    def start_run(self, request: WatchCommandRequest, skill_name: str) -> WatchReply:
        """Return first_speech immediately; run agent loop in background."""
        skill = self._load_skill(skill_name)

        intent_id = request.intent_id or f"intent-{skill_name}"
        run = SkillRunState(
            session_id=request.session_id,
            trace_id=request.trace_id,
            intent_id=intent_id,
            skill_name=skill_name,
            model_routing=self.model_config,
            tasks=[
                SubAgentTaskStatus(task_id=t, name=t, step_index=i + 1)
                for i, t in enumerate(skill.tools)
            ],
        )
        self.store.upsert_skill_run(run)
        if self.trace_db:
            self.trace_db.record_skill_run_start(
                run_id=run.run_id,
                session_id=request.session_id,
                trace_id=request.trace_id,
                skill_name=skill_name,
            )
        self.store.add_stream_event(
            session_id=request.session_id,
            run_id=run.run_id,
            trace_id=request.trace_id,
            event_type="run_started",
            step="planner",
            payload={
                "skill_name": skill_name,
                "intent_id": intent_id,
                "entry_mode": request.entry_mode.value,
                "model": self.model_config.primary_model,
            },
        )

        ctx = _RunContext(
            run=run,
            session_id=request.session_id,
            trace_id=request.trace_id,
        )
        _pool.submit(self._agent_loop, request, skill, ctx)

        return WatchReply(
            session_id=request.session_id,
            speech_text=skill.first_speech,
            cards=[],
            priority=3,
            debug={
                "skill": skill_name,
                "skill_run_id": run.run_id,
                "trace_id": request.trace_id,
                "intent_id": intent_id,
                "stream_path": f"/v1/skills/{request.session_id}/stream",
                "model": self.model_config.primary_model,
            },
        )

    # ── SKILL.md loading ─────────────────────────────────────────────────────

    def _load_skill(self, skill_name: str) -> SkillDef:
        path = _SKILLS_DIR / f"{skill_name}.md"
        if not path.exists():
            log.warning("SKILL.md not found for %s, using fallback", skill_name)
            return SkillDef(
                skill_id=skill_name,
                first_speech="收到，正在处理。",
                tools=[],
                system_prompt="",
            )

        raw = path.read_text(encoding="utf-8")
        # Split frontmatter
        if raw.startswith("---"):
            parts = raw.split("---", 2)
            fm = yaml.safe_load(parts[1]) if len(parts) >= 3 else {}
            body = parts[2].strip() if len(parts) >= 3 else ""
        else:
            fm = {}
            body = raw.strip()

        return SkillDef(
            skill_id=fm.get("skill_id", skill_name),
            first_speech=fm.get("first_speech", "收到，正在处理。"),
            tools=fm.get("tools", []),
            system_prompt=body,
        )

    # ── Agent loop ───────────────────────────────────────────────────────────

    def _agent_loop(self, request: WatchCommandRequest, skill: SkillDef, ctx: _RunContext) -> None:
        _completed = False
        try:
            providers = {
                "chrome": self.chrome,
                "wechat": self.wechat,
                "codex": self.codex,
                "codex_app": self.codex_app,
            }
            handlers = build_handlers(request, providers)
            tool_schemas = get_schemas_for(skill.tools)

            system_prompt = skill.system_prompt.replace("{{utterance}}", request.utterance)
            messages: list[dict] = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": request.utterance},
            ]

            if not self.llm.available or not tool_schemas:
                # No LLM available — fall back to executing all data tools directly
                self._fallback_run(request, skill, handlers, ctx)
                _completed = True
                return

            for _round in range(_MAX_ROUNDS):
                _llm_t0 = time.perf_counter()
                response = self.llm.chat_with_tools(messages, tools=tool_schemas)
                _llm_ms = int((time.perf_counter() - _llm_t0) * 1000)
                if self.trace_db:
                    self.trace_db.record_llm_exchange(
                        run_id=ctx.run.run_id,
                        session_id=ctx.session_id,
                        round_num=_round + 1,
                        messages=messages,
                        response_content=response.content,
                        tool_calls=response.tool_calls,
                        finish_reason=response.finish_reason,
                        duration_ms=_llm_ms,
                    )

                if not response.tool_calls:
                    # LLM produced final speech
                    speech = (response.content or "").strip()
                    if speech:
                        ctx.final_speech = speech
                        self._emit_speech_event(ctx, speech)
                    self._emit_run_completed(ctx)
                    _completed = True
                    return

                # Execute all tool calls in parallel
                tool_results = self._execute_parallel(request, handlers, response.tool_calls, ctx, round_num=_round + 1)

                # Append assistant message + tool results to messages
                messages.append(
                    {
                        "role": "assistant",
                        "content": response.content or "",
                        "tool_calls": [
                            {
                                "id": tc.id,
                                "type": "function",
                                "function": {
                                    "name": tc.function.name,
                                    "arguments": tc.function.arguments,
                                },
                            }
                            for tc in response.tool_calls
                        ],
                    }
                )
                for tc, result in zip(response.tool_calls, tool_results):
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": json.dumps(result, ensure_ascii=False),
                        }
                    )

            self._emit_run_completed(ctx)
            if self.trace_db:
                run = self.store.get_skill_run(ctx.run.run_id)
                self.trace_db.record_skill_run_end(
                    run_id=ctx.run.run_id,
                    state="completed",
                    merged_lines=run.merged_lines if run else [],
                )
            _completed = True
        except Exception as _exc:
            log.exception("_agent_loop crashed for session=%s skill=%s", ctx.session_id, skill.skill_id)
            if self.trace_db:
                try:
                    self.trace_db.record_skill_run_end(
                        run_id=ctx.run.run_id,
                        state="failed",
                        error_msg=str(_exc),
                    )
                except Exception:
                    pass
        finally:
            if not _completed:
                # Guarantee run_completed is always emitted even on unexpected exceptions
                try:
                    self._emit_run_completed(ctx)
                except Exception:
                    log.exception("Failed to emit run_completed in finally block")

    # ── Fallback (no LLM) ───────────────────────────────────────────────────

    def _fallback_run(
        self,
        request: WatchCommandRequest,
        skill: SkillDef,
        handlers: dict,
        ctx: _RunContext,
    ) -> None:
        """Execute data tools. Uses sequential calls for ≤2 tools, parallel pool for 3+."""
        # Inject current time as the first announcement for morning_brief
        if skill.skill_id == "morning_brief":
            from datetime import datetime
            now = datetime.now().astimezone()
            time_str = f"现在{now.hour}点{now.minute:02d}分。"
            self.store.add_stream_event(
                session_id=ctx.session_id,
                run_id=ctx.run.run_id,
                trace_id=ctx.trace_id,
                event_type="tool_result",
                step="time",
                payload={"summary": time_str},
            )

        data_tools = [t for t in skill.tools if t != "create_action_card"]

        if len(data_tools) <= 2:
            self._run_tools_sequential(data_tools, handlers, ctx)
        else:
            self._run_tools_parallel(data_tools, handlers, ctx)

        self._emit_default_action_card(request, skill, ctx)
        self._emit_run_completed(ctx)

    def _run_tools_sequential(self, data_tools: list[str], handlers: dict, ctx: _RunContext) -> None:
        """Run tools one-by-one on the current thread — no thread pool overhead."""
        for name in data_tools:
            handler = handlers.get(name)
            if handler is None:
                continue
            try:
                result = self._call_handler(handler, {})
                self.store.update_subagent_task(ctx.run.run_id, name, SubAgentState.DONE)
                summary = self._summarize_tool_result(name, result)
                self.store.append_run_line(ctx.run.run_id, summary)
                self.store.add_stream_event(
                    session_id=ctx.session_id,
                    run_id=ctx.run.run_id,
                    trace_id=ctx.trace_id,
                    event_type="tool_result",
                    step=name,
                    payload={"summary": summary, **result},
                )
            except Exception as exc:
                log.exception("Tool %s failed", name)
                self.store.update_subagent_task(ctx.run.run_id, name, SubAgentState.FAILED, error=str(exc))
                self.store.add_stream_event(
                    session_id=ctx.session_id,
                    run_id=ctx.run.run_id,
                    trace_id=ctx.trace_id,
                    event_type="tool_error",
                    step=name,
                    payload={"error": str(exc)},
                )

    def _run_tools_parallel(self, data_tools: list[str], handlers: dict, ctx: _RunContext) -> None:
        """Run 3+ tools in parallel via a temporary thread pool."""
        n_workers = max(1, min(len(data_tools), 8))
        tool_pool = ThreadPoolExecutor(max_workers=n_workers, thread_name_prefix="tool")

        futures = {}
        for name in data_tools:
            handler = handlers.get(name)
            if handler is None:
                continue
            future = tool_pool.submit(self._call_handler, handler, {})
            futures[future] = name

        _TOOL_TIMEOUT = 10
        remaining_futures = dict(futures)
        try:
            for future in as_completed(list(futures.keys()), timeout=_TOOL_TIMEOUT):
                name = remaining_futures.pop(future, None) or futures.get(future, "unknown")
                try:
                    result = future.result()
                    self.store.update_subagent_task(ctx.run.run_id, name, SubAgentState.DONE)
                    summary = self._summarize_tool_result(name, result)
                    self.store.append_run_line(ctx.run.run_id, summary)
                    self.store.add_stream_event(
                        session_id=ctx.session_id,
                        run_id=ctx.run.run_id,
                        trace_id=ctx.trace_id,
                        event_type="tool_result",
                        step=name,
                        payload={"summary": summary, **result},
                    )
                except Exception as exc:
                    log.exception("Fallback tool %s failed", name)
                    self.store.update_subagent_task(ctx.run.run_id, name, SubAgentState.FAILED, error=str(exc))
                    self.store.add_stream_event(
                        session_id=ctx.session_id,
                        run_id=ctx.run.run_id,
                        trace_id=ctx.trace_id,
                        event_type="tool_error",
                        step=name,
                        payload={"error": str(exc)},
                    )
        except FuturesTimeoutError:
            pass

        for future, name in remaining_futures.items():
            if not future.done():
                future.cancel()
                self.store.update_subagent_task(ctx.run.run_id, name, SubAgentState.FAILED, error="timeout")
                self.store.add_stream_event(
                    session_id=ctx.session_id,
                    run_id=ctx.run.run_id,
                    trace_id=ctx.trace_id,
                    event_type="tool_error",
                    step=name,
                    payload={"error": "timeout"},
                )

        tool_pool.shutdown(wait=False)

    def _emit_default_action_card(self, request: WatchCommandRequest, skill: SkillDef, ctx: _RunContext) -> None:
        """Emit default action card if skill has one."""
        if "create_action_card" not in skill.tools or skill.skill_id not in _DEFAULT_CARDS:
            return
        card_spec = _DEFAULT_CARDS[skill.skill_id]
        if card_spec:
            card = self._make_action_card(card_spec, request)
            confirm_token = None
            if card:
                ctx.action_cards.append(card)
                pending = self.store.create_pending(
                    session_id=ctx.session_id,
                    card=card,
                    source_utterance=request.utterance,
                    ttl_sec=600,
                )
                confirm_token = pending.token
            self.store.add_stream_event(
                session_id=ctx.session_id,
                run_id=ctx.run.run_id,
                trace_id=ctx.trace_id,
                event_type="action_card_created",
                step="create_action_card",
                payload={**card_spec, "confirm_token": confirm_token},
            )

    # ── Parallel tool execution ──────────────────────────────────────────────

    def _execute_parallel(
        self,
        request: WatchCommandRequest,
        handlers: dict,
        tool_calls: list,
        ctx: _RunContext,
        round_num: int = 1,
    ) -> list[dict]:
        # Fresh per-call pool so tool threads don't compete with _agent_loop
        # threads already occupying _pool (avoids nested-pool deadlock).
        n_workers = max(1, min(len(tool_calls), 8))
        tool_pool = ThreadPoolExecutor(max_workers=n_workers, thread_name_prefix="tool")

        futures = {}
        for i, tc in enumerate(tool_calls):
            name = tc.function.name
            handler = handlers.get(name)
            if handler is None:
                log.warning("Unknown tool: %s", name)
                futures[id(tc)] = (tc, None)
                continue
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}

            future = tool_pool.submit(self._timed_call_handler, handler, args)
            futures[future] = (tc, i)

        _TOOL_TIMEOUT = 15  # seconds; AppleScript/browser tools can be slow

        ordered: dict[str, dict] = {}
        remaining = dict(futures)
        try:
            for future in as_completed(list(futures.keys()), timeout=_TOOL_TIMEOUT):
                remaining.pop(future, None)
                tc, call_index = futures[future]
                name = tc.function.name
                try:
                    result, dur_ms = future.result()
                except Exception as exc:
                    log.exception("Tool %s failed", name)
                    result = {"error": str(exc)}
                    dur_ms = 0
                    self.store.update_subagent_task(ctx.run.run_id, name, SubAgentState.FAILED, error=str(exc))
                    self.store.add_stream_event(
                        session_id=ctx.session_id,
                        run_id=ctx.run.run_id,
                        trace_id=ctx.trace_id,
                        event_type="tool_error",
                        step=name,
                        payload={"error": str(exc)},
                    )
                    if self.trace_db:
                        self.trace_db.record_tool_call(
                            run_id=ctx.run.run_id,
                            session_id=ctx.session_id,
                            round_num=round_num,
                            call_index=call_index,
                            tool_name=name,
                            input_json=tc.function.arguments,
                            output_json=json.dumps(result, ensure_ascii=False),
                            success=False,
                            error_msg=str(exc),
                            duration_ms=dur_ms,
                        )
                else:
                    self.store.update_subagent_task(ctx.run.run_id, name, SubAgentState.DONE)
                    if self.trace_db:
                        self.trace_db.record_tool_call(
                            run_id=ctx.run.run_id,
                            session_id=ctx.session_id,
                            round_num=round_num,
                            call_index=call_index,
                            tool_name=name,
                            input_json=tc.function.arguments,
                            output_json=json.dumps(result, ensure_ascii=False),
                            success=True,
                            duration_ms=dur_ms,
                        )
                    if name == "create_action_card":
                        card_spec = result.get("card_spec", {})
                        card = self._make_action_card(card_spec, request)
                        confirm_token = None
                        if card:
                            ctx.action_cards.append(card)
                            pending = self.store.create_pending(
                                session_id=ctx.session_id,
                                card=card,
                                source_utterance=request.utterance,
                                ttl_sec=600,
                            )
                            confirm_token = pending.token
                        self.store.add_stream_event(
                            session_id=ctx.session_id,
                            run_id=ctx.run.run_id,
                            trace_id=ctx.trace_id,
                            event_type="action_card_created",
                            step=name,
                            payload={**card_spec, "confirm_token": confirm_token},
                        )
                    else:
                        summary = self._summarize_tool_result(name, result)
                        self.store.append_run_line(ctx.run.run_id, summary)
                        self.store.add_stream_event(
                            session_id=ctx.session_id,
                            run_id=ctx.run.run_id,
                            trace_id=ctx.trace_id,
                            event_type="tool_result",
                            step=name,
                            payload={"summary": summary, **result},
                        )
                ordered[tc.id] = result
        except FuturesTimeoutError:
            pass  # timed-out tools handled below

        # Emit timeout errors for tools that didn't complete
        for future, (tc, call_index) in remaining.items():
            if not future.done():
                future.cancel()
            name = tc.function.name
            self.store.update_subagent_task(ctx.run.run_id, name, SubAgentState.FAILED, error="timeout")
            self.store.add_stream_event(
                session_id=ctx.session_id,
                run_id=ctx.run.run_id,
                trace_id=ctx.trace_id,
                event_type="tool_error",
                step=name,
                payload={"error": "timeout"},
            )
            if self.trace_db:
                self.trace_db.record_tool_call(
                    run_id=ctx.run.run_id,
                    session_id=ctx.session_id,
                    round_num=round_num,
                    call_index=call_index,
                    tool_name=name,
                    input_json=tc.function.arguments,
                    output_json=None,
                    success=False,
                    error_msg="timeout",
                )
            ordered[tc.id] = {"error": "timeout"}

        tool_pool.shutdown(wait=False)

        # Return results in original tool_calls order
        return [ordered.get(tc.id, {}) for tc in tool_calls]

    @staticmethod
    def _call_handler(handler, args: dict) -> dict:
        if args:
            return handler(**args)
        return handler()

    @staticmethod
    def _timed_call_handler(handler, args: dict) -> tuple[dict, int]:
        t0 = time.perf_counter()
        result = AgentRunner._call_handler(handler, args)  # exceptions propagate
        return result, int((time.perf_counter() - t0) * 1000)

    @staticmethod
    def _summarize_tool_result(tool_name: str, result: dict) -> str:
        """Generate a brief human-readable summary of a tool result."""
        if tool_name == "get_weather":
            src = result.get("source", "unavailable")
            if src == "unavailable":
                return "天气：暂无数据。"
            temp = result.get("temp_c", "?")
            hi = result.get("today_max_c", "?")
            lo = result.get("today_min_c", "?")
            cond = result.get("condition", "")
            loc = result.get("location", "")
            return f"天气：{loc}{'，' if loc else ''}{cond}{'，' if cond else ''}当前{temp}°C，{lo}-{hi}°C。"
        if tool_name == "get_wechat_messages":
            count = result.get("count", 0)
            msgs = result.get("messages", [])
            if not count:
                return "微信：暂无未读消息。"
            preview = "；".join(msgs[:3])
            return f"微信：{count}条未读。{preview}。"
        if tool_name == "get_todos":
            count = result.get("count", 0)
            todos = result.get("todos", [])
            if not todos:
                return "待办：今日暂无待办。"
            lines = [t.get("title", "") for t in todos[:3]]
            return f"待办：今日{count}项。{'；'.join(lines)}。"
        if tool_name == "get_codex_status":
            if result.get("error"):
                return "Codex：无法连接，请确认 Codex.app 已打开。"
            running = result.get("running", [])
            awaiting = result.get("awaiting", [])
            completed = result.get("completed", [])
            parts = []
            if running:
                parts.append(f"{len(running)}个进行中")
            if awaiting:
                parts.append(f"{len(awaiting)}个待审批")
            if completed:
                parts.append(f"{len(completed)}个已完成")
            return f"Codex：{'，'.join(parts)}。" if parts else "Codex：无活跃任务。"
        if tool_name == "get_dev_status":
            git = result.get("git_status")
            commits = result.get("recent_commits", [])
            parts = []
            if git and git.get("total_changes", 0) > 0:
                parts.append(f"仓库{git['repo']}有{git['total_changes']}个待提交变更")
            elif git:
                parts.append(f"仓库{git['repo']}工作区干净")
            for c in commits[:2]:
                parts.append(f"{c['hash']} {c['message'][:20]}（{c['time']}）")
            return f"开发：{'；'.join(parts)}。" if parts else "开发状态：无可用数据。"
        if tool_name in ("get_taobao_logistics", "get_jd_logistics"):
            platform = "淘宝" if "taobao" in tool_name else "京东"
            count = result.get("count", 0)
            items = result.get("items", [])
            if not count:
                return f"{platform}：暂无待收货。"
            names = "、".join(it.get("item_name", "")[:8] for it in items[:3] if it.get("item_name"))
            return f"{platform}：{count}件待收货。{names}。" if names else f"{platform}：{count}件待收货。"
        if tool_name == "get_exercise_data":
            steps = result.get("steps", 0)
            cal = result.get("active_calories", 0)
            return f"运动：今日{steps}步，{cal}千卡。"
        if tool_name == "get_heart_data":
            hr = result.get("heart_rate")
            spo2 = result.get("blood_oxygen")
            parts = []
            if hr:
                parts.append(f"心率{hr}bpm")
            if spo2:
                parts.append(f"血氧{spo2}%")
            return f"心率：{'，'.join(parts)}。" if parts else "心率：暂无数据。"
        if tool_name == "get_sleep_data":
            hours = result.get("sleep_hours")
            deep = result.get("sleep_deep_minutes")
            return f"睡眠：昨晚{hours}小时，深睡{deep}分钟。" if hours else "睡眠：暂无数据。"
        if tool_name == "get_medication_reminder":
            reminder = result.get("reminder", "")
            return f"用药：{reminder}。"
        return f"{tool_name}: {json.dumps(result, ensure_ascii=False)[:60]}"

    @staticmethod
    def _make_action_card(spec: dict, request: WatchCommandRequest) -> ActionCard | None:
        try:
            return ActionCard(
                title=spec.get("title", "操作"),
                detail=spec.get("detail", ""),
                action_type=spec.get("action_type", "confirm_receipt"),
                action_payload=spec.get("action_payload", {}),
                execution_mode=ExecutionMode.DEMO,
                requires_confirmation=True,
                priority=2,
            )
        except Exception:
            log.exception("Failed to create ActionCard from spec: %s", spec)
            return None

    def _emit_speech_event(self, ctx: _RunContext, speech: str) -> None:
        self.store.add_stream_event(
            session_id=ctx.session_id,
            run_id=ctx.run.run_id,
            trace_id=ctx.trace_id,
            event_type="final_speech",
            step="agent",
            payload={"speech_text": speech},
        )

    def _emit_run_completed(self, ctx: _RunContext) -> None:
        run = self.store.get_skill_run(ctx.run.run_id)
        merged = run.merged_lines if run else []
        self.store.add_stream_event(
            session_id=ctx.session_id,
            run_id=ctx.run.run_id,
            trace_id=ctx.trace_id,
            event_type="run_completed",
            step="planner",
            payload={
                "line_count": len(merged),
                "merged_lines": merged,
                "action_cards": len(ctx.action_cards),
            },
        )
