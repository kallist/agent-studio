from __future__ import annotations

import re
from typing import Any

from app.domain.contracts import AgentEvent

REDACTED = "[REDACTED]"
_SENSITIVE_KEYS = {
    "authorization",
    "apikey",
    "accesstoken",
    "refreshtoken",
    "password",
    "secret",
    "cookie",
    "setcookie",
}
_KEY_PARTS = re.compile(r"[^a-z0-9]")
_AUTHORIZATION_VALUE = re.compile(r"(?i)\b(authorization)\s*([:=])\s*([^\r\n,;]+)")
_LABELED_SECRET = re.compile(
    r"(?i)\b(api[ _-]?key|access[ _-]?token|refresh[ _-]?token|password|secret|"
    r"set-cookie|cookie)\s*([:=])\s*([^\s,;]+)"
)


def _normalized_key(key: object) -> str:
    return _KEY_PARTS.sub("", str(key).casefold())


def redact_text(value: str) -> str:
    """Redact only explicitly labelled secrets in free-form error text."""

    authorization_safe = _AUTHORIZATION_VALUE.sub(
        lambda match: f"{match.group(1)}{match.group(2)}{REDACTED}", value
    )
    return _LABELED_SECRET.sub(
        lambda match: f"{match.group(1)}{match.group(2)}{REDACTED}", authorization_safe
    )


def redact_value(value: Any) -> Any:
    """Recursively redact structured trace data without deleting normal token prose."""

    if isinstance(value, dict):
        return {
            str(key): REDACTED if _normalized_key(key) in _SENSITIVE_KEYS else redact_value(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact_value(item) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


def sanitize_event(event: AgentEvent) -> AgentEvent:
    """Return the safe event used by both persistence and live publication."""

    payload = redact_value(event.payload)
    if not isinstance(payload, dict):
        raise TypeError("Agent event payload must remain an object after redaction.")
    return event.model_copy(update={"payload": payload})
