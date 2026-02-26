import json
import logging
from datetime import datetime, timezone
from typing import Dict, Optional


class JsonLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: Dict[str, object] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }

        event_name = getattr(record, "event", None)
        if isinstance(event_name, str) and event_name:
            payload["event"] = event_name

        fields = getattr(record, "fields", None)
        if isinstance(fields, dict):
            for key, value in fields.items():
                payload[key] = value

        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)

        return json.dumps(payload, sort_keys=True, ensure_ascii=True)


def configure_bridge_logging(level_name: str) -> None:
    level = getattr(logging, level_name.upper(), logging.INFO)
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()

    handler = logging.StreamHandler()
    handler.setFormatter(JsonLogFormatter())
    root.addHandler(handler)


def emit_event(
    event: str,
    *,
    level: int = logging.INFO,
    logger_name: str = "telegram_bridge",
    fields: Optional[Dict[str, object]] = None,
) -> None:
    safe_fields = fields if isinstance(fields, dict) else {}
    logging.getLogger(logger_name).log(
        level,
        event,
        extra={
            "event": event,
            "fields": safe_fields,
        },
    )
