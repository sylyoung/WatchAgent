"""SQLite trace database — records the full data pipeline for each watch interaction.

WAL mode enables concurrent writes from ThreadPoolExecutor tool threads.
All methods are fire-and-forget: DB failures are logged but never raised.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Generator

log = logging.getLogger(__name__)

_DDL = """\
CREATE TABLE IF NOT EXISTS watch_requests (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id          TEXT NOT NULL,
    session_id          TEXT NOT NULL,
    trace_id            TEXT,
    ts                  TEXT NOT NULL,
    request_type        TEXT NOT NULL,
    utterance           TEXT,
    skill_hint          TEXT,
    resolved_skill      TEXT,
    entry_mode          TEXT,
    input_mode          TEXT,
    device_ctx_json     TEXT,
    response_speech     TEXT,
    response_cards_json TEXT,
    duration_ms         INTEGER
);

CREATE TABLE IF NOT EXISTS skill_runs (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id            TEXT NOT NULL UNIQUE,
    session_id        TEXT NOT NULL,
    trace_id          TEXT,
    skill_name        TEXT NOT NULL,
    state             TEXT,
    started_at        TEXT NOT NULL,
    finished_at       TEXT,
    first_response_ms INTEGER,
    merged_lines_json TEXT,
    error_msg         TEXT
);

CREATE TABLE IF NOT EXISTS llm_exchanges (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          TEXT NOT NULL,
    session_id      TEXT NOT NULL,
    round_num       INTEGER,
    ts              TEXT NOT NULL,
    messages_json   TEXT,
    response_json   TEXT,
    tool_calls_json TEXT,
    finish_reason   TEXT,
    duration_ms     INTEGER,
    error_msg       TEXT
);

CREATE TABLE IF NOT EXISTS tool_calls (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id      TEXT NOT NULL,
    session_id  TEXT NOT NULL,
    round_num   INTEGER,
    call_index  INTEGER,
    ts          TEXT NOT NULL,
    tool_name   TEXT NOT NULL,
    input_json  TEXT,
    output_json TEXT,
    success     INTEGER,
    error_msg   TEXT,
    duration_ms INTEGER
);

CREATE TABLE IF NOT EXISTS confirmations (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id          TEXT NOT NULL,
    confirm_token       TEXT NOT NULL,
    action_type         TEXT,
    action_payload_json TEXT,
    decision            TEXT,
    followup_text       TEXT,
    ts                  TEXT NOT NULL,
    exec_success        INTEGER,
    exec_result_json    TEXT
);
"""


def _now() -> str:
    return datetime.now(UTC).isoformat()


class TraceDB:
    """Thread-safe SQLite trace store (WAL mode)."""

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = str(db_path)
        self._init_schema()

    def _init_schema(self) -> None:
        try:
            with self._conn() as conn:
                conn.executescript(_DDL)
        except Exception:
            log.warning("TraceDB: schema init failed at %s", self._db_path, exc_info=True)

    @contextmanager
    def _conn(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(self._db_path, timeout=5, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ── watch_requests ────────────────────────────────────────────────────────

    def record_request_in(
        self,
        *,
        request_id: str,
        session_id: str,
        trace_id: str | None,
        request_type: str,
        utterance: str | None,
        skill_hint: str | None,
        entry_mode: str | None,
        input_mode: str | None,
        device_ctx_json: str | None,
    ) -> None:
        try:
            with self._conn() as conn:
                conn.execute(
                    """INSERT INTO watch_requests
                       (request_id, session_id, trace_id, ts, request_type,
                        utterance, skill_hint, entry_mode, input_mode, device_ctx_json)
                       VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (
                        request_id, session_id, trace_id, _now(), request_type,
                        utterance, skill_hint, entry_mode, input_mode, device_ctx_json,
                    ),
                )
        except Exception:
            log.warning("TraceDB.record_request_in failed", exc_info=True)

    def record_request_out(
        self,
        *,
        request_id: str,
        resolved_skill: str | None,
        response_speech: str | None,
        response_cards_json: str | None,
        duration_ms: int,
    ) -> None:
        try:
            with self._conn() as conn:
                conn.execute(
                    """UPDATE watch_requests
                       SET resolved_skill=?, response_speech=?, response_cards_json=?, duration_ms=?
                       WHERE request_id=?""",
                    (resolved_skill, response_speech, response_cards_json, duration_ms, request_id),
                )
        except Exception:
            log.warning("TraceDB.record_request_out failed", exc_info=True)

    # ── skill_runs ─────────────────────────────────────────────────────────────

    def record_skill_run_start(
        self,
        *,
        run_id: str,
        session_id: str,
        trace_id: str | None,
        skill_name: str,
    ) -> None:
        try:
            with self._conn() as conn:
                conn.execute(
                    """INSERT OR IGNORE INTO skill_runs
                       (run_id, session_id, trace_id, skill_name, state, started_at)
                       VALUES (?,?,?,?,?,?)""",
                    (run_id, session_id, trace_id, skill_name, "running", _now()),
                )
        except Exception:
            log.warning("TraceDB.record_skill_run_start failed", exc_info=True)

    def record_skill_run_end(
        self,
        *,
        run_id: str,
        state: str,
        merged_lines: list[str] | None = None,
        error_msg: str | None = None,
    ) -> None:
        try:
            with self._conn() as conn:
                conn.execute(
                    """UPDATE skill_runs
                       SET state=?, finished_at=?, merged_lines_json=?, error_msg=?
                       WHERE run_id=?""",
                    (
                        state,
                        _now(),
                        json.dumps(merged_lines or [], ensure_ascii=False),
                        error_msg,
                        run_id,
                    ),
                )
        except Exception:
            log.warning("TraceDB.record_skill_run_end failed", exc_info=True)

    # ── llm_exchanges ──────────────────────────────────────────────────────────

    def record_llm_exchange(
        self,
        *,
        run_id: str,
        session_id: str,
        round_num: int,
        messages: list[dict],
        response_content: str | None,
        tool_calls: list[Any] | None,
        finish_reason: str,
        duration_ms: int,
        error_msg: str | None = None,
    ) -> None:
        try:
            tc_json = None
            if tool_calls:
                tc_json = json.dumps(
                    [
                        {
                            "id": getattr(tc, "id", None),
                            "name": getattr(getattr(tc, "function", None), "name", None),
                            "arguments": getattr(getattr(tc, "function", None), "arguments", None),
                        }
                        for tc in tool_calls
                    ],
                    ensure_ascii=False,
                )
            with self._conn() as conn:
                conn.execute(
                    """INSERT INTO llm_exchanges
                       (run_id, session_id, round_num, ts, messages_json, response_json,
                        tool_calls_json, finish_reason, duration_ms, error_msg)
                       VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (
                        run_id,
                        session_id,
                        round_num,
                        _now(),
                        json.dumps(messages, ensure_ascii=False),
                        response_content,
                        tc_json,
                        finish_reason,
                        duration_ms,
                        error_msg,
                    ),
                )
        except Exception:
            log.warning("TraceDB.record_llm_exchange failed", exc_info=True)

    # ── tool_calls ─────────────────────────────────────────────────────────────

    def record_tool_call(
        self,
        *,
        run_id: str,
        session_id: str,
        round_num: int,
        call_index: int,
        tool_name: str,
        input_json: str | None,
        output_json: str | None,
        success: bool,
        error_msg: str | None = None,
        duration_ms: int = 0,
    ) -> None:
        try:
            with self._conn() as conn:
                conn.execute(
                    """INSERT INTO tool_calls
                       (run_id, session_id, round_num, call_index, ts, tool_name,
                        input_json, output_json, success, error_msg, duration_ms)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        run_id,
                        session_id,
                        round_num,
                        call_index,
                        _now(),
                        tool_name,
                        input_json,
                        output_json,
                        1 if success else 0,
                        error_msg,
                        duration_ms,
                    ),
                )
        except Exception:
            log.warning("TraceDB.record_tool_call failed", exc_info=True)

    # ── confirmations ─────────────────────────────────────────────────────────

    def record_confirmation(
        self,
        *,
        session_id: str,
        confirm_token: str,
        action_type: str | None,
        action_payload_json: str | None,
        decision: str,
        followup_text: str | None,
    ) -> None:
        try:
            with self._conn() as conn:
                conn.execute(
                    """INSERT INTO confirmations
                       (session_id, confirm_token, action_type, action_payload_json,
                        decision, followup_text, ts)
                       VALUES (?,?,?,?,?,?,?)""",
                    (
                        session_id,
                        confirm_token,
                        action_type,
                        action_payload_json,
                        decision,
                        followup_text,
                        _now(),
                    ),
                )
        except Exception:
            log.warning("TraceDB.record_confirmation failed", exc_info=True)

    def record_confirmation_result(
        self,
        *,
        confirm_token: str,
        exec_success: bool,
        exec_result_json: str | None,
    ) -> None:
        try:
            with self._conn() as conn:
                conn.execute(
                    """UPDATE confirmations
                       SET exec_success=?, exec_result_json=?
                       WHERE confirm_token=?""",
                    (1 if exec_success else 0, exec_result_json, confirm_token),
                )
        except Exception:
            log.warning("TraceDB.record_confirmation_result failed", exc_info=True)
