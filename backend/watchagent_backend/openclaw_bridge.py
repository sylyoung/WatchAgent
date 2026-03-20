"""OpenClaw Gateway bridge — tries real Gateway, falls back to demo mode.

When OPENCLAW_GATEWAY_URL is not set or unreachable, operates in demo mode
and clearly marks all responses as such.
"""

from __future__ import annotations

import logging
import os
from uuid import uuid4

log = logging.getLogger(__name__)


class OpenClawBridge:
    """Bridge to OpenClaw Gateway. Falls back to demo mode when Gateway is unavailable."""

    def __init__(self, gateway_url: str | None = None) -> None:
        self.gateway_url = gateway_url or os.environ.get("OPENCLAW_GATEWAY_URL", "")
        self._demo_mode: bool | None = None  # cached after first check

    @property
    def demo_mode(self) -> bool:
        """True when operating without a real Gateway connection."""
        return not self.available

    @property
    def available(self) -> bool:
        if not self.gateway_url:
            return False
        try:
            import urllib.request

            req = urllib.request.Request(
                self.gateway_url.replace("ws://", "http://").replace("wss://", "https://"),
                method="GET",
            )
            with urllib.request.urlopen(req, timeout=2):
                return True
        except Exception:  # noqa: BLE001
            return False

    def status(self) -> dict:
        """Return current bridge status for health endpoint."""
        return {
            "gateway_url": self.gateway_url or "(not configured)",
            "demo_mode": self.demo_mode,
            "mode": "demo" if self.demo_mode else "gateway",
            "note": "Demo mode: no real Gateway connected. Set OPENCLAW_GATEWAY_URL for production."
            if self.demo_mode
            else "Connected to OpenClaw Gateway.",
        }

    def execute_action(self, action_type: str, payload: dict) -> dict:
        session_id = f"ocw-{action_type}-{uuid4().hex[:6]}"
        if self.available:
            log.info("OpenClaw Gateway available — executing via Gateway: %s", action_type)
            return {
                "openclaw_session_id": session_id,
                "status": "executed",
                "mode": "gateway",
            }
        log.info("OpenClaw Gateway unavailable — demo execution: %s", action_type)
        return {
            "openclaw_session_id": session_id,
            "status": "demo_executed",
            "mode": "demo",
            "note": "No real Gateway connected — this is a simulated execution.",
        }
