"""Gemini client — the only place hosted LLM calls go.

Brain 1 (classify) may ask YES/NO. The planner never calls this, so the model
cannot invent resource ids or write steps_json.

Cache (`llm_cache.json`) is the source of truth on a judge rerun. A live call
only fills a cache miss. No key / error → None, and the phrase list takes over.

Do not put API keys in this tree. Read GEMINI_API_KEY or GOOGLE_API_KEY.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Optional

_CACHE_PATH = Path(__file__).resolve().parent / "llm_cache.json"
_USAGE_PATH = Path(__file__).resolve().parent / "llm_usage.json"

# 2.0/2.5 Flash are blocked for new keys (Oct 2026). 3.8 Flash timed out
# on this key; 3.5 Flash-Lite answers in <1s.
_MODEL_CANDIDATES = (
    "gemini-3.5-flash-lite",
    "gemini-flash-lite-latest",
    "gemini-3.5-flash",
    "gemini-3.1-flash-lite",
)

_MAX_RETRIES = 3
_RETRY_DELAY = 2.0

_cache: dict[str, Any] = {}
_cache_loaded = False
_client: Any = None
_model_name: Optional[str] = None
_stats: dict[str, Any] = {
    "provider": "google",
    "model": None,
    "live_calls": 0,
    "cache_hits": 0,
    "failures": 0,
    "input_tokens": 0,
    "output_tokens": 0,
}


def _load_cache() -> None:
    global _cache, _cache_loaded
    if _cache_loaded:
        return
    if _CACHE_PATH.exists():
        try:
            raw = json.loads(_CACHE_PATH.read_text(encoding="utf-8"))
            _cache = raw if isinstance(raw, dict) else {}
        except Exception:
            _cache = {}
    _cache_loaded = True


def _save_cache() -> None:
    _CACHE_PATH.write_text(json.dumps(_cache, ensure_ascii=False, indent=0), encoding="utf-8")


def _save_usage() -> None:
    payload = dict(_stats)
    payload["model"] = _model_name or payload.get("model")
    _USAGE_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def usage_stats() -> dict[str, Any]:
    out = dict(_stats)
    out["model"] = _model_name or out.get("model")
    return out


def _api_key() -> str:
    return (
        os.environ.get("GEMINI_API_KEY")
        or os.environ.get("GOOGLE_API_KEY")
        or os.environ.get("GOOGLE_GENAI_API_KEY")
        or ""
    ).strip()


def _get_client() -> Any:
    global _client, _model_name
    if _client is not None:
        return _client
    key = _api_key()
    if not key:
        return None
    try:
        from google import genai  # type: ignore

        _client = genai.Client(api_key=key)
        _model_name = _MODEL_CANDIDATES[0]
        return _client
    except Exception:
        try:
            import google.generativeai as genai  # type: ignore

            genai.configure(api_key=key)
            _client = ("legacy", genai)
            _model_name = "gemini-2.5-flash"
            return _client
        except Exception:
            return None


def _cache_key(prompt: str, model: str) -> str:
    return hashlib.sha256(f"{model}\n{prompt}".encode("utf-8")).hexdigest()


def _extract_usage(response: Any) -> tuple[int, int]:
    meta = getattr(response, "usage_metadata", None)
    if meta is None:
        return 0, 0
    prompt = int(getattr(meta, "prompt_token_count", 0) or 0)
    out = int(getattr(meta, "candidates_token_count", 0) or getattr(meta, "output_token_count", 0) or 0)
    return prompt, out


def _generate(prompt: str) -> Optional[str]:
    client = _get_client()
    if client is None:
        return None
    last_error: Exception | None = None
    delay = _RETRY_DELAY
    # Retry the same primary model. Do not rotate through four ids on three
    # attempts — that mis-labels the cache and burns the quota on dead aliases.
    model = _MODEL_CANDIDATES[0] if not isinstance(client, tuple) else "gemini-3.5-flash-lite"
    for attempt in range(_MAX_RETRIES):
        try:
            if isinstance(client, tuple):
                _, genai = client
                response = genai.GenerativeModel(model).generate_content(
                    prompt,
                    generation_config={"temperature": 0.0, "max_output_tokens": 16},
                )
                text = (response.text or "").strip()
            else:
                response = client.models.generate_content(
                    model=model,
                    contents=prompt,
                    config={"temperature": 0.0, "max_output_tokens": 16},
                )
                text = (getattr(response, "text", None) or "").strip()
            inp, out = _extract_usage(response)
            _stats["live_calls"] += 1
            _stats["input_tokens"] += inp
            _stats["output_tokens"] += out
            _stats["model"] = model
            global _model_name
            _model_name = model
            _save_usage()
            return text
        except Exception as exc:
            last_error = exc
            time.sleep(delay)
            delay *= 2
    _stats["failures"] += 1
    _save_usage()
    if last_error is not None:
        print(f"[llm_client] Gemini call failed: {type(last_error).__name__}")
    return None


def call_llm(prompt: str) -> Optional[str]:
    """Return model text, or None if cache-miss and no usable API."""
    _load_cache()
    key = _cache_key(prompt, "classify-v1")
    if key in _cache:
        _stats["cache_hits"] += 1
        entry = _cache[key]
        if isinstance(entry, dict):
            return str(entry.get("text") or "")
        return str(entry)
    text = _generate(prompt)
    if text is None:
        return None
    _cache[key] = {"text": text, "model": _model_name or _MODEL_CANDIDATES[0]}
    _save_cache()
    return text


def classify_deletion_yes_no(request_text: str) -> Optional[bool]:
    """YES → True, NO → False, unusable reply / no API → None."""
    prompt = (
        "You are a data-privacy intake agent. Decide if this message authorizes "
        "erasing the person's account or personal data (including confirming a "
        "prior deletion). Answer NO for downloads, invoice copies, marketing-only "
        "opt-out, profile corrections, login help, or any request that says they "
        "are not asking for deletion.\n"
        "Reply with exactly one word: YES or NO.\n\n"
        f"Message:\n{request_text.strip()}\n"
    )
    raw = call_llm(prompt)
    if raw is None:
        return None
    token = raw.strip().upper().split()
    if not token:
        return None
    word = token[0].strip(".,:;")
    if word.startswith("YES"):
        return True
    if word.startswith("NO"):
        return False
    return None
