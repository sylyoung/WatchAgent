from __future__ import annotations

import logging

from .llm_client import LLMClient
from .models import WatchCommandRequest, WatchReply
from .store import InMemoryStore

log = logging.getLogger(__name__)

SCHEDULE_KEYWORDS = {"今日日程", "今天日程", "早安简报", "schedule", "morning"}
WORK_KEYWORDS = {"工作进展", "汇报进展", "codex进展", "codex工作地怎么样了", "状态查询"}
RIDE_KEYWORDS = {"出行叫车", "叫车", "滴滴"}
MESSAGE_KEYWORDS = {
    "我的消息",
    "待回消息",
    "待回复消息",
    "未回复消息",
    "消息代回",
    "回复导师",
    "回复妈妈",
    "代回",
    "微信",
}
PACKAGE_KEYWORDS = {"查看快递", "快递", "物流", "包裹", "淘宝物流", "京东物流", "我的快递", "在途包裹"}
HEALTH_KEYWORDS = {"健康管理", "健康", "运动", "喝水", "睡眠", "吃药", "用药提醒"}

_llm = LLMClient()


def resolve_skill(utterance: str, skill_hint: str | None = None) -> str:
    # 1. Explicit skill_hint always wins
    text = (skill_hint or "").strip().lower()
    if text in {"schedule", "今日日程", "morning_brief", "morning"}:
        return "morning_brief"
    if text in {"work", "工作进展", "work_progress"}:
        return "work_progress"
    if text in {"ride", "出行叫车", "ride_hailing"}:
        return "ride_hailing"
    if text in {"message", "我的消息", "消息代回", "message_delegate", "message_inbox"}:
        return "message_inbox"
    if text in {"package", "查看快递", "package_tracking", "快递", "物流"}:
        return "package_tracking"
    if text in {"health", "健康管理", "health_manager"}:
        return "health_manager"

    u = utterance.strip().lower()
    all_skills = {"morning_brief", "work_progress", "ride_hailing", "message_inbox", "package_tracking", "health_manager"}

    # 2. LLM-first intent recognition (primary router)
    if _llm.available:
        intent = _llm.chat(
            system_prompt=(
                "你是意图识别助手。用户说了一句话，请判断属于以下哪个技能："
                "morning_brief（日程/简报/天气/早安/今天）、work_progress（工作/任务/进展/代码/项目）、"
                "ride_hailing（叫车/出行/打车/去哪/路线）、message_inbox（消息/回复/联系人/微信/聊天）、"
                "package_tracking（快递/物流/包裹/淘宝/京东/收货）、health_manager（健康/运动/睡眠/用药/心率/步数）。"
                "如果无法确定，回复 unknown。只回复技能名称，不要其他内容。"
            ),
            user_message=u,
            max_tokens=20,
            fallback="",
        ).strip().lower()
        if intent in all_skills:
            return intent

    # 3. Keyword fallback (when LLM unavailable or returns unknown)
    if any(k in u for k in SCHEDULE_KEYWORDS):
        return "morning_brief"
    if any(k in u for k in WORK_KEYWORDS):
        return "work_progress"
    if any(k in u for k in RIDE_KEYWORDS):
        return "ride_hailing"
    if any(k in u for k in MESSAGE_KEYWORDS):
        return "message_inbox"
    if any(k in u for k in PACKAGE_KEYWORDS):
        return "package_tracking"
    if any(k in u for k in HEALTH_KEYWORDS):
        return "health_manager"

    return "work_progress"


def attach_confirmation_tokens(reply: WatchReply, request: WatchCommandRequest, store: InMemoryStore) -> WatchReply:
    tokens: list[str] = []
    for card in reply.cards:
        if card.requires_confirmation:
            pending = store.create_pending(
                session_id=request.session_id,
                card=card,
                source_utterance=request.utterance,
            )
            tokens.append(pending.token)

    reply.requires_confirmation = bool(tokens)
    reply.confirm_token = tokens[0] if tokens else None
    reply.debug = {
        **reply.debug,
        "skill": resolve_skill(request.utterance, request.skill_hint),
        "card_count": len(reply.cards),
        "confirmable_cards": len(tokens),
    }
    return reply


