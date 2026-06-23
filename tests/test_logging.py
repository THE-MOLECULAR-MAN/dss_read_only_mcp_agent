import json
import logging

import pytest

from dss_mcp.logging_config import _JsonLineFormatter

# Enumerate every field the formatter must redact
_ALL_LOG_REDACTED_FIELDS = sorted(_JsonLineFormatter._REDACTED_FIELDS)


def _make_record(msg: str, extra: dict | None = None) -> logging.LogRecord:
    logger = logging.getLogger("dss_mcp.test")
    record = logger.makeRecord(
        name="dss_mcp.test",
        level=logging.INFO,
        fn="test_logging.py",
        lno=1,
        msg=msg,
        args=(),
        exc_info=None,
    )
    if extra:
        for k, v in extra.items():
            setattr(record, k, v)
    return record


class TestJsonLineFormatter:
    def setup_method(self):
        self.fmt = _JsonLineFormatter()

    def test_output_is_valid_json(self):
        record = _make_record("hello")
        line = self.fmt.format(record)
        parsed = json.loads(line)
        assert isinstance(parsed, dict)

    def test_contains_required_fields(self):
        record = _make_record("test message")
        parsed = json.loads(self.fmt.format(record))
        assert "ts" in parsed
        assert "level" in parsed
        assert "logger" in parsed
        assert "msg" in parsed

    def test_message_preserved(self):
        record = _make_record("something happened")
        parsed = json.loads(self.fmt.format(record))
        assert parsed["msg"] == "something happened"

    def test_level_correct(self):
        record = _make_record("info msg")
        parsed = json.loads(self.fmt.format(record))
        assert parsed["level"] == "INFO"

    def test_extra_safe_field_included(self):
        record = _make_record("started", extra={"project_key": "MY_PROJ"})
        parsed = json.loads(self.fmt.format(record))
        assert parsed["project_key"] == "MY_PROJ"

    @pytest.mark.parametrize("field", _ALL_LOG_REDACTED_FIELDS)
    def test_every_sensitive_field_redacted(self, field):
        record = _make_record("event", extra={field: "sensitive-value"})
        parsed = json.loads(self.fmt.format(record))
        assert parsed[field] == "[REDACTED]"

    def test_internal_log_fields_excluded(self):
        record = _make_record("msg")
        parsed = json.loads(self.fmt.format(record))
        # Standard LogRecord attributes should not appear as extra fields
        assert "lineno" not in parsed
        assert "pathname" not in parsed
        assert "thread" not in parsed
        assert "processName" not in parsed

    def test_underscore_prefixed_extra_excluded(self):
        record = _make_record("msg", extra={"_internal": "skip-me"})
        parsed = json.loads(self.fmt.format(record))
        assert "_internal" not in parsed

    def test_numeric_extra_field_included(self):
        record = _make_record("done", extra={"elapsed_s": 1.23})
        parsed = json.loads(self.fmt.format(record))
        assert parsed["elapsed_s"] == pytest.approx(1.23)

    def test_single_line_output(self):
        record = _make_record("single line check")
        line = self.fmt.format(record)
        assert "\n" not in line
