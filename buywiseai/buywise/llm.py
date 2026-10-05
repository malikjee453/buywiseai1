"""Groq client wrapper for openai/gpt-oss-120b."""
from __future__ import annotations

import json
import logging
import re
import time

from buywise.config import get_secret, load_app_settings

log = logging.getLogger(__name__)


class LLMError(RuntimeError):
    pass


_cooldown_until = 0.0          # unix time until which we don't call the API (rate limit hit)
_RETRY_IN = re.compile(r"try again in\s+(?:(\d+)h)?\s*(?:(\d+)m)?\s*(?:(\d+(?:\.\d+)?)s)?", re.I)


def is_rate_limited(msg: str) -> bool:
    low = msg.lower()
    return "429" in low or "rate limit" in low or "rate_limit" in low


def retry_seconds(msg: str, default: float = 60.0) -> float:
    """Seconds from 'Please try again in 7m33.6s' (capped at 1h so we re-check regularly)."""
    m = _RETRY_IN.search(msg)
    if not m or not any(m.groups()):
        return default
    h, mi, sec = (float(g) if g else 0.0 for g in m.groups())
    return min(h * 3600 + mi * 60 + sec, 3600.0)


def rate_limited_now() -> bool:
    return time.time() < _cooldown_until


def _rate_limit_error() -> LLMError:
    mins = max(1, round((_cooldown_until - time.time()) / 60))
    return LLMError(f"Groq rate limit reached (token cap): AI steps paused ~{mins} min, rule-based checks still run")


class LLM:
    """Thin wrapper around the official `groq` SDK (lazy client, JSON helpers)."""

    def __init__(self, temperature: float = 0.2, model: str | None = None):
        self.model = model or load_app_settings()["llm"]["model"]
        self.temperature = temperature
        self._client = None

    def available(self) -> bool:
        return bool(get_secret("GROQ_API_KEY"))

    def _get_client(self):
        if self._client is None:
            key = get_secret("GROQ_API_KEY")
            if not key:
                raise LLMError("GROQ_API_KEY is not set")
            from groq import Groq

            self._client = Groq(api_key=key, timeout=45.0, max_retries=2)
        return self._client

    def chat(
        self,
        system: str,
        user: str,
        *,
        json_mode: bool = False,
        max_tokens: int = 3000,
        temperature: float | None = None,
        reasoning: str = "low",
    ) -> str:
        """Single chat completion. `max_tokens` includes the model's reasoning tokens."""
        kwargs = dict(
            model=self.model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=self.temperature if temperature is None else temperature,
            max_completion_tokens=max_tokens,
        )
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        global _cooldown_until
        if rate_limited_now():                         # don't spend a request (or wait on retries) while capped
            raise _rate_limit_error()
        client = self._get_client()
        try:
            try:
                resp = client.chat.completions.create(reasoning_effort=reasoning, **kwargs)
            except TypeError:
                resp = client.chat.completions.create(**kwargs)   # older SDK without reasoning_effort
        except Exception as e:
            if is_rate_limited(str(e)):
                _cooldown_until = time.time() + retry_seconds(str(e))
                raise _rate_limit_error() from e
            raise LLMError(str(e)) from e
        return (resp.choices[0].message.content or "").strip()

    def chat_json(self, system: str, user: str, **kw) -> dict:
        text = self.chat(system, user, json_mode=True, **kw)
        return parse_json(text)


def parse_json(text: str) -> dict:
    """Parse a JSON object from model output, tolerating code fences and chatter."""
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
    raise LLMError("Model did not return valid JSON")
