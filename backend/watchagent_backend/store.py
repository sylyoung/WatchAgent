from __future__ import annotations

from datetime import UTC, datetime, timedelta
from threading import RLock
from uuid import uuid4

from .models import (
    ActionCard,
    ApprovalItem,
    ApprovalStatus,
    AuditLogEntry,
    Decision,
    MacTaskStatus,
    PendingAction,
    SkillRunState,
    SkillRunStateValue,
    SkillStreamEvent,
    SubAgentState,
)


class InMemoryStore:
    def __init__(self) -> None:
        self._lock = RLock()
        self._pending: dict[str, PendingAction] = {}
        self._tasks: dict[str, MacTaskStatus] = {}
        self._logs: list[AuditLogEntry] = []

        self._skill_runs: dict[str, SkillRunState] = {}
        self._latest_run_by_session: dict[str, str] = {}
        self._events_by_session: dict[str, list[SkillStreamEvent]] = {}
        self._next_event_id = 1

        self._codex_queue: dict[str, ApprovalItem] = {}
        self._codex_completed_unread: set[str] = set()

    def create_pending(self, session_id: str, card: ActionCard, source_utterance: str, ttl_sec: int = 180) -> PendingAction:
        now = datetime.now(UTC)
        token = str(uuid4())
        card.confirm_token = token
        pending = PendingAction(
            token=token,
            session_id=session_id,
            created_at=now,
            expires_at=now + timedelta(seconds=ttl_sec),
            card=card,
            source_utterance=source_utterance,
        )
        with self._lock:
            self._pending[token] = pending
        return pending

    def get_pending(self, token: str) -> PendingAction | None:
        with self._lock:
            return self._pending.get(token)

    def pop_pending(self, token: str) -> PendingAction | None:
        with self._lock:
            return self._pending.pop(token, None)

    def upsert_tasks(self, tasks: list[MacTaskStatus]) -> None:
        with self._lock:
            for task in tasks:
                self._tasks[task.task_id] = task

    def list_tasks(self) -> list[MacTaskStatus]:
        with self._lock:
            return sorted(
                self._tasks.values(),
                key=lambda x: (x.state.value != "running", -x.progress, x.task_title),
            )

    def add_log(self, entry: AuditLogEntry) -> None:
        with self._lock:
            self._logs.append(entry)

    def list_logs(self, limit: int = 50) -> list[AuditLogEntry]:
        with self._lock:
            return list(reversed(self._logs[-limit:]))

    def seed_default_tasks(self) -> None:
        if self.list_tasks():
            return

        now = datetime.now(UTC)
        defaults = [
            MacTaskStatus(
                task_id="thesis-32",
                task_title="毕业论文修改第32轮",
                state="running",
                progress=82,
                action_needed="确认是否发送当前 PDF 至微信传输助手",
                last_update=now,
            ),
            MacTaskStatus(
                task_id="lobster-video",
                task_title="龙虾大赛视频编辑流程",
                state="running",
                progress=68,
                action_needed="上传原始素材后可自动生成 1分30秒版本",
                last_update=now,
            ),
            MacTaskStatus(
                task_id="stroke-bci",
                task_title="中风病人脑机接口基础解码实验",
                state="done",
                progress=100,
                action_needed="确认结果表格后可输出图表",
                last_update=now,
            ),
            MacTaskStatus(
                task_id="neurips-crawl",
                task_title="NeurIPS 2025 论文检索",
                state="blocked",
                progress=42,
                blocked_reason="Google Scholar crawler blocked",
                action_needed="是否同意重新尝试爬取",
                last_update=now,
            ),
            MacTaskStatus(
                task_id="home-ticket",
                task_title="后台任务监控",
                state="running",
                progress=35,
                action_needed="后台存在 3 个 bash 进程，持续追踪中",
                last_update=now,
            ),
        ]
        self.upsert_tasks(defaults)

    def _default_codex_items(self) -> list[ApprovalItem]:
        return [
            ApprovalItem(
                title="论文第32轮终稿是否发送至微信传输助手",
                question="是否 approve 发送当前 PDF 给微信传输助手？",
                suggested_action="approve",
                openclaw_session_id="ocw-thesis-32",
                acp_thread_id="acp-thread-001",
                priority=3,
            ),
            ApprovalItem(
                title="NeurIPS Scholar 任务是否重试",
                question="爬虫被拦截，是否 reject 当前方案并改用代理重试？",
                suggested_action="reject + followup",
                openclaw_session_id="ocw-neurips-25",
                acp_thread_id="acp-thread-002",
                priority=2,
            ),
            ApprovalItem(
                title="龙虾大赛视频自动剪辑参数确认",
                question="是否 approve 使用 1分30秒默认模板导出？",
                suggested_action="approve",
                openclaw_session_id="ocw-lobster-video",
                acp_thread_id="acp-thread-003",
                priority=2,
            ),
        ]

    def seed_codex_queue(self, force_reset: bool = False) -> None:
        with self._lock:
            if self._codex_queue and not force_reset:
                return
            if force_reset:
                self._codex_queue.clear()
                self._codex_completed_unread.clear()
            for item in self._default_codex_items():
                self._codex_queue[item.approval_id] = item

    def list_codex_queue(self, only_pending: bool = True, refill_if_empty: bool = False) -> list[ApprovalItem]:
        self.seed_codex_queue()
        with self._lock:
            items = list(self._codex_queue.values())

        if only_pending:
            items = [x for x in items if x.status == ApprovalStatus.PENDING]
            if refill_if_empty and not items:
                # Demo stability: if a previous run consumed all approvals, refill defaults.
                self.seed_codex_queue(force_reset=True)
                with self._lock:
                    items = list(self._codex_queue.values())
                items = [x for x in items if x.status == ApprovalStatus.PENDING]

        return sorted(items, key=lambda x: (-x.priority, x.created_at))

    def apply_codex_decision(self, approval_id: str, decision: Decision) -> ApprovalItem | None:
        with self._lock:
            item = self._codex_queue.get(approval_id)
            if item is None:
                return None

            item.status = ApprovalStatus.APPROVED if decision == Decision.APPROVE else ApprovalStatus.REJECTED
            item.updated_at = datetime.now(UTC)
            self._codex_queue[approval_id] = item
            self._codex_completed_unread.add(approval_id)
            return item

    def codex_brief_summary(self, refill_if_empty: bool = False, mark_completed_read: bool = False) -> dict:
        self.seed_codex_queue()
        with self._lock:
            items = list(self._codex_queue.values())

        pending = [x for x in items if x.status == ApprovalStatus.PENDING]
        if refill_if_empty and not pending:
            self.seed_codex_queue(force_reset=True)
            with self._lock:
                items = list(self._codex_queue.values())
            pending = [x for x in items if x.status == ApprovalStatus.PENDING]

        with self._lock:
            completed_unread_ids = [x for x in self._codex_completed_unread if x in self._codex_queue]
            completed_unread_items = [self._codex_queue[x] for x in completed_unread_ids]
            if mark_completed_read:
                self._codex_completed_unread.difference_update(completed_unread_ids)

        return {
            "pending_count": len(pending),
            "completed_unread_count": len(completed_unread_items),
            "pending_items": [x.model_dump(mode="json") for x in pending],
            "completed_unread_items": [x.model_dump(mode="json") for x in completed_unread_items],
        }

    def upsert_skill_run(self, run: SkillRunState) -> None:
        with self._lock:
            self._skill_runs[run.run_id] = run
            self._latest_run_by_session[run.session_id] = run.run_id

    def get_skill_run(self, run_id: str) -> SkillRunState | None:
        with self._lock:
            return self._skill_runs.get(run_id)

    def get_latest_run(self, session_id: str) -> SkillRunState | None:
        with self._lock:
            run_id = self._latest_run_by_session.get(session_id)
            if run_id is None:
                return None
            return self._skill_runs.get(run_id)

    def update_subagent_task(
        self,
        run_id: str,
        task_id: str,
        state: SubAgentState,
        summary: str | None = None,
        error: str | None = None,
    ) -> SkillRunState | None:
        with self._lock:
            run = self._skill_runs.get(run_id)
            if run is None:
                return None

            for task in run.tasks:
                if task.task_id != task_id:
                    continue
                task.state = state
                if state == SubAgentState.RUNNING and task.started_at is None:
                    task.started_at = datetime.now(UTC)
                if state in {SubAgentState.DONE, SubAgentState.FAILED}:
                    task.finished_at = datetime.now(UTC)
                if summary:
                    task.summary = summary
                if error:
                    task.error = error
                break

            all_done = all(t.state in {SubAgentState.DONE, SubAgentState.FAILED} for t in run.tasks)
            if all_done and run.state == SkillRunStateValue.RUNNING:
                run.state = SkillRunStateValue.COMPLETED
                run.finished_at = datetime.now(UTC)

            self._skill_runs[run_id] = run
            return run

    def append_run_line(self, run_id: str, line: str) -> None:
        with self._lock:
            run = self._skill_runs.get(run_id)
            if run is None:
                return
            run.merged_lines.append(line)
            self._skill_runs[run_id] = run

    def set_first_response_ms(self, run_id: str, latency_ms: int) -> None:
        with self._lock:
            run = self._skill_runs.get(run_id)
            if run is None:
                return
            run.first_response_ms = latency_ms
            self._skill_runs[run_id] = run

    def add_stream_event(
        self,
        *,
        session_id: str,
        run_id: str,
        trace_id: str,
        event_type: str,
        step: str,
        payload: dict,
    ) -> SkillStreamEvent:
        with self._lock:
            event = SkillStreamEvent(
                event_id=self._next_event_id,
                session_id=session_id,
                run_id=run_id,
                trace_id=trace_id,
                event_type=event_type,
                step=step,
                payload=payload,
            )
            self._next_event_id += 1
            self._events_by_session.setdefault(session_id, []).append(event)
            return event

    def list_stream_events(self, session_id: str, after_event_id: int = 0, limit: int = 100) -> list[SkillStreamEvent]:
        with self._lock:
            events = self._events_by_session.get(session_id, [])
            filtered = [e for e in events if e.event_id > after_event_id]
            return filtered[:limit]

    def list_openclaw_session_ids(self, limit: int = 20) -> list[str]:
        ids: list[str] = []
        for log in self.list_logs(limit=200):
            if log.openclaw_session_id:
                ids.append(log.openclaw_session_id)
        dedup: list[str] = []
        for sid in ids:
            if sid in dedup:
                continue
            dedup.append(sid)
            if len(dedup) >= limit:
                break
        return dedup
