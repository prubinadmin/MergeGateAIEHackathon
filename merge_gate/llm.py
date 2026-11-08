"""Muse Spark client (Meta Model API, OpenAI-compatible Chat Completions).

Reads MUSE_API_KEY, MUSE_BASE_URL, MUSE_MODEL from the environment, .env or .env.local.
The model writes tests and message summaries. It never decides a verdict.

Docs: https://dev.meta.ai/docs/cookbook/quickstart-chat-completions
- base URL https://api.meta.ai/v1, model muse-spark-1.3
- prefer role "developer" over "system"; `stop`/`logit_bias` return 400
- retry 429 and 5xx with backoff, never retry 400
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import time
import urllib.error
import urllib.request

DEFAULT_BASE_URL = "https://api.meta.ai/v1"
DEFAULT_MODEL = "muse-spark-1.3"
# Muse is the default writer; Gemini (gemini-4-argon) is a second, independent one from another lab. Both speak
# chat/completions; they differ in env names, defaults and which role carries the instructions.
PROVIDERS = {
    "muse": {"key": "MUSE_API_KEY", "base": "MUSE_BASE_URL", "model": "MUSE_MODEL",
             "default_base": DEFAULT_BASE_URL, "default_model": DEFAULT_MODEL, "system_role": "developer"},
    "gemini": {"key": "GEMINI_API_KEY", "base": "GEMINI_BASE_URL", "model": "GEMINI_MODEL",
               "default_base": "https://generativelanguage.googleapis.com/v1beta/openai", "default_model": "gemini-4-argon",
               "system_role": "system"},
}
CACHE_DIR = os.path.join(".cache", "llm")


class LLMError(RuntimeError):
    pass


def load_dotenv(*paths: str) -> None:
    """Minimal .env loader (no dependency). Existing environment variables win; empty values are skipped."""
    for path in paths or (".env", ".env.local"):
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key, value = key.strip(), value.strip().strip('"').strip("'")
                if value and not os.environ.get(key):
                    os.environ[key] = value


def has_key(provider: str = "muse") -> bool:
    load_dotenv()
    return bool(os.environ.get(PROVIDERS[provider]["key"]))


def model_name(provider: str = "muse") -> str:
    load_dotenv()
    p = PROVIDERS[provider]
    return os.environ.get(p["model"]) or p["default_model"]


def _config(provider: str = "muse") -> tuple[str, str, str]:
    load_dotenv()
    p = PROVIDERS[provider]
    key = os.environ.get(p["key"], "")
    if not key:
        raise LLMError(f"{p['key']} is not set (.env or .env.local)")
    base = os.environ.get(p["base"]) or p["default_base"]
    return key, base.rstrip("/"), model_name(provider)


def complete(
    developer: str,
    user: str,
    *,
    temperature: float | None = None,
    timeout_s: int = 180,
    retries: int = 4,
    use_cache: bool = True,
    provider: str = "muse",
) -> str:
    """One chat completion from Muse (default) or Gemini; returns the message text.

    Responses are cached on disk by request hash (the model is part of it), so benchmark reruns and the demo
    are replayable offline.
    """
    key, base, model = _config(provider)
    body: dict = {
        "model": model,
        "messages": [
            {"role": PROVIDERS[provider]["system_role"], "content": developer},
            {"role": "user", "content": user},
        ],
    }
    if temperature is not None:
        body["temperature"] = temperature

    digest = hashlib.sha256(json.dumps(body, sort_keys=True).encode("utf-8")).hexdigest()
    cache_path = os.path.join(CACHE_DIR, digest + ".json")
    if use_cache and os.path.exists(cache_path):
        with open(cache_path, encoding="utf-8") as f:
            return json.load(f)["text"]

    data = json.dumps(body).encode("utf-8")
    last_err: Exception | None = None
    for attempt in range(retries + 1):
        req = urllib.request.Request(
            f"{base}/chat/completions",
            data=data,
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
                "User-Agent": "merge-gate/0.1",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            break
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:500]
            if e.code == 429 or e.code >= 500:
                last_err = LLMError(f"HTTP {e.code}: {detail}")
            else:
                raise LLMError(f"HTTP {e.code}: {detail}") from None
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            last_err = e
        if attempt < retries:
            time.sleep(min(30, 2**attempt) + random.random())
    else:
        raise LLMError(f"{model} call failed after {retries + 1} attempts: {last_err}")

    try:
        text = payload["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError):
        raise LLMError(f"unexpected response shape: {str(payload)[:300]}") from None

    if use_cache:
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump({"text": text, "usage": payload.get("usage"), "model": model}, f)
    return text
