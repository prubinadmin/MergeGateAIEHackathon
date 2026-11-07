"""Muse Spark client. Reads MUSE_API_KEY, MUSE_BASE_URL, MUSE_MODEL from the environment / .env.

The model writes tests and message summaries. It never decides a verdict.
"""

from __future__ import annotations

import os


def load_dotenv(path: str = ".env") -> None:
    """Minimal .env loader (no dependency). Existing environment variables win."""
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


def complete(system: str, user: str, *, max_tokens: int = 2000) -> str:
    """One chat completion from Muse Spark. Wire up once the API docs and key arrive."""
    raise NotImplementedError("Muse Spark API not wired yet")
