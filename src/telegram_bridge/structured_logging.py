import json
import logging
import os
from datetime import datetime, timezone
from typing import Dict, Optional, Set


DEFAULT_SUPPRESSED_INFO_EVENTS = frozenset(
    {
        "bridge.poll_updates_received",
        "bridge.progress_edit_stats",
        "bridge.request_phase_timing",
    }
)

_suppressed_info_events: Set[str] = set(DEFAULT_SUPPRESSED_INFO_EVENTS)

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
    global _suppressed_info_events
    level = getattr(logging, level_name.upper(), logging.INFO)
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()
    _suppressed_info_events = _load_suppressed_info_events()

    handler = logging.StreamHandler()
    handler.setFormatter(JsonLogFormatter())
    root.addHandler(handler)


def _load_suppressed_info_events() -> Set[str]:
    raw = os.getenv("TELEGRAM_LOG_SUPPRESS_EVENTS")
    if raw is None:
        return set(DEFAULT_SUPPRESSED_INFO_EVENTS)

    normalized = raw.strip().lower()
    if normalized in {"", "none", "off", "disabled", "empty"}:
        return set()

    return {item.strip() for item in raw.split(",") if item.strip()}

def emit_event(
    event: str,
    *,
    level: int = logging.INFO,
    logger_name: str = "telegram_bridge",
    fields: Optional[Dict[str, object]] = None,
) -> None:
    if level == logging.INFO and event in _suppressed_info_events:
        return
    safe_fields = fields if isinstance(fields, dict) else {}
    logging.getLogger(logger_name).log(
        level,
        event,
        extra={
            "event": event,
            "fields": safe_fields,
        },
    )
