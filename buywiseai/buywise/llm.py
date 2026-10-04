"""Groq client wrapper for openai/gpt-oss-120b."""
from __future__ import annotations

import json
import logging
import re

from buywise.config import get_secret, load_app_settings

log = logging.getLogger(__name__)


class LLMError(RuntimeError):
    pass


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
        client = self._get_client()
        try:
            resp = client.chat.completions.create(reasoning_effort=reasoning, **kwargs)
        except TypeError:
            resp = client.chat.completions.create(**kwargs)   # older SDK without reasoning_effort
        except Exception as e:
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
