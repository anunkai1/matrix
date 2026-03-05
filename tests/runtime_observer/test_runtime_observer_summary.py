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


def _metric(worst: str) -> dict:
    return {
        "worst_severity": worst,
        "severity_counts": {"warn": 0, "critical": 0},
        "value_percent": {"min": 0.0, "avg": 0.0, "max": 0.0},
        "max_restarts_per_service_last_hour": {"min": 0.0, "avg": 0.0, "max": 0.0},
        "count_last_15m": {"min": 0.0, "avg": 0.0, "max": 0.0},
        "rate_percent": {"min": 0.0, "avg": 0.0, "max": 0.0},
        "count_last_hour": {"min": 0.0, "avg": 0.0, "max": 0.0},
    }


def _summary_with_kpis(kpis: dict) -> dict:
    return {
        "hours": 24,
        "timezone": "Australia/Brisbane",
        "snapshot_count": 288,
        "first_snapshot_local": "2026-03-05T08:10:29.817030+10:00",
        "last_snapshot_local": "2026-03-06T08:05:32.247648+10:00",
        "kpis": kpis,
    }


def test_operator_summary_line_healthy_no_attention() -> None:
    kpis = {
        "service_up": _metric("ok"),
        "restart_count": _metric("ok"),
        "telegram_retry_rate": _metric("ok"),
        "telegram_edit_400_rate": _metric("ok"),
        "wa_reconnect_rate": _metric("ok"),
        "request_fail_rate": _metric("ok"),
    }
    text = runtime_observer.format_summary(_summary_with_kpis(kpis))
    assert text.endswith(
        "Summary: system is healthy overall, and no attention is needed right now."
    )


def test_operator_summary_line_healthy_with_warning_spikes() -> None:
    kpis = {
        "service_up": _metric("ok"),
        "restart_count": _metric("warn"),
        "telegram_retry_rate": _metric("ok"),
        "telegram_edit_400_rate": _metric("critical"),
        "wa_reconnect_rate": _metric("ok"),
        "request_fail_rate": _metric("ok"),
    }
    text = runtime_observer.format_summary(_summary_with_kpis(kpis))
    assert text.endswith(
        "Summary: system is healthy overall, but you had intermittent Telegram edit-400 spikes, some restarts that triggered warnings."
    )


def test_operator_summary_line_attention_needed() -> None:
    kpis = {
        "service_up": _metric("critical"),
        "restart_count": _metric("ok"),
        "telegram_retry_rate": _metric("ok"),
        "telegram_edit_400_rate": _metric("ok"),
        "wa_reconnect_rate": _metric("ok"),
        "request_fail_rate": _metric("critical"),
    }
    text = runtime_observer.format_summary(_summary_with_kpis(kpis))
    assert text.endswith(
        "Summary: attention needed now due to request failures, service availability drops."
    )
