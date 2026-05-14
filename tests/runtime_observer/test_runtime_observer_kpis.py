from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys


MODULE_PATH = (
    Path(__file__).resolve().parents[2] / "ops" / "runtime_observer" / "runtime_observer.py"
)
SPEC = spec_from_file_location("runtime_observer", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
runtime_observer = module_from_spec(SPEC)
sys.modules[SPEC.name] = runtime_observer
SPEC.loader.exec_module(runtime_observer)


def test_summarize_telegram_retry_bursts_groups_single_outage_window() -> None:
    rows = [
        {
            "event": "bridge.telegram_api_retry_scheduled",
            "method": "getUpdates",
            "ts": "2026-05-14T19:35:15.906732+00:00",
            "error_description": "<urlopen error [Errno 101] Network is unreachable>",
        },
        {
            "event": "bridge.telegram_api_retry_scheduled",
            "method": "getUpdates",
            "ts": "2026-05-14T19:35:19.280476+00:00",
            "error_description": "<urlopen error [Errno 101] Network is unreachable>",
        },
        {
            "event": "bridge.telegram_api_failed",
            "method": "getUpdates",
            "transient": True,
            "ts": "2026-05-14T19:35:25.622816+00:00",
            "error_description": "<urlopen error [Errno 101] Network is unreachable>",
        },
        {
            "event": "bridge.telegram_api_retry_scheduled",
            "method": "getUpdates",
            "ts": "2026-05-14T19:40:42.715804+00:00",
            "error_description": "<urlopen error [Errno 101] Network is unreachable>",
        },
        {
            "event": "bridge.telegram_api_retry_succeeded",
            "method": "getUpdates",
            "ts": "2026-05-14T19:41:22.567986+00:00",
        },
    ]

    summary = runtime_observer.summarize_telegram_retry_bursts(rows)

    assert summary["burst_count"] == 1
    assert summary["raw_retry_attempts"] == 3
    assert summary["max_burst_duration_seconds"] == 366.661
    assert len(summary["bursts"]) == 1
    assert summary["bursts"][0]["recovered"] is True


def test_summarize_telegram_retry_bursts_splits_distinct_windows() -> None:
    rows = [
        {
            "event": "bridge.telegram_api_retry_scheduled",
            "method": "getUpdates",
            "ts": "2026-05-14T15:57:59.405198+00:00",
        },
        {
            "event": "bridge.telegram_api_retry_succeeded",
            "method": "getUpdates",
            "ts": "2026-05-14T15:58:21.904515+00:00",
        },
        {
            "event": "bridge.telegram_api_retry_scheduled",
            "method": "getUpdates",
            "ts": "2026-05-14T19:35:15.906732+00:00",
        },
        {
            "event": "bridge.telegram_api_retry_succeeded",
            "method": "getUpdates",
            "ts": "2026-05-14T19:41:22.567986+00:00",
        },
    ]

    summary = runtime_observer.summarize_telegram_retry_bursts(rows)

    assert summary["burst_count"] == 2
    assert summary["raw_retry_attempts"] == 2


def test_summarize_wa_reconnects_collects_status_codes(tmp_path: Path) -> None:
    log_path = tmp_path / "service.log"
    log_path.write_text(
        "\n".join(
            [
                '{"time":1778792957944,"statusCode":428,"shouldReconnect":true,"msg":"whatsapp connection closed"}',
                '{"time":1778794762886,"statusCode":503,"shouldReconnect":true,"msg":"whatsapp connection closed"}',
                '{"time":1778794776508,"statusCode":428,"shouldReconnect":true,"msg":"whatsapp connection closed"}',
                '{"time":1778794776508,"statusCode":401,"shouldReconnect":false,"msg":"whatsapp connection closed"}',
            ]
        ),
        encoding="utf-8",
    )

    since_dt = runtime_observer.datetime.fromtimestamp(1778792000, tz=runtime_observer.timezone.utc)
    summary = runtime_observer.summarize_wa_reconnects(since_dt, log_path)

    assert summary["count"] == 3
    assert summary["status_codes"] == ["428x2", "503x1"]
