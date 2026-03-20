from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class InputMode(str, Enum):
    VOICE = "voice"
    GESTURE = "gesture"
    TAP = "tap"


class EntryMode(str, Enum):
    COMPLICATION = "complication"
    SIRI = "siri"
    TAP = "tap"


class TaskState(str, Enum):
    RUNNING = "running"
    BLOCKED = "blocked"
    DONE = "done"


class Decision(str, Enum):
    APPROVE = "approve"
    REJECT = "reject"


class ExecutionMode(str, Enum):
    DEMO = "demo"
    LIVE = "live"


class SubAgentState(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class SkillRunStateValue(str, Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class HealthSnapshot(BaseModel):
    heart_rate: float | None = None
    resting_heart_rate: float | None = None
    steps: int | None = None
    active_calories: float | None = None
    blood_oxygen: float | None = None
    sleep_hours: float | None = None
    sleep_deep_minutes: int | None = None
    sleep_rem_minutes: int | None = None


class WeatherSnapshot(BaseModel):
    location_name: str | None = None
    temp_c: float | None = None
    feels_like_c: float | None = None
    humidity: float | None = None
    condition_description: str | None = None
    today_max_c: float | None = None
    today_min_c: float | None = None
    wind_speed_kmh: float | None = None
    uv_index: int | None = None


class DeviceContext(BaseModel):
    watch_model: str | None = Field(default=None, description="e.g., Apple Watch S9")
    locale: str | None = Field(default="zh-CN")
    timezone: str | None = Field(default="Asia/Shanghai")
    battery_level: float | None = Field(default=None, ge=0, le=100)
    connectivity: str | None = Field(default="wifi")
    health_snapshot: HealthSnapshot | None = None
    weather_snapshot: WeatherSnapshot | None = None
    latitude: float | None = None
    longitude: float | None = None


class ModelRoutingConfig(BaseModel):
    primary_model: str = "doubao-mini"
    escalation_model: str = "doubao-pro"
    timeout_ms: int = 900
    max_parallel_subagents: int = 5


class WatchCommandRequest(BaseModel):
    session_id: str
    utterance: str
    skill_hint: str | None = None
    device_context: DeviceContext = Field(default_factory=DeviceContext)
    input_mode: InputMode = InputMode.VOICE
    entry_mode: EntryMode = EntryMode.TAP
    intent_id: str | None = None
    trace_id: str = Field(default_factory=lambda: str(uuid4()))
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ActionCard(BaseModel):
    card_id: str = Field(default_factory=lambda: str(uuid4()))
    title: str
    detail: str
    action_type: str
    action_payload: dict[str, Any] = Field(default_factory=dict)
    requires_confirmation: bool = True
    execution_mode: ExecutionMode = ExecutionMode.DEMO
    priority: int = Field(default=1, ge=0, le=3)
    confirm_token: str | None = None
    cta_approve: str = "确认"
    cta_reject: str = "取消"
    primary_action: str = "approve"
    reject_mode: str = "button"


class WatchReply(BaseModel):
    request_id: str = Field(default_factory=lambda: str(uuid4()))
    session_id: str
    speech_text: str
    cards: list[ActionCard] = Field(default_factory=list)
    requires_confirmation: bool = False
    confirm_token: str | None = None
    priority: int = Field(default=1, ge=0, le=3)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    debug: dict[str, Any] = Field(default_factory=dict)


class WatchConfirmRequest(BaseModel):
    session_id: str
    confirm_token: str
    decision: Decision
    input_mode: InputMode = InputMode.VOICE
    followup_text: str | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class WatchConfirmResponse(BaseModel):
    request_id: str = Field(default_factory=lambda: str(uuid4()))
    session_id: str
    speech_text: str
    result: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class MacTaskStatus(BaseModel):
    task_id: str
    task_title: str
    state: TaskState
    progress: float = Field(ge=0, le=100)
    last_update: datetime = Field(default_factory=lambda: datetime.now(UTC))
    action_needed: str | None = None
    blocked_reason: str | None = None
    source: str = "mac_agent"


class MacStatusBatch(BaseModel):
    reporter_id: str = "local-mac"
    tasks: list[MacTaskStatus]
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class AuditLogEntry(BaseModel):
    log_id: str = Field(default_factory=lambda: str(uuid4()))
    who: str
    when: datetime = Field(default_factory=lambda: datetime.now(UTC))
    what: str
    why: str | None = None
    result: str
    mode: ExecutionMode = ExecutionMode.DEMO
    confirm_token: str | None = None
    openclaw_session_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class PendingAction(BaseModel):
    token: str
    session_id: str
    created_at: datetime
    expires_at: datetime
    card: ActionCard
    source_utterance: str


class SubAgentTaskStatus(BaseModel):
    task_id: str
    name: str
    step_index: int
    state: SubAgentState = SubAgentState.PENDING
    summary: str | None = None
    error: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


class SkillRunState(BaseModel):
    run_id: str = Field(default_factory=lambda: str(uuid4()))
    session_id: str
    trace_id: str
    intent_id: str
    skill_name: str
    state: SkillRunStateValue = SkillRunStateValue.RUNNING
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    finished_at: datetime | None = None
    first_response_ms: int | None = None
    model_routing: ModelRoutingConfig = Field(default_factory=ModelRoutingConfig)
    tasks: list[SubAgentTaskStatus] = Field(default_factory=list)
    merged_lines: list[str] = Field(default_factory=list)


class SkillStreamEvent(BaseModel):
    event_id: int
    session_id: str
    run_id: str
    trace_id: str
    event_type: str
    step: str
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ApprovalItem(BaseModel):
    approval_id: str = Field(default_factory=lambda: str(uuid4()))
    title: str
    question: str
    suggested_action: str | None = None
    openclaw_session_id: str
    acp_thread_id: str
    status: ApprovalStatus = ApprovalStatus.PENDING
    priority: int = 2
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ApprovalDecisionRequest(BaseModel):
    session_id: str
    approval_id: str
    decision: Decision
    followup_text: str | None = None
    input_mode: InputMode = InputMode.VOICE


class ApprovalDecisionResponse(BaseModel):
    approval_id: str
    status: ApprovalStatus
    speech_text: str
    openclaw_session_id: str


class CodexQueueResponse(BaseModel):
    items: list[ApprovalItem]


class SkillStateResponse(BaseModel):
    state: SkillRunState | None


class SkillEventsResponse(BaseModel):
    events: list[SkillStreamEvent]


class OpenClawEvidenceResponse(BaseModel):
    gateway_status: str
    telegram_channel: str
    latest_openclaw_session_ids: list[str]
    evidence_notes: list[str]


class ListAuditLogsResponse(BaseModel):
    logs: list[AuditLogEntry]


class ListMacTaskStatusResponse(BaseModel):
    tasks: list[MacTaskStatus]


class SecurityPolicy(BaseModel):
    """Declares per-action-type security requirements."""
    action_type: str
    requires_confirmation: bool = True
    requires_api_key: bool = False
    allowed_execution_modes: list[str] = Field(default_factory=lambda: ["demo"])
    max_payload_size: int = 10000
    description: str = ""


# Default security policies for all known action types
DEFAULT_SECURITY_POLICIES: dict[str, SecurityPolicy] = {
    "send_message": SecurityPolicy(
        action_type="send_message",
        requires_confirmation=True,
        allowed_execution_modes=["demo", "live"],
        description="Send message via WeChat — always requires user confirmation",
    ),
    "add_todo": SecurityPolicy(
        action_type="add_todo",
        requires_confirmation=True,
        allowed_execution_modes=["demo", "live"],
        description="Add a todo item",
    ),
    "send_pdf": SecurityPolicy(
        action_type="send_pdf",
        requires_confirmation=True,
        allowed_execution_modes=["demo", "live"],
        description="Send PDF file",
    ),
    "retry_crawler": SecurityPolicy(
        action_type="retry_crawler",
        requires_confirmation=True,
        allowed_execution_modes=["demo", "live"],
        description="Retry a blocked crawler task",
    ),
    "book_ride": SecurityPolicy(
        action_type="book_ride",
        requires_confirmation=True,
        allowed_execution_modes=["demo"],
        description="Book a ride — demo only",
    ),
    "confirm_receipt": SecurityPolicy(
        action_type="confirm_receipt",
        requires_confirmation=True,
        allowed_execution_modes=["demo", "live"],
        description="Confirm package receipt",
    ),
    "codex_approval": SecurityPolicy(
        action_type="codex_approval",
        requires_confirmation=True,
        allowed_execution_modes=["live"],
        description="Approve/reject in Codex app — LIVE mode required",
    ),
    "codex_decision": SecurityPolicy(
        action_type="codex_decision",
        requires_confirmation=True,
        allowed_execution_modes=["live"],
        description="Codex queue decision",
    ),
}
