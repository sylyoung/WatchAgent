"""Real macOS data providers — replaces mock data with actual Mac-local data.

Each provider gracefully degrades to empty/None if access fails.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess

log = logging.getLogger(__name__)


class ChromeProvider:
    """Read Chrome tab data via AppleScript: todo app, shopping logistics."""

    ALLOWED_URL_PATTERNS = [
        "localhost",
        "taobao.com",
        "jd.com",
        "trade.taobao.com",
        "order.jd.com",
    ]

    def _is_url_allowed(self, url_pattern: str) -> bool:
        """Check if the URL pattern matches the whitelist."""
        return any(allowed in url_pattern for allowed in self.ALLOWED_URL_PATTERNS)

    def _run_chrome_js(self, tab_index: int, window_index: int, js_code: str, delay: float = 0) -> str:
        """Execute JavaScript in a Chrome tab via AppleScript and return result."""
        if not isinstance(tab_index, int) or not isinstance(window_index, int):
            return ""
        if tab_index < 1 or window_index < 1 or tab_index > 200 or window_index > 50:
            return ""
        # Escape for AppleScript string embedding
        escaped_js = js_code.replace("\\", "\\\\").replace('"', '\\"')
        if delay > 0:
            script = f'''
tell application "Google Chrome"
    set t to tab {tab_index} of window {window_index}
    execute t javascript "{escaped_js}"
    delay {delay}
end tell'''
        else:
            script = f'''
tell application "Google Chrome"
    set t to tab {tab_index} of window {window_index}
    set r to execute t javascript "{escaped_js}"
    return r
end tell'''
        try:
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True, text=True, timeout=15,
            )
            return result.stdout.strip() if result.returncode == 0 else ""
        except Exception:
            return ""

    def _run_chrome_js_two_step(self, tab_index: int, window_index: int,
                                 js_step1: str, js_step2: str, delay: float = 2) -> str:
        """Run JS step1, wait, then run JS step2 and return its result."""
        escaped1 = js_step1.replace("\\", "\\\\").replace('"', '\\"')
        escaped2 = js_step2.replace("\\", "\\\\").replace('"', '\\"')
        script = f'''
tell application "Google Chrome"
    set t to tab {tab_index} of window {window_index}
    execute t javascript "{escaped1}"
    delay {delay}
    set r to execute t javascript "{escaped2}"
    return r
end tell'''
        try:
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True, text=True, timeout=20,
            )
            return result.stdout.strip() if result.returncode == 0 else ""
        except Exception:
            return ""

    def _find_tab(self, url_pattern: str) -> tuple[int, int] | None:
        """Find Chrome tab by URL pattern. Returns (tab_index, window_index) or None."""
        if not self._is_url_allowed(url_pattern):
            return None
        script = '''
tell application "Google Chrome"
    set winList to every window
    repeat with wi from 1 to count of winList
        set w to item wi of winList
        try
            set isMini to miniaturized of w
        on error
            set isMini to false
        end try
        if isMini is false then
            set tabList to every tab of w
            repeat with ti from 1 to count of tabList
                set u to URL of item ti of tabList
                if u contains "PATTERN" then
                    return (ti as string) & "," & (wi as string)
                end if
            end repeat
        end if
    end repeat
    return ""
end tell'''.replace("PATTERN", url_pattern)
        try:
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True, text=True, timeout=8,
            )
            out = result.stdout.strip()
            if out and "," in out:
                parts = out.split(",")
                return int(parts[0]), int(parts[1])
        except Exception:
            pass
        return None

    def get_open_tabs(self) -> list[dict]:
        """Return all open tabs in non-minimized windows: {title, url, window}."""
        script = '''
tell application "Google Chrome"
    set tabInfo to ""
    set winList to every window
    repeat with i from 1 to count of winList
        set w to item i of winList
        try
            set isMini to miniaturized of w
        on error
            set isMini to false
        end try
        if isMini is false then
            set tabList to every tab of w
            repeat with j from 1 to count of tabList
                set t to item j of tabList
                set tabInfo to tabInfo & (title of t) & "\\t" & (URL of t) & "\\t" & i & linefeed
            end repeat
        end if
    end repeat
    return tabInfo
end tell'''
        try:
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode != 0:
                return []
            tabs = []
            for line in result.stdout.strip().split("\n"):
                parts = line.split("\t")
                if len(parts) >= 3:
                    tabs.append({"title": parts[0], "url": parts[1], "window": int(parts[2])})
            return tabs
        except Exception:
            return []

    # ── Todo App (localhost) ─────────────────────────────────

    def fetch_today_todos(self) -> list[dict]:
        """Read today's tasks from the localhost todo app in Chrome.

        Clicks '按日' tab, then extracts today's items.
        Returns list of {title, priority, time}.
        """
        loc = self._find_tab("localhost")
        if not loc:
            return []
        ti, wi = loc

        # Step1: click 按日 button; Step2: read today section
        click_js = (
            'var bs=document.querySelectorAll("button");'
            'for(var i=0;i<bs.length;i++){if(bs[i].innerText.trim()==="按日"){bs[i].click();break;}}'
            '"clicked";'
        )
        read_js = (
            '(function(){'
            'var body=document.body.innerText;'
            'var d=new Date();'
            'var m=String(d.getMonth()+1).padStart(2,"0");'
            'var day=String(d.getDate()).padStart(2,"0");'
            'var hdr=m+"月"+day+"日";'
            'var lines=body.split("\\n").map(function(l){return l.trim()}).filter(function(l){return l});'
            'var inToday=false;var tasks=[];var cur=null;'
            'for(var i=0;i<lines.length;i++){'
            'var line=lines[i];'
            'if(line.indexOf(hdr)===0){inToday=true;continue;}'
            'if(inToday && /^\\d{2}月\\d{2}日/.test(line))break;'
            'if(inToday){'
            'if(line==="✎"||line==="×")continue;'
            'if(line==="高"||line==="中"||line==="低"){if(cur)cur.priority=line;continue;}'
            'if(/^\\d{1,2}:\\d{2}$/.test(line)){if(cur)cur.time=line;tasks.push(cur);cur=null;continue;}'
            'cur={title:line,priority:"",time:""};'
            '}}'
            'if(cur)tasks.push(cur);'
            'return JSON.stringify({date:hdr,tasks:tasks});'
            '})()'
        )
        raw = self._run_chrome_js_two_step(ti, wi, click_js, read_js, delay=1)
        if not raw:
            return []
        try:
            data = json.loads(raw)
            return data.get("tasks", [])
        except (json.JSONDecodeError, KeyError):
            return []

    def fetch_all_todos(self) -> list[dict]:
        """Read all tasks from the todo app list view.

        Clicks '列表' tab, then extracts all items.
        Returns list of {title, priority, date}.
        """
        loc = self._find_tab("localhost")
        if not loc:
            return []
        ti, wi = loc

        click_js = (
            'var bs=document.querySelectorAll("button");'
            'for(var i=0;i<bs.length;i++){if(bs[i].innerText.trim()==="列表"){bs[i].click();break;}}'
            '"clicked";'
        )
        read_js = (
            '(function(){'
            'var body=document.body.innerText;'
            'var lines=body.split("\\n").map(function(l){return l.trim()}).filter(function(l){return l});'
            'var tasks=[];var cur=null;'
            'for(var i=0;i<lines.length;i++){'
            'var line=lines[i];'
            'if(line==="✎"||line==="×"||line==="添加"||line==="列表"||line==="按日")continue;'
            'if(line==="待办事项"||line==="优先级"||line==="截止"||line==="全部"||line==="未完成"||line==="已完成")continue;'
            'if(line==="高"||line==="中"||line==="低"){if(cur)cur.priority=line;continue;}'
            'if(/^\\d{2}-\\d{2}-\\d{4}/.test(line)){if(cur)cur.date=line;tasks.push(cur);cur=null;continue;}'
            'if(/^\\d{2}-\\d{2}-\\d{4}\\s/.test(line)){if(cur)cur.date=line;tasks.push(cur);cur=null;continue;}'
            'if(/^\\d{1,2}:\\d{2}$/.test(line)){if(cur)cur.time=line;continue;}'
            'if(line.match(/^\\d+\\s*项/))continue;'
            'if(line.indexOf("清除")===0)continue;'
            'cur={title:line,priority:"",date:"",time:""};'
            '}}'
            'if(cur)tasks.push(cur);'
            'return JSON.stringify(tasks);'
            '})()'
        )
        raw = self._run_chrome_js_two_step(ti, wi, click_js, read_js, delay=1)
        if not raw:
            return []
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, KeyError):
            return []

    # ── Taobao Logistics ─────────────────────────────────────

    def fetch_taobao_logistics(self) -> list[dict]:
        """Navigate to Taobao '待收货' tab, refresh, and parse order text.

        Returns list of {item_name, status, logistics_summary}.
        """
        loc = self._find_tab("taobao.com")
        if not loc:
            return []
        ti, wi = loc

        # Click 待收货 tab and refresh
        nav_js = (
            "var tabs=document.querySelectorAll('a,li,span,div,button');"
            "for(var i=0;i<tabs.length;i++){"
            "var t=tabs[i].innerText.trim();"
            "if(t==='待收货'||t.match(/^待收货\\s*\\d/)){"
            "tabs[i].click();break;}}"
            "'clicked';"
        )
        self._run_chrome_js(ti, wi, nav_js)
        import time as _time
        _time.sleep(3)

        # Parse the page text to extract orders
        read_js = (
            "(function(){"
            "var text=document.body.innerText;"
            "var lines=text.split('\\n').map(function(l){return l.trim()}).filter(function(l){return l});"
            "var orders=[];var cur=null;"
            "for(var i=0;i<lines.length;i++){"
            "var l=lines[i];"
            # Order date header
            "if(/^\\d{4}-\\d{2}-\\d{2}$/.test(l)){"
            "if(cur&&cur.name)orders.push(cur);"
            "cur={date:l,name:'',logistics:'',price:''};continue;}"
            # Skip noise
            "if(!cur)continue;"
            "if(l.indexOf('订单号')>=0||l.indexOf('订单详情')>=0)continue;"
            "if(l.indexOf('卖家已发货')>=0)continue;"
            "if(l==='[交易快照]')continue;"
            "l=l.replace(' [交易快照]','').replace('[交易快照]','');"
            "if(l.indexOf('退货宝')>=0||l.indexOf('极速退款')>=0||l.indexOf('价保')>=0)continue;"
            "if(l.indexOf('退换加入')>=0||l.indexOf('加入购物车')>=0)continue;"
            "if(l==='查看物流'||l==='确认收货'||l==='延长收货'||l==='申请开票')continue;"
            "if(l.indexOf('再买一单')>=0||l.indexOf('手机订单')>=0)continue;"
            "if(l.indexOf('实付款')>=0||l.indexOf('含运费')>=0)continue;"
            "if(l.indexOf('还剩')>=0)continue;"
            "if(l.match(/^￥/)||l.match(/^x\\d/))continue;"
            # Skip shop names (end with 旗舰店/专营店/店/自营)
            "if(!cur.name&&(l.match(/店$/)&&l.length<25)){"
            "cur.shop=l;continue;}"
            # Logistics summary: starts with 已签收/待取件/派送中/etc
            "if(l.indexOf('已签收')>=0||l.indexOf('待取件')>=0||l.indexOf('派送中')>=0||l.indexOf('已暂存')>=0||l.indexOf('快件已')>=0){"
            "cur.logistics=l.substring(0,80);continue;}"
            # Product name: first non-skipped long text after date (skip short spec lines)
            "if(!cur.name&&l.length>6&&l.length<200&&!l.match(/^[\\d;]+$/)){"
            "cur.name=l.substring(0,60);continue;}"
            "}"
            "if(cur&&cur.name)orders.push(cur);"
            "return JSON.stringify(orders);"
            "})()"
        )
        raw = self._run_chrome_js(ti, wi, read_js)
        if not raw:
            return []
        try:
            orders = json.loads(raw)
            return [
                {
                    "item_name": o.get("name", "")[:40],
                    "source": "淘宝",
                    "logistics_summary": o.get("logistics", "在途"),
                    "date": o.get("date", ""),
                }
                for o in orders
            ]
        except (json.JSONDecodeError, KeyError):
            return []

    # ── JD Logistics ─────────────────────────────────────────

    def fetch_jd_logistics(self) -> list[dict]:
        """Navigate to JD '待收货/使用' tab, refresh, and parse order text.

        Returns list of {item_name, source, logistics_summary, date}.
        """
        loc = self._find_tab("jd.com")
        if not loc:
            return []
        ti, wi = loc

        # Click 待收货/使用 tab
        nav_js = (
            "var links=document.querySelectorAll('a,li,span');"
            "for(var i=0;i<links.length;i++){"
            "var t=links[i].innerText.trim();"
            "if(t.indexOf('待收货')>=0&&t.length<15){"
            "links[i].click();break;}}"
            "'clicked';"
        )
        self._run_chrome_js(ti, wi, nav_js)
        import time as _time
        _time.sleep(3)

        # Parse the page text
        read_js = (
            "(function(){"
            "var text=document.body.innerText;"
            "var lines=text.split('\\n').map(function(l){return l.trim()}).filter(function(l){return l});"
            "var orders=[];var cur=null;"
            "for(var i=0;i<lines.length;i++){"
            "var l=lines[i];"
            # Order date header
            "if(/^\\d{4}-\\d{2}-\\d{2}\\s/.test(l)){"
            "if(cur&&cur.name)orders.push(cur);"
            "cur={date:l.substring(0,10),name:'',status:'',shop:''};continue;}"
            "if(!cur)continue;"
            "if(l.indexOf('订单号')>=0||l.indexOf('拆分')>=0||l.indexOf('查看拆分')>=0)continue;"
            "if(l.indexOf('订单金额')>=0||l.indexOf('支付方式')>=0||l.indexOf('订单状态')>=0)continue;"
            "if(l.indexOf('订单详情')>=0||l.indexOf('确认收货')>=0||l.indexOf('取消订单')>=0)continue;"
            "if(l.indexOf('查看发票')>=0||l==='跟踪'||l===' 跟踪 ')continue;"
            "if(l.match(/^￥/)||l.match(/^¥/)||l.match(/^x\\d/))continue;"
            "if(l==='在线支付'||l==='在线预付')continue;"
            # Status
            "if(l==='等待收货'||l.indexOf('待收货')>=0){cur.status=l;continue;}"
            # Shop name
            "if(!cur.shop&&(l.indexOf('店')>=0||l.indexOf('京东')>=0)&&l.length<30){cur.shop=l;continue;}"
            # Product name
            "if(!cur.name&&l.length>5&&l.length<200){"
            "cur.name=l.substring(0,60);continue;}"
            "}"
            "if(cur&&cur.name)orders.push(cur);"
            "return JSON.stringify(orders);"
            "})()"
        )
        raw = self._run_chrome_js(ti, wi, read_js)
        if not raw:
            return []
        try:
            orders = json.loads(raw)
            return [
                {
                    "item_name": o.get("name", "")[:40],
                    "source": "京东",
                    "logistics_summary": o.get("status", "在途"),
                    "date": o.get("date", ""),
                }
                for o in orders
            ]
        except (json.JSONDecodeError, KeyError):
            return []

    def fetch_all_logistics(self) -> list[dict]:
        """Fetch logistics from both Taobao and JD."""
        results = []
        tb = self.fetch_taobao_logistics()
        for item in tb:
            item["source"] = "淘宝"
            results.append(item)
        jd = self.fetch_jd_logistics()
        for item in jd:
            item["source"] = "京东"
            results.append(item)
        return results


class WeChatProvider:
    """Read real WeChat conversation list via macOS Accessibility (System Events)."""

    _SCRIPT = '''\
tell application "System Events"
    if not (exists process "WeChat") then
        return "NOT_RUNNING"
    end if
    tell process "WeChat"
        try
            tell table 1 of scroll area 1 of splitter group 1 of window 1
                set rowCount to count of rows
                set maxRows to {limit}
                if rowCount < maxRows then set maxRows to rowCount
                set output to ""
                repeat with i from 1 to maxRows
                    try
                        set r to row i
                        set elems to every UI element of r
                        repeat with elem in elems
                            try
                                set d to description of elem as string
                                if d is not "" then
                                    set output to output & "ROW:" & i & ":" & d & linefeed
                                end if
                            end try
                        end repeat
                    end try
                end repeat
                return output
            end tell
        on error
            return "UI_ERROR"
        end try
    end tell
end tell
'''

    def is_running(self) -> bool:
        """Check if WeChat is running on this Mac."""
        try:
            result = subprocess.run(
                ["pgrep", "-x", "WeChat"],
                capture_output=True,
                timeout=3,
            )
            return result.returncode == 0
        except Exception:
            return False

    def read_conversation_list(self, limit: int = 12) -> list[dict]:
        """Read WeChat conversation list via AppleScript + Accessibility.

        Returns list of dicts with keys: contact, message, time, unread, extras.
        Each output line has format: "ROW:i:description" where i is the row number.
        Elements from the same row are grouped and parsed together so that
        separate badge elements (e.g. "1 unread message") are not lost.
        """
        script = self._SCRIPT.replace("{limit}", str(limit))
        try:
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode != 0:
                return []
            output = result.stdout.strip()
            if output in ("NOT_RUNNING", "UI_ERROR", ""):
                return []

            # Group element descriptions by row number
            from collections import defaultdict
            row_elements: dict[int, list[str]] = defaultdict(list)
            for line in output.split("\n"):
                line = line.strip()
                if not line.startswith("ROW:"):
                    continue
                rest = line[4:]  # e.g. "3:宝宝,消息,15:40,Sticky on Top"
                colon_idx = rest.find(":")
                if colon_idx < 0:
                    continue
                try:
                    row_idx = int(rest[:colon_idx])
                except ValueError:
                    continue
                desc = rest[colon_idx + 1:]
                row_elements[row_idx].append(desc)

            # Parse each row group
            conversations = []
            for row_idx in sorted(row_elements.keys()):
                descs = row_elements[row_idx]
                parsed = self._parse_row_group(descs)
                if parsed:
                    conversations.append(parsed)
            return conversations
        except Exception:
            return []

    def _parse_row_group(self, descriptions: list[str]) -> dict | None:
        """Parse all element descriptions from a single row into one conversation dict.

        A row may have multiple UI elements: a main description with
        contact,message,time fields plus separate badge elements like
        "1 unread message" or just "unread". This method merges them all.
        """
        contact = ""
        message = ""
        time_str = ""
        unread = 0
        extras: list[str] = []

        for desc in descriptions:
            # Check for standalone unread badge element
            desc_lower = desc.lower()
            if "unread message" in desc_lower or desc_lower.strip() == "unread":
                # Extract count from "N unread message(s)"
                for word in desc.split():
                    try:
                        unread = max(unread, int(word))
                        break
                    except ValueError:
                        continue
                # If count is still 0 but "unread" is present, it's a red-dot badge (count as 1)
                if unread == 0:
                    unread = 1
                # If this description has no comma, it's a standalone badge — skip to next element
                if "," not in desc:
                    continue

            # Standalone tag with no comma (e.g. "Mute Notifications", "Sticky on Top")
            if "," not in desc:
                tag = desc.strip()
                if tag:
                    extras.append(tag)
                continue

            # Try to parse as the main "contact,message,time,..." description
            parsed = self._parse_row_description(desc)
            if parsed and parsed["contact"]:
                if not contact:
                    contact = parsed["contact"]
                    message = parsed["message"]
                    time_str = parsed["time"]
                    extras = extras + parsed.get("extras", [])
                # Merge unread (take max)
                unread = max(unread, parsed["unread"])

        if not contact:
            return None
        return {
            "contact": contact,
            "message": message,
            "time": time_str,
            "unread": unread,
            "extras": extras,
        }

    @staticmethod
    def _parse_row_description(desc: str) -> dict | None:
        """Parse a WeChat row description string.

        Examples:
          'Alice,hi there,22:01,1 unread message(s),Sticky on Top'
          'File Transfer,[File] 专题31.pdf,13:36,Sticky on Top'
          'Bob,meeting tomorrow,22:08,2 unread message(s)'
          'Official Accounts,新华社: [Link] ...,21:49'
        """
        parts = desc.split(",")
        if len(parts) < 2:
            return None

        contact = parts[0].strip()
        # Find time field (HH:MM pattern) to separate message from metadata
        time_str = ""
        message_parts = []
        meta_parts = []
        unread = 0
        found_time = False

        for i, p in enumerate(parts[1:], 1):
            p = p.strip()
            if not found_time and _looks_like_time(p):
                time_str = p
                found_time = True
            elif not found_time:
                # Date string (e.g. "2026/03/19", "3/20") acts as the time separator for
                # non-today messages — mark found_time so metadata after it parses correctly,
                # but leave time_str empty so Bug-A filter rejects it as a non-today message.
                if re.fullmatch(r'\d{1,4}/\d{1,2}(/\d{1,4})?', p):
                    found_time = True
                else:
                    message_parts.append(p)
            else:
                # After time: check for unread count or other metadata
                if "unread message" in p:
                    try:
                        unread = int(p.split()[0])
                    except (ValueError, IndexError):
                        pass
                else:
                    meta_parts.append(p)

        message = ",".join(message_parts).strip() if message_parts else ""
        return {
            "contact": contact,
            "message": message,
            "time": time_str,
            "unread": unread,
            "extras": meta_parts,
        }

    _UNREAD_CHATS_SCRIPT = '''\
tell application "System Events"
    if not (exists process "WeChat") then
        return "NOT_RUNNING"
    end if
    tell process "WeChat"
        set finalOutput to ""

        -- Find unread rows in conversation list
        tell table 1 of scroll area 1 of splitter group 1 of window 1
            set rowCount to count of rows
            set maxScan to {max_scan}
            if rowCount < maxScan then set maxScan to rowCount
            set unreadRows to {}
            repeat with i from 1 to maxScan
                try
                    set r to row i
                    set elems to every UI element of r
                    repeat with elem in elems
                        try
                            set d to description of elem as string
                            if d contains "unread message" and d does not contain "Mute Notifications" then
                                set AppleScript's text item delimiters to ","
                                set parts to text items of d
                                set AppleScript's text item delimiters to ""
                                set contactName to item 1 of parts
                                set end of unreadRows to {i, contactName}
                            end if
                        end try
                    end repeat
                end try
            end repeat
        end tell

        -- Click into each unread conversation and read recent messages
        repeat with info in unreadRows
            set rowIdx to item 1 of info
            set cName to item 2 of info

            set selected of row rowIdx of table 1 of scroll area 1 of splitter group 1 of window 1 to true
            delay 0.6

            set finalOutput to finalOutput & "===" & cName & "===" & linefeed

            -- After selection, chat area may be in nested splitter group
            try
                tell scroll area 1 of splitter group 1 of splitter group 1 of window 1
                    tell table 1
                        set chatRows to count of rows
                        set startR to chatRows - {msg_count}
                        if startR < 1 then set startR to 1
                        repeat with j from startR to chatRows
                            try
                                set elems to every UI element of row j
                                repeat with elem in elems
                                    try
                                        set d to description of elem as string
                                        if d is not "" then
                                            set finalOutput to finalOutput & d & linefeed
                                        end if
                                    end try
                                end repeat
                            end try
                        end repeat
                    end tell
                end tell
            on error
                -- Fallback: maybe scroll area 2 structure
                try
                    tell table 1 of scroll area 2 of splitter group 1 of window 1
                        set chatRows to count of rows
                        set startR to chatRows - {msg_count}
                        if startR < 1 then set startR to 1
                        repeat with j from startR to chatRows
                            try
                                set elems to every UI element of row j
                                repeat with elem in elems
                                    try
                                        set d to description of elem as string
                                        if d is not "" then
                                            set finalOutput to finalOutput & d & linefeed
                                        end if
                                    end try
                                end repeat
                            end try
                        end repeat
                    end tell
                on error
                    set finalOutput to finalOutput & "(cannot read)" & linefeed
                end try
            end try
            set finalOutput to finalOutput & linefeed
        end repeat

        return finalOutput
    end tell
end tell
'''

    def read_unread_chats(self, max_scan: int = 15, msg_count: int = 5) -> list[dict]:
        """Click into each unread conversation and read recent messages.

        Returns list of {contact, messages: [str]}.
        NOTE: This physically clicks through WeChat conversations.
        """
        script = self._UNREAD_CHATS_SCRIPT.replace("{max_scan}", str(max_scan)).replace("{msg_count}", str(msg_count))
        try:
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                timeout=45,
            )
            if result.returncode != 0:
                return []
            output = result.stdout.strip()
            if output in ("NOT_RUNNING", ""):
                return []

            chats = []
            current_contact = None
            current_messages: list[str] = []

            for line in output.split("\n"):
                line = line.strip()
                if not line:
                    continue
                if line.startswith("===") and line.endswith("==="):
                    if current_contact is not None:
                        chats.append({"contact": current_contact, "messages": current_messages})
                    current_contact = line[3:-3]
                    current_messages = []
                elif current_contact is not None:
                    current_messages.append(line)

            if current_contact is not None:
                chats.append({"contact": current_contact, "messages": current_messages})

            return chats
        except Exception:
            return []

    def get_messages_summary(self) -> tuple[list[str], bool]:
        """Return (message_lines, is_running).

        message_lines: formatted "contact：message" strings from real WeChat UI.
        """
        running = self.is_running()
        try:
            conversations = self.read_conversation_list(12)
        except Exception:
            return [], running
        lines = []
        for c in conversations:
            contact = c["contact"]
            message = c["message"]
            unread = c["unread"]
            extras = c.get("extras", [])
            # Skip system/non-personal entries and muted conversations
            if contact in ("File Transfer", "Official Accounts"):
                continue
            if "Mute Notifications" in extras:
                continue
            # Skip old (non-today) messages: WeChat shows date instead of HH:MM
            if c.get("time") and not _looks_like_time(c["time"]):
                continue
            suffix = f"({unread}条未读)" if unread > 0 else ""
            if message:
                lines.append(f"{contact}：{message[:40]}{suffix}")
            else:
                lines.append(f"{contact}{suffix}")
        return lines, running

    _SEND_SCRIPT = '''\
tell application "WeChat"
    activate
end tell
delay 0.8

tell application "System Events"
    tell process "WeChat"
        -- Find the target conversation by scanning rows
        tell table 1 of scroll area 1 of splitter group 1 of window 1
            set rowCount to count of rows
            set maxScan to 20
            if rowCount < maxScan then set maxScan to rowCount
            set targetRow to 0
            repeat with i from 1 to maxScan
                try
                    set r to row i
                    set elems to every UI element of r
                    repeat with elem in elems
                        try
                            set d to description of elem as string
                            if d starts with "{contact}" then
                                set targetRow to i
                                exit repeat
                            end if
                        end try
                    end repeat
                    if targetRow > 0 then exit repeat
                end try
            end repeat
        end tell

        if targetRow is 0 then
            return "ERROR:CONTACT_NOT_FOUND"
        end if

        -- Select the conversation
        set selected of row targetRow of table 1 of scroll area 1 of splitter group 1 of window 1 to true
        delay 0.6

        -- Focus input area
        set inputArea to text area 1 of scroll area 2 of splitter group 1 of splitter group 1 of window 1
        click inputArea
        delay 0.3

        -- Clear and paste message
        keystroke "a" using command down
        delay 0.1
        key code 51
        delay 0.2
        set the clipboard to "{message}"
        delay 0.2
        keystroke "v" using command down
        delay 0.4

        -- Verify input
        set inputVal to value of inputArea
        if inputVal is not "{message}" then
            return "ERROR:INPUT_MISMATCH:" & inputVal
        end if
    end tell

    -- Press Enter at top level to send
    delay 0.2
    key code 36
    delay 1.0

    return "SENT"
end tell
'''

    def send_message(self, contact: str, message: str) -> str:
        """Send a message to a contact via WeChat UI automation.

        Returns "SENT" on success, or "ERROR:..." on failure.
        NOTE: This activates the WeChat window and physically types/sends.
        """
        if not contact or not message:
            return "ERROR:empty_input"
        if len(message) > 2000:
            return "ERROR:message_too_long"
        # Prevent AppleScript injection via contact name or message
        for forbidden in ['"', '\\', '\r', '\n']:
            contact = contact.replace(forbidden, '')
            message = message.replace(forbidden, ' ')

        # Escape quotes in contact and message for AppleScript
        safe_contact = contact.replace('"', '\\"').replace("'", "'")
        safe_message = message.replace('"', '\\"').replace("'", "'")
        script = self._SEND_SCRIPT.replace("{contact}", safe_contact).replace("{message}", safe_message)
        try:
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                timeout=20,
            )
            output = result.stdout.strip()
            if result.returncode != 0:
                return f"ERROR:OSASCRIPT:{result.stderr.strip()}"
            return output
        except Exception as e:
            return f"ERROR:EXCEPTION:{e}"

    def get_unread_details(self) -> tuple[list[dict], bool]:
        """Return (unread_chats, is_running).

        unread_chats: list of {contact, messages} with actual chat content.
        """
        running = self.is_running()
        if not running:
            return [], False
        chats = self.read_unread_chats(max_scan=15, msg_count=5)
        return chats, running


def _looks_like_time(s: str) -> bool:
    """Check if string looks like HH:MM time."""
    s = s.strip()
    if ":" not in s:
        return False
    parts = s.split(":")
    if len(parts) != 2:
        return False
    try:
        h, m = int(parts[0]), int(parts[1])
        return 0 <= h <= 23 and 0 <= m <= 59
    except ValueError:
        return False


class CodexAppProvider:
    """Read Codex.app (OpenAI Codex) thread statuses via macOS Accessibility API.

    Detects three states by analysing element structure in the sidebar:
      - running   : 2 AXGroups between Archive's AXImage and Pin button
      - awaiting  : same + extra AXImage + "Awaiting approval" static text
      - completed : 1 AXGroup between Archive's AXImage and Pin button
    """

    _SCRIPT = r'''
tell application "System Events"
    if not (exists process "Codex") then
        return "NOT_RUNNING"
    end if
    tell process "Codex"
        tell window 1
            set allElems to entire contents
            set totalElems to count of allElems
            set output to ""

            -- Use index-based iteration (repeat-with skips elements in Electron apps).
            -- Sidebar threads are always within the first ~400 elements.
            set scanLimit to totalElems
            if scanLimit > 400 then set scanLimit to 400
            repeat with i from 1 to scanLimit
                set e to item i of allElems
                try
                    set r to role of e as string
                    set d to description of e as string
                    set v to ""
                    try
                        set v to value of e as string
                    end try
                    if r is "AXImage" then
                        set output to output & i & "|IMG||" & linefeed
                    else if r is "AXGroup" then
                        set output to output & i & "|GRP||" & linefeed
                    else if r is "AXButton" and d is "Archive thread" then
                        set output to output & i & "|ARCHIVE||" & linefeed
                    else if r is "AXButton" and d is "Pin thread" then
                        set output to output & i & "|PIN||" & linefeed
                    else if r is "AXStaticText" and v is not "" then
                        set output to output & i & "|TXT||" & v & linefeed
                    end if
                end try
            end repeat
            return output
        end tell
    end tell
end tell
'''

    # Script to click a thread and read its content area.
    # TITLE_IDX is replaced with the actual element index before calling osascript.
    _READ_THREAD_SCRIPT = r'''
tell application "System Events"
    if not (exists process "Codex") then
        return "NOT_RUNNING"
    end if
    tell process "Codex"
        tell window 1
            set allElems to entire contents
            set totalElems to count of allElems
            if TITLE_IDX <= totalElems then
                try
                    click (item TITLE_IDX of allElems)
                end try
            end if
            delay 0.8
            -- Re-read; content area elements appear after ~300
            set allElems to entire contents
            set totalElems to count of allElems
            set output to ""
            set startScan to 300
            if startScan > totalElems then set startScan to 1
            repeat with i from startScan to totalElems
                set e to item i of allElems
                try
                    set r to role of e as string
                    if r is "AXStaticText" then
                        set v to ""
                        try
                            set v to value of e as string
                        end try
                        if v is not "" then
                            set output to output & v & linefeed
                            if (length of output) > 3000 then
                                exit repeat
                            end if
                        end if
                    end if
                end try
            end repeat
            return output
        end tell
    end tell
end tell
'''

    # Script to click a numbered option and Submit in the Codex approval UI.
    # TITLE_IDX and OPTION_PREFIX are replaced before calling.
    _CLICK_OPTION_SCRIPT = r'''
tell application "System Events"
    if not (exists process "Codex") then
        return "NOT_RUNNING"
    end if
    tell process "Codex"
        tell window 1
            -- Click thread title to open it
            set allElems to entire contents
            set totalElems to count of allElems
            if TITLE_IDX <= totalElems then
                try
                    click (item TITLE_IDX of allElems)
                end try
            end if
            delay 0.8
            -- Re-read elements
            set allElems to entire contents
            set totalElems to count of allElems
            set optClicked to false
            set submitted to false
            repeat with i from 300 to totalElems
                set e to item i of allElems
                try
                    set r to role of e as string
                    set v to ""
                    try
                        set v to value of e as string
                    end try
                    -- Click option matching OPTION_PREFIX
                    if (not optClicked) and v starts with "OPTION_PREFIX" then
                        try
                            click e
                            set optClicked to true
                            delay 0.4
                        end try
                    end if
                    -- After clicking option, click Submit
                    if optClicked and (not submitted) and r is "AXButton" and v is "Submit" then
                        try
                            click e
                            set submitted to true
                        end try
                        exit repeat
                    end if
                end try
            end repeat
            if submitted then
                return "SUBMITTED"
            else if optClicked then
                return "CLICKED_NO_SUBMIT"
            else
                return "NOT_FOUND"
            end if
        end tell
    end tell
end tell
'''

    # Script to click option 3 (No + instruction), type text, then Submit.
    _CLICK_NO_WITH_INSTRUCTION_SCRIPT = r'''
tell application "System Events"
    if not (exists process "Codex") then
        return "NOT_RUNNING"
    end if
    tell process "Codex"
        tell window 1
            set allElems to entire contents
            set totalElems to count of allElems
            if TITLE_IDX <= totalElems then
                try
                    click (item TITLE_IDX of allElems)
                end try
            end if
            delay 0.8
            set allElems to entire contents
            set totalElems to count of allElems
            set optClicked to false
            set submitted to false
            repeat with i from 300 to totalElems
                set e to item i of allElems
                try
                    set r to role of e as string
                    set v to ""
                    try
                        set v to value of e as string
                    end try
                    if (not optClicked) and v starts with "NO_PREFIX" then
                        try
                            click e
                            set optClicked to true
                            delay 0.5
                            -- Type instruction into the text field that appears
                            set the clipboard to "INSTRUCTION_TEXT"
                            delay 0.2
                            keystroke "v" using command down
                            delay 0.3
                        end try
                    end if
                    if optClicked and (not submitted) and r is "AXButton" and v is "Submit" then
                        try
                            click e
                            set submitted to true
                        end try
                        exit repeat
                    end if
                end try
            end repeat
            if submitted then
                return "SUBMITTED"
            else if optClicked then
                return "CLICKED_NO_SUBMIT"
            else
                return "NOT_FOUND"
            end if
        end tell
    end tell
end tell
'''

    _running_name: str = "Codex"

    def is_running(self) -> bool:
        candidates = os.environ.get("CODEX_APP_NAME", "Codex,Claude,Codex Agent").split(",")
        for name in candidates:
            name = name.strip()
            try:
                r = subprocess.run(["pgrep", "-x", name], capture_output=True, timeout=3)
                if r.returncode == 0:
                    self._running_name = name
                    return True
            except Exception:
                pass
        return False

    def read_threads(self) -> list[dict]:
        """Return list of dicts: {project, title, title_elem_idx, status, time}.

        status: 'running' | 'awaiting' | 'completed' | 'old'
        """
        if not self.is_running():
            return []
        script = self._SCRIPT.replace('"Codex"', f'"{self._running_name}"')
        try:
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True, text=True, timeout=60,
            )
            if result.returncode != 0 or result.stdout.strip() in ("NOT_RUNNING", ""):
                if result.stderr.strip():
                    log.warning("CodexAppProvider osascript stderr: %s", result.stderr.strip())
                return []
            return self._parse_elements(result.stdout)
        except subprocess.TimeoutExpired:
            log.warning("CodexAppProvider osascript timed out (>60s) — Codex UI may be too large")
            return []
        except Exception:
            log.warning("CodexAppProvider read_threads failed", exc_info=True)
            return []

    def read_thread_content(self, title_elem_idx: int) -> list[str]:
        """Click on a thread and read its chat content (for awaiting/running threads).

        Returns list of non-empty text lines from the content area.
        """
        script = self._READ_THREAD_SCRIPT.replace("TITLE_IDX", str(title_elem_idx))
        try:
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True, text=True, timeout=15,
            )
            if result.returncode != 0 or result.stdout.strip() in ("NOT_RUNNING", ""):
                return []
            return [ln.strip() for ln in result.stdout.strip().split("\n") if ln.strip()]
        except Exception:
            return []

    def click_codex_option(self, title_elem_idx: int, option_number: int, instruction: str | None = None) -> str:
        """Click a numbered option (and optionally type instruction) in Codex approval UI.

        Returns 'SUBMITTED', 'CLICKED_NO_SUBMIT', or 'NOT_FOUND'.
        """
        option_prefix = f"{option_number}."
        if instruction:
            # Use the "No + instruction" script
            no_prefix = option_prefix
            safe_instr = instruction.replace('"', '\\"').replace("'", "\\'")
            script = (
                self._CLICK_NO_WITH_INSTRUCTION_SCRIPT
                .replace("TITLE_IDX", str(title_elem_idx))
                .replace("NO_PREFIX", no_prefix)
                .replace("INSTRUCTION_TEXT", safe_instr)
            )
        else:
            script = (
                self._CLICK_OPTION_SCRIPT
                .replace("TITLE_IDX", str(title_elem_idx))
                .replace("OPTION_PREFIX", option_prefix)
            )
        try:
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True, text=True, timeout=15,
            )
            return result.stdout.strip() or "NOT_FOUND"
        except Exception:
            return "ERROR"

    @staticmethod
    def parse_approval_content(lines: list[str]) -> dict:
        """Parse chat content lines into structured approval data.

        Returns {
            "question": str,
            "options": [{"number": int, "text": str, "short": str}],
            "type": "yes_no" | "multi_choice" | "unknown",
        }
        """
        import re

        option_re = re.compile(r"^(\d+)\.\s+(.+)$")
        question = ""
        options: list[dict] = []

        # Skip known UI labels
        skip_labels = {"Settings", "New Thread", "Chat", "Archive", "Pin", "Search"}

        for line in lines:
            line = line.strip()
            if not line or line in skip_labels or len(line) < 3:
                continue
            m = option_re.match(line)
            if m:
                num = int(m.group(1))
                text = m.group(2).strip()
                # Generate short label (≤4 chars) for Watch button
                text_lower = text.lower()
                if text_lower.startswith("yes") and ("don't ask" in text_lower or "dont ask" in text_lower):
                    short = "不再问"
                elif text_lower.startswith("yes"):
                    short = "Yes"
                elif text_lower.startswith("no"):
                    short = "No"
                else:
                    short = text[:4]
                options.append({"number": num, "text": text, "short": short})
            elif not options and len(line) > 8:
                # Before numbered options: candidate for question text
                question = line  # Keep updating; last long line before options = question

        # Classify
        has_yes = any(o["text"].lower().startswith("yes") for o in options)
        has_no = any("no" in o["text"][:10].lower() for o in options)

        if has_yes and has_no:
            type_ = "yes_no"
        elif len(options) >= 2:
            type_ = "multi_choice"
        else:
            type_ = "unknown"

        return {
            "question": question[:120],
            "options": options,
            "type": type_,
        }

    def _parse_elements(self, raw: str) -> list[dict]:
        """Parse the flat element list into thread dicts with project names."""
        import re

        lines = [ln for ln in raw.strip().split("\n") if ln.strip()]
        elements = []
        for line in lines:
            parts = line.split("|", 3)
            if len(parts) < 3:
                continue
            idx = int(parts[0]) if parts[0].isdigit() else 0
            role = parts[1]
            value = parts[3] if len(parts) > 3 else ""
            elements.append({"idx": idx, "role": role, "value": value})

        def _is_time_str(s: str) -> bool:
            return bool(re.match(r"^\d+[mhdw]$", s.strip())) or s.strip().lower() == "now"

        archive_positions = [i for i, e in enumerate(elements) if e["role"] == "ARCHIVE"]

        # Track project name per archive: project name = first qualifying TXT
        # in the inter-archive zone (after prev thread's last TXT, before this ARCHIVE).
        # Qualifying = not a time string, not "Awaiting approval", not in known skip set.
        _skip = {"Awaiting approval", "Settings", "New Thread"}

        def _find_project(search_start: int, search_end: int) -> str:
            for j in range(search_start, search_end):
                e = elements[j]
                if e["role"] != "TXT" or not e["value"]:
                    continue
                v = e["value"]
                if _is_time_str(v) or v in _skip or "awaiting" in v.lower():
                    continue
                return v
            return ""

        threads = []
        current_project = ""
        prev_search_start = 0

        for ai in archive_positions:
            # Check for project name in zone before this archive
            new_proj = _find_project(prev_search_start, ai)
            if new_proj:
                current_project = new_proj

            # Find the first IMG after Archive (status icon)
            img1_pos = None
            for j in range(ai + 1, min(ai + 4, len(elements))):
                if elements[j]["role"] == "IMG":
                    img1_pos = j
                    break
            if img1_pos is None:
                continue

            # Find Pin button after img1
            pin_pos = None
            for j in range(img1_pos + 1, min(img1_pos + 6, len(elements))):
                if elements[j]["role"] == "PIN":
                    pin_pos = j
                    break
            if pin_pos is None:
                continue

            # Count elements between img1 and pin
            between = elements[img1_pos + 1 : pin_pos]
            grp_count = sum(1 for e in between if e["role"] == "GRP")
            extra_img = any(e["role"] == "IMG" for e in between)

            # Find title and metadata after Pin.
            # Thread texts: title (first TXT), optionally "Awaiting approval", and time string.
            # Any other TXT is a section/project header → stop scanning.
            texts_after_pin: list[str] = []
            title_elem_idx: int | None = None
            last_txt_list_pos = pin_pos  # position in `elements` list

            for j in range(pin_pos + 1, min(pin_pos + 7, len(elements))):
                if elements[j]["role"] == "ARCHIVE":
                    break
                if elements[j]["role"] == "TXT" and elements[j]["value"]:
                    v = elements[j]["value"]
                    if title_elem_idx is None:
                        # First TXT = thread title
                        title_elem_idx = elements[j]["idx"]
                        texts_after_pin.append(v)
                        last_txt_list_pos = j
                    else:
                        # Subsequent TXTs must be "Awaiting approval" or a time string
                        if "Awaiting approval" in v or _is_time_str(v):
                            texts_after_pin.append(v)
                            last_txt_list_pos = j
                        else:
                            # Looks like a project header — stop here (don't consume it)
                            break

            if not texts_after_pin:
                # Advance search start past this archive's block anyway
                prev_search_start = pin_pos + 1
                continue

            title = texts_after_pin[0]
            has_awaiting = any("Awaiting approval" in t for t in texts_after_pin)

            # Time is the last short token (e.g. "2h", "1w", "6d")
            time_str = ""
            for t in reversed(texts_after_pin):
                if _is_time_str(t):
                    time_str = t
                    break

            # Determine status
            if extra_img and has_awaiting:
                status = "awaiting"
            elif extra_img and not has_awaiting:
                status = "running"
            elif grp_count >= 2:
                status = "completed"
            else:
                status = "old"

            threads.append({
                "project": current_project,
                "title": title,
                "title_elem_idx": title_elem_idx,
                "status": status,
                "time": time_str,
                "awaiting_approval": has_awaiting,
            })

            # Next inter-archive search starts after this thread's last text
            prev_search_start = last_txt_list_pos + 1

        return threads

    def get_active_summary(self) -> list[dict]:
        """Return running, awaiting, and completed (blue-dot) threads — the 3 states to surface."""
        all_threads = self.read_threads()
        return [t for t in all_threads if t["status"] in ("running", "awaiting", "completed")]


class CodexProvider:
    """Read real development state from git repos and running processes."""

    def __init__(self, repo_path: str | None = None) -> None:
        self.repo_path = repo_path or os.getcwd()

    def git_status(self) -> dict | None:
        """Return git working tree status for the repo."""
        try:
            result = subprocess.run(
                ["git", "status", "--porcelain"],
                capture_output=True,
                text=True,
                timeout=5,
                cwd=self.repo_path,
            )
            if result.returncode != 0:
                return None
            lines = [line for line in result.stdout.strip().split("\n") if line.strip()]
            modified = len([line for line in lines if line[0:2].strip() in ("M", "MM")])
            added = len([line for line in lines if line.startswith("??")])
            return {
                "repo": os.path.basename(self.repo_path),
                "modified_files": modified,
                "new_files": added,
                "total_changes": len(lines),
            }
        except Exception:
            return None

    def recent_commits(self, limit: int = 5) -> list[dict]:
        """Return recent git commits."""
        try:
            result = subprocess.run(
                ["git", "log", f"-{limit}", "--format=%h|%s|%ar"],
                capture_output=True,
                text=True,
                timeout=5,
                cwd=self.repo_path,
            )
            if result.returncode != 0:
                return []
            commits = []
            for line in result.stdout.strip().split("\n"):
                if not line:
                    continue
                parts = line.split("|", 2)
                if len(parts) == 3:
                    commits.append({"hash": parts[0], "message": parts[1], "time": parts[2]})
            return commits
        except Exception:
            return []

    def running_dev_processes(self) -> list[str]:
        """Find running development-related processes."""
        try:
            result = subprocess.run(
                ["ps", "-eo", "comm"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            keywords = {"python", "node", "npm", "claude", "codex", "uvicorn", "cloudflared"}
            seen = set()
            procs = []
            for line in result.stdout.split("\n"):
                name = os.path.basename(line.strip())
                lower = name.lower()
                if any(k in lower for k in keywords) and lower not in seen:
                    seen.add(lower)
                    procs.append(name)
            return procs[:8]
        except Exception:
            return []

    def get_work_summary(self) -> dict:
        """Return a combined work state summary."""
        status = self.git_status()
        commits = self.recent_commits(3)
        procs = self.running_dev_processes()
        return {
            "git_status": status,
            "recent_commits": commits,
            "running_processes": procs,
        }
