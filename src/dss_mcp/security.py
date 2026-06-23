import re
from typing import Any

# Field names whose values must always be redacted
_SENSITIVE_KEYS: frozenset[str] = frozenset({
    "password", "passwd", "secret", "apiKey", "api_key", "token",
    "bearerToken", "accessToken", "secretKey", "accessKey", "sessionToken",
    "credential", "privateKey", "clientSecret", "ssoToken", "authToken",
    "stsToken", "refreshToken",
})

# Patterns that look like credentials even when the key name is innocuous
# Matches: long base64 blobs, JWTs (three dot-separated segments), hex secrets
_CREDENTIAL_VALUE_RE = re.compile(
    r"^(?:"
    r"[A-Za-z0-9+/]{40,}={0,2}"           # base64, 40+ chars
    r"|[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{20,}"  # JWT
    r"|[0-9a-fA-F]{32,}"                   # hex secret/token
    r")$"
)

_REDACTED = "[REDACTED]"


def redact(value: Any, key: str | None = None) -> Any:
    """Recursively redact sensitive values from dicts and lists.

    Redacts by field name match and by value pattern (long base64, JWTs, hex).
    """
    if isinstance(value, dict):
        return {k: redact(v, k) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    if key is not None and key in _SENSITIVE_KEYS:
        return _REDACTED
    if isinstance(value, str) and _CREDENTIAL_VALUE_RE.match(value):
        return _REDACTED
    return value


def safe_user_fields(user_dict: dict) -> dict:
    """Return only safe user fields; drop hashed passwords and internal IDs."""
    allowed = {"login", "displayName", "email", "groups", "sourceType"}
    return {k: v for k, v in user_dict.items() if k in allowed}
