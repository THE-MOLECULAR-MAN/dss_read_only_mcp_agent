import pytest

from dss_mcp.security import _SENSITIVE_KEYS, redact, safe_user_fields

_REDACTED = "[REDACTED]"

# Every key in _SENSITIVE_KEYS must be redacted regardless of value
_ALL_SENSITIVE_KEYS = sorted(_SENSITIVE_KEYS)


class TestRedactByKeyName:
    @pytest.mark.parametrize("key", _ALL_SENSITIVE_KEYS)
    def test_every_sensitive_key_is_redacted(self, key):
        assert redact("some-value", key=key) == _REDACTED

    @pytest.mark.parametrize("key", _ALL_SENSITIVE_KEYS)
    def test_none_value_with_sensitive_key_is_redacted(self, key):
        assert redact(None, key=key) == _REDACTED

    def test_safe_key_short_string_unchanged(self):
        assert redact("Alice", key="displayName") == "Alice"

    def test_safe_key_int_unchanged(self):
        assert redact(42, key="count") == 42

    def test_safe_key_bool_unchanged(self):
        assert redact(True, key="enabled") is True

    def test_no_key_safe_string_unchanged(self):
        assert redact("hello world") == "hello world"


class TestRedactByValuePattern:
    def test_base64_40_chars_redacted(self):
        b64 = "A" * 40
        assert redact(b64, key="someField") == _REDACTED

    def test_base64_with_padding_redacted(self):
        b64 = "A" * 40 + "=="
        assert redact(b64, key="someField") == _REDACTED

    def test_base64_39_chars_not_redacted(self):
        # 39 chars with non-hex characters (G-Z) so the hex pattern also doesn't match
        b64 = "G" * 39
        assert redact(b64, key="someField") == b64

    def test_jwt_redacted(self):
        # Three dot-separated segments of 20+ base64url chars each
        jwt = (
            "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9"
            ".eyJzdWIiOiJ1c2VyMTIzIiwibmFtZSI6IkpvaG4ifQ"
            ".SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
        )
        assert redact(jwt, key="someField") == _REDACTED

    def test_hex_32_chars_redacted(self):
        hex_val = "a" * 32
        assert redact(hex_val, key="someField") == _REDACTED

    def test_hex_31_chars_not_redacted(self):
        # 31 chars is below the 32-char hex threshold
        hex_val = "a" * 31
        assert redact(hex_val, key="someField") == hex_val

    def test_normal_string_not_matching_pattern_unchanged(self):
        assert redact("my-project", key="name") == "my-project"


class TestRedactRecursive:
    def test_nested_dict_recursive(self):
        data = {"user": {"password": "secret", "name": "Alice"}}
        result = redact(data)
        assert result["user"]["password"] == _REDACTED
        assert result["user"]["name"] == "Alice"

    def test_deeply_nested(self):
        data = {"a": {"b": {"token": "tok", "label": "safe"}}}
        result = redact(data)
        assert result["a"]["b"]["token"] == _REDACTED
        assert result["a"]["b"]["label"] == "safe"

    def test_list_items_redacted(self):
        data = [{"token": "tok123"}, {"name": "safe"}]
        result = redact(data)
        assert result[0]["token"] == _REDACTED
        assert result[1]["name"] == "safe"

    def test_list_of_strings_with_credential_pattern(self):
        data = ["A" * 40, "short"]
        result = redact(data)
        assert result[0] == _REDACTED
        assert result[1] == "short"

    def test_mixed_types_in_list(self):
        data = [42, True, None, "safe"]
        assert redact(data) == [42, True, None, "safe"]

    def test_empty_dict(self):
        assert redact({}) == {}

    def test_empty_list(self):
        assert redact([]) == []

    def test_value_pattern_inside_nested_dict(self):
        b64 = "Z" * 40
        data = {"connection": {"url": "jdbc:postgres://host/db", "password": b64}}
        result = redact(data)
        # Redacted by key name (password) — the b64 value also matches, but key wins
        assert result["connection"]["password"] == _REDACTED
        assert result["connection"]["url"] == "jdbc:postgres://host/db"


class TestSafeUserFields:
    def test_keeps_all_allowed_fields(self):
        user = {
            "login": "alice",
            "displayName": "Alice Smith",
            "email": "alice@example.com",
            "groups": ["admin", "data-science"],
            "sourceType": "LOCAL",
        }
        assert safe_user_fields(user) == user

    def test_drops_password(self):
        user = {"login": "alice", "password": "secret", "hashedPassword": "xxx"}
        result = safe_user_fields(user)
        assert "password" not in result
        assert "hashedPassword" not in result
        assert result["login"] == "alice"

    def test_drops_internal_id(self):
        user = {"login": "bob", "internalId": "123", "createdOn": 12345}
        result = safe_user_fields(user)
        assert "internalId" not in result
        assert "createdOn" not in result

    def test_empty_user(self):
        assert safe_user_fields({}) == {}

    def test_no_allowed_fields_returns_empty(self):
        user = {"password": "x", "secret": "y"}
        assert safe_user_fields(user) == {}
