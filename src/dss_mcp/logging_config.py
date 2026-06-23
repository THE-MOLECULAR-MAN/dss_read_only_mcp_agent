import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path


class _JsonLineFormatter(logging.Formatter):
    """Emit one JSON object per line. Never writes credential field values."""

    _REDACTED_FIELDS = frozenset({
        "api_key", "apiKey", "password", "passwd", "secret", "token",
        "bearerToken", "accessToken", "secretKey", "accessKey", "credential",
    })

    def format(self, record: logging.LogRecord) -> str:
        entry: dict = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            entry["exc"] = self.formatException(record.exc_info)
        # Merge any extra fields added via logger.info(..., extra={...})
        for key, value in record.__dict__.items():
            if key in ("msg", "args", "levelname", "levelno", "pathname",
                       "filename", "module", "exc_info", "exc_text",
                       "stack_info", "lineno", "funcName", "created",
                       "msecs", "relativeCreated", "thread", "threadName",
                       "processName", "process", "name", "message",
                       "taskName"):
                continue
            if key.startswith("_"):
                continue
            entry[key] = "[REDACTED]" if key in self._REDACTED_FIELDS else value
        return json.dumps(entry)


def setup_logging() -> None:
    log_dir = Path(os.environ.get("DSS_MCP_LOG_DIR", Path.home() / ".dss-mcp"))
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "server.log"

    handler = logging.FileHandler(log_file, encoding="utf-8")
    handler.setFormatter(_JsonLineFormatter())

    root = logging.getLogger("dss_mcp")
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    root.propagate = False


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"dss_mcp.{name}")
