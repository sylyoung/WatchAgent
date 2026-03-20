"""Tool registry: JSON schemas + Python handlers for all agent tools."""

from __future__ import annotations

import logging
import urllib.request
import json as _json
from typing import Callable
from watchagent_backend.mac_data_providers import _looks_like_time

log = logging.getLogger(__name__)

# ── Tool schemas ──────────────────────────────────────────────────────────────

TOOL_SCHEMAS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "获取当前天气情况（温度、天气状况、体感温度、湿度）",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_wechat_messages",
            "description": "获取微信消息摘要（未读数量、会话列表）",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_todos",
            "description": "获取今日待办事项列表（来自 Chrome todo 应用）",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_codex_status",
            "description": "获取 Codex.app 任务状态（进行中/待审批/已完成的线程列表）",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_dev_status",
            "description": "获取开发状态（Git 变更、最近提交、后台进程）",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_taobao_logistics",
            "description": "获取淘宝待收货物流信息",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_jd_logistics",
            "description": "获取京东待收货物流信息",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_exercise_data",
            "description": "获取今日运动数据（步数、卡路里）",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_heart_data",
            "description": "获取心率和血氧数据",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_sleep_data",
            "description": "获取昨晚睡眠数据（总时长、深睡、REM）",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_medication_reminder",
            "description": "获取当前时段的用药提醒",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_action_card",
            "description": "创建需要用户确认的操作卡片（如发消息、审批 Codex、叫车等）",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "卡片标题"},
                    "detail": {"type": "string", "description": "操作详情"},
                    "action_type": {
                        "type": "string",
                        "enum": [
                            "send_message",
                            "book_ride",
                            "codex_approval",
                            "codex_decision",
                            "confirm_receipt",
                        ],
                        "description": "操作类型",
                    },
                    "action_payload": {
                        "type": "object",
                        "description": "操作所需参数（action_type 相关字段）",
                    },
                },
                "required": ["title", "detail", "action_type", "action_payload"],
            },
        },
    },
]

_SCHEMA_BY_NAME: dict[str, dict] = {s["function"]["name"]: s for s in TOOL_SCHEMAS}


def get_schemas_for(tool_names: list[str]) -> list[dict]:
    """Return tool schemas filtered by whitelist from SKILL.md."""
    return [_SCHEMA_BY_NAME[n] for n in tool_names if n in _SCHEMA_BY_NAME]


# ── Handler factory ───────────────────────────────────────────────────────────
# Each handler receives (request, providers) and returns a JSON-serialisable dict.
# providers = {"chrome": ChromeProvider, "wechat": WeChatProvider,
#              "codex": CodexProvider, "codex_app": CodexAppProvider}


def build_handlers(request, providers: dict) -> dict[str, Callable[[], dict]]:
    """Return a map of tool_name → zero-arg callable that executes the tool."""

    chrome = providers.get("chrome")
    wechat = providers.get("wechat")
    codex = providers.get("codex")
    codex_app = providers.get("codex_app")

    def _get_weather() -> dict:
        ws = None
        dc = request.device_context
        if dc and dc.weather_snapshot:
            ws = dc.weather_snapshot
        if ws and ws.temp_c is not None:
            return {
                "source": "watch",
                "temp_c": ws.temp_c,
                "condition": ws.condition_description or "",
                "feels_like_c": ws.feels_like_c,
                "today_min_c": ws.today_min_c,
                "today_max_c": ws.today_max_c,
                "humidity": ws.humidity,
                "location": ws.location_name or "当前位置",
            }
        lat = dc.latitude if dc else None
        lon = dc.longitude if dc else None
        if lat is not None and lon is not None:
            try:
                url = (
                    f"https://api.open-meteo.com/v1/forecast"
                    f"?latitude={lat}&longitude={lon}"
                    f"&current=temperature_2m,apparent_temperature,relative_humidity_2m,weather_code"
                    f"&daily=temperature_2m_max,temperature_2m_min"
                    f"&timezone=auto&forecast_days=1"
                )
                with urllib.request.urlopen(url, timeout=8) as resp:
                    data = _json.loads(resp.read())
                c = data["current"]
                d = data["daily"]
                return {
                    "source": "open_meteo",
                    "temp_c": round(c["temperature_2m"], 1),
                    "feels_like_c": round(c["apparent_temperature"], 1),
                    "humidity": int(c["relative_humidity_2m"]),
                    "today_min_c": round(d["temperature_2m_min"][0], 1),
                    "today_max_c": round(d["temperature_2m_max"][0], 1),
                }
            except Exception:
                log.warning("Open-Meteo fetch failed", exc_info=True)
        return {"source": "unavailable"}

    def _get_wechat_messages() -> dict:
        running = wechat.is_running()
        if not running:
            return {"messages": [], "count": 0, "wechat_running": False}
        _SKIP = {"File Transfer", "Official Accounts"}
        try:
            conversations = wechat.read_conversation_list(12)
        except Exception:
            return {"messages": [], "count": 0, "wechat_running": running}
        unread_messages = []
        for c in conversations:
            if c["contact"] in _SKIP:
                continue
            if "Mute Notifications" in c.get("extras", []):
                continue
            if c["unread"] > 0:
                msg = c.get("message", "")
                unread_messages.append(f"{c['contact']}：{msg[:10]}")
        return {
            "messages": unread_messages,
            "count": len(unread_messages),
            "wechat_running": running,
        }

    def _get_todos() -> dict:
        todos = chrome.fetch_today_todos()
        return {"todos": todos, "count": len(todos)}

    def _get_codex_status() -> dict:
        try:
            threads = codex_app.read_threads()
        except Exception:
            log.warning("CodexAppProvider failed", exc_info=True)
            return {"running": [], "awaiting": [], "completed": [], "error": "codex_unavailable"}
        running = [t for t in threads if t["status"] == "running"]
        awaiting = [t for t in threads if t["status"] == "awaiting"]
        completed = [t for t in threads if t["status"] == "completed"]
        return {
            "running": running,
            "awaiting": awaiting,
            "completed": completed,
        }

    def _get_dev_status() -> dict:
        work = codex.get_work_summary()
        return {
            "git_status": work.get("git_status"),
            "recent_commits": work.get("recent_commits", []),
            "running_processes": work.get("running_processes", []),
        }

    def _get_taobao_logistics() -> dict:
        items = chrome.fetch_taobao_logistics()
        return {"items": items, "count": len(items)}

    def _get_jd_logistics() -> dict:
        items = chrome.fetch_jd_logistics()
        return {"items": items, "count": len(items)}

    def _get_exercise_data() -> dict:
        hs = {}
        if request.device_context and request.device_context.health_snapshot:
            hs = request.device_context.health_snapshot.model_dump()
        todos = chrome.fetch_today_todos()
        high_pri = [t for t in todos if t.get("priority") == "高"]
        return {
            "steps": hs.get("steps") or 0,
            "active_calories": hs.get("active_calories") or 0,
            "schedule_items": len(todos),
            "high_priority_items": len(high_pri),
        }

    def _get_heart_data() -> dict:
        hs = {}
        if request.device_context and request.device_context.health_snapshot:
            hs = request.device_context.health_snapshot.model_dump()
        return {
            "heart_rate": hs.get("heart_rate"),
            "resting_heart_rate": hs.get("resting_heart_rate"),
            "blood_oxygen": hs.get("blood_oxygen"),
        }

    def _get_sleep_data() -> dict:
        hs = {}
        if request.device_context and request.device_context.health_snapshot:
            hs = request.device_context.health_snapshot.model_dump()
        return {
            "sleep_hours": hs.get("sleep_hours"),
            "sleep_deep_minutes": hs.get("sleep_deep_minutes"),
            "sleep_rem_minutes": hs.get("sleep_rem_minutes"),
        }

    def _get_medication_reminder() -> dict:
        hour = request.timestamp.astimezone().hour
        if hour < 12:
            period = "morning"
            reminder = "早餐后记得服用日常保健品"
        elif hour < 18:
            period = "afternoon"
            reminder = "午餐后记得补充维生素"
        else:
            period = "evening"
            reminder = "晚间保健提醒：注意休息"
        return {"hour": hour, "period": period, "reminder": reminder}

    def _create_action_card(**kwargs) -> dict:
        # Handler just returns the card spec; AgentRunner creates the actual ActionCard
        return {"card_spec": kwargs}

    return {
        "get_weather": _get_weather,
        "get_wechat_messages": _get_wechat_messages,
        "get_todos": _get_todos,
        "get_codex_status": _get_codex_status,
        "get_dev_status": _get_dev_status,
        "get_taobao_logistics": _get_taobao_logistics,
        "get_jd_logistics": _get_jd_logistics,
        "get_exercise_data": _get_exercise_data,
        "get_heart_data": _get_heart_data,
        "get_sleep_data": _get_sleep_data,
        "get_medication_reminder": _get_medication_reminder,
        "create_action_card": _create_action_card,
    }
