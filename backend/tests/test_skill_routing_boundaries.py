from __future__ import annotations

from watchagent_backend.skills import resolve_skill


def test_skill_hint_precedence_over_utterance() -> None:
    assert resolve_skill("滴滴叫车", skill_hint="morning_brief") == "morning_brief"
    assert resolve_skill("今日日程", skill_hint="ride_hailing") == "ride_hailing"
    assert resolve_skill("回复妈妈", skill_hint="work_progress") == "work_progress"


def test_keyword_routing_without_skill_hint() -> None:
    assert resolve_skill("今日日程") == "morning_brief"
    assert resolve_skill("我的codex工作地怎么样了，汇报进展") == "work_progress"
    assert resolve_skill("帮我滴滴叫一辆车") == "ride_hailing"
    assert resolve_skill("我的消息里有哪些待回复") == "message_inbox"
    assert resolve_skill("帮我回复妈妈说正在抢票了") == "message_inbox"


def test_unknown_utterance_fallbacks_to_work_progress() -> None:
    assert resolve_skill("这是一个未知指令") == "work_progress"
    assert resolve_skill("random unknown text") == "work_progress"
