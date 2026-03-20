"""Volcano Engine (豆包) TTS client — 豆包语音合成模型2.0.

Uses the HTTP Chunked/SSE unidirectional V3 endpoint.
Requires env vars: VOLCENGINE_APPID, VOLCENGINE_ACCESS_KEY.
"""

from __future__ import annotations

import io
import json
import logging
import os
import uuid

import requests as http_requests

log = logging.getLogger(__name__)

# ── Voice catalogue (from console 音色详情) ────────────────────────────────
VOICE_OPTIONS: list[dict[str, str]] = [
    {"id": "zh_female_vv_uranus_bigtts",              "label": "vivi 2.0 (通用女声)"},
    {"id": "saturn_zh_female_cancan_tob",              "label": "知性灿灿"},
    {"id": "saturn_zh_female_keainvsheng_tob",         "label": "可爱女生"},
    {"id": "saturn_zh_female_tiaopigongzhu_tob",       "label": "调皮公主"},
    {"id": "saturn_zh_male_shuanglangshaonian_tob",    "label": "爽朗少年"},
    {"id": "saturn_zh_male_tiancaitongzhuo_tob",       "label": "天才同桌"},
]

_SSE_ENDPOINT = "https://openspeech.bytedance.com/api/v3/tts/unidirectional/sse"


class VolcengineTTS:
    """Synchronous Volcano Engine TTS client (豆包语音合成模型2.0, HTTP SSE)."""

    def __init__(self) -> None:
        self.appid = os.environ.get("VOLCENGINE_APPID", "")
        self.access_key = os.environ.get("VOLCENGINE_ACCESS_KEY", "")
        self.resource_id = os.environ.get("VOLCENGINE_RESOURCE_ID", "seed-tts-2.0")
        self.available = bool(self.appid and self.access_key)
        if not self.available:
            log.warning("Volcano TTS not configured — missing VOLCENGINE_APPID / VOLCENGINE_ACCESS_KEY")

    def synthesize(
        self,
        text: str,
        voice_type: str = "zh_female_vv_uranus_bigtts",
        speed_ratio: float = 1.0,
        encoding: str = "mp3",
    ) -> bytes | None:
        """Convert *text* to audio. Returns MP3 bytes or ``None`` on failure."""
        if not self.available or not text.strip():
            return None

        # Speed ratio → speech_rate: 0 = normal, range [-50, 100], 100 = 2x speed
        # Map speed_ratio 0.5–2.0 → speech_rate -50–100
        speech_rate = int((speed_ratio - 1.0) * 100)
        speech_rate = max(-50, min(100, speech_rate))

        headers = {
            "Content-Type": "application/json",
            "X-Api-App-Key": self.appid,
            "X-Api-Access-Key": self.access_key,
            "X-Api-Resource-Id": self.resource_id,
        }

        payload = {
            "user": {"uid": "watchagent"},
            "event": 100,  # TaskRequest
            "req_params": {
                "text": text,
                "speaker": voice_type,
                "audio_params": {
                    "format": encoding,
                    "sample_rate": 24000,
                    "speech_rate": speech_rate,
                },
            },
        }

        try:
            resp = http_requests.post(
                _SSE_ENDPOINT,
                json=payload,
                headers=headers,
                timeout=15,
                stream=True,
            )

            if resp.status_code != 200:
                log.warning("TTS HTTP %d: %s", resp.status_code, resp.text[:200])
                return None

            # Collect audio chunks from SSE stream
            audio_buf = io.BytesIO()
            for line in resp.iter_lines():
                if not line:
                    continue
                line_str = line.decode("utf-8", errors="replace")
                if line_str.startswith("data:"):
                    data_str = line_str[5:].strip()
                    if not data_str:
                        continue
                    try:
                        event = json.loads(data_str)
                        # Audio data is base64 encoded in the "data" field
                        if "data" in event and event.get("data"):
                            import base64
                            audio_buf.write(base64.b64decode(event["data"]))
                    except (json.JSONDecodeError, KeyError):
                        pass

            audio_bytes = audio_buf.getvalue()
            if audio_bytes:
                return audio_bytes

            log.warning("TTS returned no audio data")
            return None

        except Exception:
            log.exception("TTS request failed")
            return None
