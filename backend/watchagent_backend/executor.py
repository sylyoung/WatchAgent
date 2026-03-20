from __future__ import annotations

from dataclasses import dataclass

from .mac_data_providers import CodexAppProvider, WeChatProvider
from .models import ActionCard, Decision, ExecutionMode

_ALLOWED_ACTION_TYPES = frozenset({
    "send_message", "add_todo", "send_pdf", "retry_crawler",
    "book_ride", "confirm_receipt", "codex_approval", "codex_decision",
})

_wechat = WeChatProvider()
_codex_app = CodexAppProvider()


@dataclass
class ExecutionResult:
    speech_text: str
    result: str
    metadata: dict[str, str]


class ActionExecutor:
    def __init__(self, demo_mode: bool = True) -> None:
        self.demo_mode = demo_mode

    def execute(
        self,
        decision: Decision,
        card: ActionCard,
        followup_text: str | None = None,
    ) -> ExecutionResult:
        if card.action_type not in _ALLOWED_ACTION_TYPES:
            return ExecutionResult(
                speech_text=f"不允许的操作类型：{card.action_type}",
                result="denied",
                metadata={"action_type": card.action_type, "reason": "not_in_whitelist"},
            )

        if card.execution_mode == ExecutionMode.LIVE and not card.confirm_token:
            return ExecutionResult(
                speech_text=f"操作需要确认令牌：{card.title}",
                result="denied",
                metadata={"action_type": card.action_type, "reason": "missing_confirm_token"},
            )

        # codex_approval handles both approve and reject (reject may carry instruction)
        if card.action_type == "codex_approval":
            return self._codex_approval(decision, card, followup_text)

        if decision == Decision.REJECT:
            return ExecutionResult(
                speech_text=f"已取消：{card.title}",
                result="canceled",
                metadata={"action_type": card.action_type, "mode": card.execution_mode.value},
            )

        handler = {
            "send_message": self._send_message,
            "add_todo": self._add_todo,
            "send_pdf": self._send_pdf,
            "retry_crawler": self._retry_crawler,
            "book_ride": self._book_ride,
            "confirm_receipt": self._confirm_receipt,
        }.get(card.action_type, self._generic_execute)

        return handler(card)

    def _send_message(self, card: ActionCard) -> ExecutionResult:
        to = card.action_payload.get("to", "联系人")
        message = card.action_payload.get("message", "好的")
        channel = card.action_payload.get("channel", "wechat")

        # Actually send via WeChat if channel is wechat
        if channel == "wechat":
            send_result = _wechat.send_message(contact=to, message=message)
            if send_result == "SENT":
                return ExecutionResult(
                    speech_text=f"微信已发送给{to}：{message}。",
                    result="executed",
                    metadata={"channel": "wechat", "real_send": "true"},
                )
            else:
                return ExecutionResult(
                    speech_text=f"微信发送失败：{send_result}。消息内容：{message}。",
                    result="failed",
                    metadata={"channel": "wechat", "error": send_result},
                )

        return ExecutionResult(
            speech_text=f"已发送给{to}：{message}。",
            result="executed",
            metadata={"channel": str(channel)},
        )

    def _add_todo(self, card: ActionCard) -> ExecutionResult:
        title = card.action_payload.get("title", "待办事项")
        due = card.action_payload.get("due", "今天")
        return ExecutionResult(
            speech_text=f"已添加待办：{title}，时间 {due}。",
            result="executed",
            metadata={"todo_title": str(title)},
        )

    def _send_pdf(self, card: ActionCard) -> ExecutionResult:
        target = card.action_payload.get("target", "微信传输助手")
        return ExecutionResult(
            speech_text=f"已将当前版本 PDF 发送至 {target}。",
            result="executed",
            metadata={"artifact": "thesis_v32.pdf"},
        )

    def _retry_crawler(self, card: ActionCard) -> ExecutionResult:
        return ExecutionResult(
            speech_text="已同意重新尝试 Google Scholar 爬取任务。",
            result="executed",
            metadata={"task": "neurips-crawl", "retry": "true"},
        )

    def _book_ride(self, card: ActionCard) -> ExecutionResult:
        destination = card.action_payload.get("destination", "")
        return ExecutionResult(
            speech_text=f"滴滴已按默认设置叫车，目的地 {destination}，待你确认下单。",
            result="executed",
            metadata={"provider": "didi", "destination": str(destination)},
        )

    def _confirm_receipt(self, card: ActionCard) -> ExecutionResult:
        item = card.action_payload.get("item", "快递")
        provider = card.action_payload.get("provider", "快递")
        return ExecutionResult(
            speech_text=f"已确认签收{provider}{item}。",
            result="executed",
            metadata={"provider": str(provider), "item": str(item)},
        )

    def _codex_approval(
        self, decision: Decision, card: ActionCard, followup_text: str | None
    ) -> ExecutionResult:
        """Click Yes or No in the Codex.app approval dialog."""
        payload = card.action_payload or {}
        tidx_str = payload.get("title_elem_idx", "")
        thread_title = payload.get("thread_title", card.title)
        approval_type = payload.get("approval_type", "yes_no")

        try:
            tidx = int(tidx_str) if tidx_str else 0
        except ValueError:
            tidx = 0

        if tidx == 0:
            return ExecutionResult(
                speech_text=f"无法定位Codex线程，请手动处理：{thread_title}",
                result="failed",
                metadata={"reason": "missing_title_elem_idx"},
            )

        if decision == Decision.APPROVE:
            if approval_type == "multi_choice":
                opt_num = int(payload.get("option_1_num", "1"))
            else:
                opt_num = int(payload.get("yes_option_num", "1"))
            result_str = _codex_app.click_codex_option(tidx, opt_num)
            if result_str == "SUBMITTED":
                return ExecutionResult(
                    speech_text=f"已在Codex中确认：{thread_title}。",
                    result="executed",
                    metadata={"codex_click": result_str, "option": str(opt_num)},
                )
            return ExecutionResult(
                speech_text=f"Codex点击结果：{result_str}。请检查{thread_title}。",
                result="partial",
                metadata={"codex_click": result_str},
            )

        else:  # REJECT
            if approval_type == "multi_choice":
                opt_num = int(payload.get("option_2_num", "2"))
                result_str = _codex_app.click_codex_option(tidx, opt_num)
                return ExecutionResult(
                    speech_text=f"已在Codex中选择第{opt_num}项：{thread_title}。",
                    result="executed",
                    metadata={"codex_click": result_str, "option": str(opt_num)},
                )
            else:
                no_num = int(payload.get("no_option_num", "3"))
                # If followup_text provided and it's NOT a simple refusal → use as instruction
                refusal_words = {"不", "禁止", "不允许", "no", "nope", "拒绝"}
                is_simple_refusal = (
                    not followup_text
                    or followup_text.strip().lower() in refusal_words
                    or followup_text.strip() in refusal_words
                )
                if is_simple_refusal:
                    # Click No directly
                    result_str = _codex_app.click_codex_option(tidx, no_num)
                    return ExecutionResult(
                        speech_text=f"已在Codex中拒绝：{thread_title}。",
                        result="executed",
                        metadata={"codex_click": result_str, "option": str(no_num)},
                    )
                else:
                    # Click No and type instruction
                    result_str = _codex_app.click_codex_option(tidx, no_num, instruction=followup_text)
                    return ExecutionResult(
                        speech_text=f"已在Codex中拒绝并写入指令：{thread_title}。",
                        result="executed",
                        metadata={
                            "codex_click": result_str,
                            "option": str(no_num),
                            "instruction": followup_text or "",
                        },
                    )

    def _generic_execute(self, card: ActionCard) -> ExecutionResult:
        return ExecutionResult(
            speech_text=f"动作已执行：{card.title}",
            result="executed",
            metadata={"action_type": card.action_type},
        )
