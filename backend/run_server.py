from __future__ import annotations

import os
from pathlib import Path

import uvicorn

# Auto-load .env if present (so Volcano TTS keys etc. are available)
_env_file = Path(__file__).resolve().parent / ".env"
if _env_file.exists():
    for line in _env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


def get_bind_config() -> tuple[str, int]:
    host = os.getenv("WATCHAGENT_HOST", "0.0.0.0")
    port = int(os.getenv("WATCHAGENT_PORT", "8787"))
    return host, port


def main() -> None:
    host, port = get_bind_config()
    uvicorn.run("watchagent_backend.app:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    main()
