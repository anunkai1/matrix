from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from unittest import mock
import sys


MODULE_PATH = (
    Path(__file__).resolve().parents[2] / "ops" / "runtime_observer" / "runtime_observer.py"
)
SPEC = spec_from_file_location("runtime_observer", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
runtime_observer = module_from_spec(SPEC)
sys.modules[SPEC.name] = runtime_observer
SPEC.loader.exec_module(runtime_observer)


def _base_service_states() -> tuple[dict, list[str]]:
    states = {}
    for service in runtime_observer.CORE_SERVICES:
        states[service] = {
            "active_state": "active",
            "sub_state": "running",
            "active": True,
            "down_seconds": 0.0,
            "nrestarts_total": 0,
        }
    return states, []


def test_benign_message_not_modified_400_does_not_warn_without_stats_event() -> None:
    now_dt = runtime_observer.now_utc()
    telegram_events = [
        {
            "event": "bridge.telegram_api_failed",
            "method": "editMessageText",
            "error_code": 400,
            "error_description": (
                "Bad Request: message is not modified: specified new message content "
                "and reply markup are exactly the same as a current content and "
                "reply markup of the message"
            ),
            "ts": now_dt.isoformat(),
        }
    ]

    with (
        mock.patch.object(
            runtime_observer,
            "collect_service_states",
            return_value=_base_service_states(),
        ),
        mock.patch.object(runtime_observer, "count_systemd_starts", return_value=0),
        mock.patch.object(runtime_observer, "load_telegram_events", return_value=telegram_events),
        mock.patch.object(runtime_observer, "summarize_wa_reconnects", return_value={"count": 0}),
    ):
        snapshot = runtime_observer.build_snapshot(now_dt)

    metric = snapshot["kpis"]["telegram_edit_400_rate"]
    assert metric["severity"] == "ok"
    assert metric["raw_edit_400_count"] == 1
    assert metric["benign_edit_400_count"] == 1
    assert metric["edit_400_count"] == 0
    assert metric["edit_attempts"] == 0
    assert "telegram-edit-rate-denominator-missing" not in snapshot["warnings"]
