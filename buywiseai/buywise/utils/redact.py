"""Remove API keys / tokens from text before it is logged or shown in the UI trace."""
import re

_SECRET_RE = re.compile(r"((?:api[_-]?key|key|token|secret|authorization|bearer)[\"'=:\s]+)([A-Za-z0-9._\-]{8,})", re.I)


def redact_secrets(text: str) -> str:
    return _SECRET_RE.sub(r"\1***", text or "")
