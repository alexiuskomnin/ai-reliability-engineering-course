"""Secret masking helpers.

Applied to tool outputs when RuntimeConfig.mask_secrets is true.
Conservative by design: redact, never raise.
"""

from __future__ import annotations

from typing import Any

REDACTED = "***"
_SENSITIVE_KEY_SUFFIXES = ("password", "token", "key", "cert", "secret")


def mask(obj: Any) -> Any:
    """Recursively redact sensitive fields in a Kubernetes object dict."""
    if isinstance(obj, dict):
        kind = obj.get("kind")
        if kind == "Secret":
            return _mask_secret(obj)
        return {k: _mask_value(k, v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [mask(item) for item in obj]
    return obj


def _mask_secret(secret: dict) -> dict:
    out = dict(secret)
    for field in ("data", "stringData"):
        if field in out and isinstance(out[field], dict):
            out[field] = {k: REDACTED for k in out[field]}
    return out


def _mask_value(key: str, value: Any) -> Any:
    lowered = key.lower()
    if any(lowered.endswith(s) for s in _SENSITIVE_KEY_SUFFIXES) and isinstance(
        value, str
    ):
        return REDACTED
    return mask(value)
