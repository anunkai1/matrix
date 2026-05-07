#!/usr/bin/env python3
"""Runtime observer for Server3 bridge services.

Phase-1 mode is collect-only: compute KPI state, persist snapshots, and expose
operator commands. Phase-2 can enable Telegram alert delivery with cooldown.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple
from zoneinfo import ZoneInfo


SYSTEMD_STARTED_MESSAGE_ID = "39f53479d3a045ac8e11786248231fbf"
CORE_SERVICES = (
    "telegram-architect-bridge.service",
    "telegram-tank-bridge.service",
    "telegram-trinity-bridge.service",
    "telegram-sentinel-bridge.service",
    "whatsapp-govorun-bridge.service",
    "govorun-whatsapp-bridge.service",
)
TELEGRAM_UNIT = "telegram-architect-bridge.service"
WA_RUNTIME_LOG_DEFAULT = "/home/govorun/whatsapp-govorun/state/logs/service.log"
SEVERITY_ORDER = {"ok": 0, "warn": 1, "critical": 2, "unknown": 3}


def env_int(name: str, default: int, minimum: int = 0) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        parsed = int(raw)
    except ValueError:
        return default
    return max(minimum, parsed)


TZ_NAME = os.getenv("RUNTIME_OBSERVER_TZ", "Australia/Brisbane")
STATE_DIR = Path(os.getenv("RUNTIME_OBSERVER_STATE_DIR", "/var/lib/server3-runtime-observer"))
SNAPSHOT_PATH = STATE_DIR / "snapshots.jsonl"
ALERT_STATE_PATH = STATE_DIR / "alert_state.json"
RETENTION_HOURS = env_int("RUNTIME_OBSERVER_RETENTION_HOURS", 168, minimum=24)
MODE = os.getenv("RUNTIME_OBSERVER_MODE", "collect_only").strip() or "collect_only"
WA_RUNTIME_LOG = Path(os.getenv("RUNTIME_OBSERVER_WA_LOG_PATH", WA_RUNTIME_LOG_DEFAULT))
ALERT_COOLDOWN_MINUTES = env_int("RUNTIME_OBSERVER_ALERT_COOLDOWN_MINUTES", 30, minimum=1)
ALERT_ENABLED = MODE in {"telegram_alerts", "telegram_alerts_daily"}
ALERT_TIMEOUT_SECONDS = env_int("RUNTIME_OBSERVER_ALERT_TIMEOUT_SECONDS", 10, minimum=2)
TELEGRAM_EDIT_MIN_ATTEMPTS = env_int(
    "RUNTIME_OBSERVER_TELEGRAM_EDIT_MIN_ATTEMPTS",
    20,
    minimum=1,
)
DAILY_SUMMARY_ENABLED = MODE in {"telegram_daily_summary", "telegram_alerts_daily"}
DAILY_SUMMARY_WINDOW_HOURS = env_int("RUNTIME_OBSERVER_DAILY_SUMMARY_WINDOW_HOURS", 24, minimum=1)
DAILY_SUMMARY_HOUR_LOCAL = min(
    23,
    env_int("RUNTIME_OBSERVER_DAILY_SUMMARY_HOUR_LOCAL", 20, minimum=0),
)
DAILY_SUMMARY_MINUTE_LOCAL = min(
    59,
    env_int("RUNTIME_OBSERVER_DAILY_SUMMARY_MINUTE_LOCAL", 0, minimum=0),
)


def env_csv(name: str) -> List[str]:
    raw = os.getenv(name, "").strip()
    if not raw:
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


def alert_telegram_bot_token() -> str:
    return (
        os.getenv("RUNTIME_OBSERVER_TELEGRAM_BOT_TOKEN", "").strip()
        or os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    )


def alert_telegram_chat_ids() -> List[str]:
    explicit = env_csv("RUNTIME_OBSERVER_TELEGRAM_CHAT_IDS")
    if explicit:
        return explicit
    return env_csv("TELEGRAM_ALLOWED_CHAT_IDS")


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def to_local(dt: datetime) -> datetime:
    return dt.astimezone(ZoneInfo(TZ_NAME))


def iso_local(dt: datetime) -> str:
    return to_local(dt).isoformat()


def since_arg(dt: datetime) -> str:
    return f"@{int(dt.timestamp())}"


def run_command(args: List[str]) -> str:
    proc = subprocess.run(args, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        stderr = proc.stderr.strip()
        raise RuntimeError(f"command failed ({' '.join(args)}): {stderr}")
    return proc.stdout


def parse_key_value(text: str) -> Dict[str, str]:
    result: Dict[str, str] = {}
    for raw in text.splitlines():
        if "=" not in raw:
            continue
        key, value = raw.split("=", 1)
        result[key.strip()] = value.strip()
    return result


def parse_json_lines(text: str) -> Iterable[Dict[str, object]]:
    for raw in text.splitlines():
        line = raw.strip()
        if not line or not line.startswith("{"):
            continue
        try:
            decoded = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(decoded, dict):
            yield decoded


def safe_int(value: object, default: int = 0) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def pick_worst_severity(levels: Iterable[str]) -> str:
    worst = "ok"
    worst_score = SEVERITY_ORDER[worst]
    for level in levels:
        score = SEVERITY_ORDER.get(level, SEVERITY_ORDER["unknown"])
        if score > worst_score:
            worst = level if level in SEVERITY_ORDER else "unknown"
            worst_score = score
    return worst


@dataclass(frozen=True)
class Threshold:
    warn: float
    critical: float

    def classify(self, value: float) -> str:
        if value >= self.critical:
            return "critical"
        if value >= self.warn:
            return "warn"
        return "ok"


def read_uptime_monotonic_seconds() -> float:
    with open("/proc/uptime", "r", encoding="utf-8") as handle:
        text = handle.read().strip().split()
    if not text:
        return 0.0
    try:
        return float(text[0])
    except ValueError:
        return 0.0


def collect_service_states() -> Tuple[Dict[str, Dict[str, object]], List[str]]:
    warnings: List[str] = []
    uptime_us = int(read_uptime_monotonic_seconds() * 1_000_000)
    states: Dict[str, Dict[str, object]] = {}
    for service in CORE_SERVICES:
        try:
            raw = run_command(
                [
                    "systemctl",
                    "show",
                    service,
                    "-p",
                    "ActiveState",
                    "-p",
                    "SubState",
                    "-p",
                    "StateChangeTimestampMonotonic",
                    "-p",
                    "NRestarts",
                    "--no-pager",
                ]
            )
            fields = parse_key_value(raw)
            active_state = fields.get("ActiveState", "unknown")
            state_change_us = safe_int(fields.get("StateChangeTimestampMonotonic"), default=0)
            down_seconds = 0.0
            if active_state != "active" and uptime_us > 0 and state_change_us > 0:
                down_seconds = max(0.0, (uptime_us - state_change_us) / 1_000_000.0)
            states[service] = {
                "active_state": active_state,
                "sub_state": fields.get("SubState", ""),
                "active": active_state == "active",
                "down_seconds": round(down_seconds, 3),
                "nrestarts_total": safe_int(fields.get("NRestarts"), default=0),
            }
        except Exception as exc:  # pragma: no cover - operational fallback
            warnings.append(f"service-state-unavailable:{service}:{exc}")
            states[service] = {
                "active_state": "unknown",
                "sub_state": "unknown",
                "active": False,
                "down_seconds": None,
                "nrestarts_total": None,
            }
    return states, warnings


def count_systemd_starts(service: str, since_dt: datetime) -> int:
    raw = run_command(
        [
            "journalctl",
            "-u",
            service,
            "--since",
            since_arg(since_dt),
            "--no-pager",
            "-q",
            "-o",
            "json",
        ]
    )
    count = 0
    for row in parse_json_lines(raw):
        if row.get("MESSAGE_ID") != SYSTEMD_STARTED_MESSAGE_ID:
            continue
        if row.get("UNIT") != service:
            continue
        count += 1
    return count


def load_telegram_events(since_dt: datetime) -> List[Dict[str, object]]:
    raw = run_command(
        [
            "journalctl",
            "-u",
            TELEGRAM_UNIT,
            "--since",
            since_arg(since_dt),
            "--no-pager",
            "-q",
            "-o",
            "cat",
        ]
    )
    events: List[Dict[str, object]] = []
    for row in parse_json_lines(raw):
        if isinstance(row.get("event"), str):
            events.append(row)
    return events


def count_wa_reconnects(since_dt: datetime, path: Path) -> int:
    if not path.exists():
        return 0
    since_ms = int(since_dt.timestamp() * 1000)
    count = 0
    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        for raw in handle:
            line = raw.strip()
            if not line.startswith("{"):
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(record, dict):
                continue
            ts_ms = safe_int(record.get("time"), default=0)
            if ts_ms < since_ms:
                continue
            if record.get("msg") != "whatsapp connection closed":
                continue
            if record.get("shouldReconnect") is False:
                continue
            count += 1
    return count


def build_snapshot(now_dt: datetime) -> Dict[str, object]:
    warnings: List[str] = []
    states, state_warnings = collect_service_states()
    warnings.extend(state_warnings)

    active_count = sum(1 for row in states.values() if bool(row.get("active")))
    service_total = len(CORE_SERVICES)
    service_percent = (active_count / service_total) * 100 if service_total else 0.0
    down_over_60 = [
        name
        for name, row in states.items()
        if row.get("active") is False and isinstance(row.get("down_seconds"), (int, float)) and row.get("down_seconds", 0) > 60  # type: ignore[arg-type]
    ]
    if down_over_60:
        service_severity = "critical"
    elif active_count < service_total:
        service_severity = "warn"
    else:
        service_severity = "ok"
    service_kpi = {
        "severity": service_severity,
        "value_percent": round(service_percent, 3),
        "target_percent": 100.0,
        "window": "instant",
        "active_services": active_count,
        "total_services": service_total,
        "down_over_60s": down_over_60,
        "services": states,
    }

    restart_since = now_dt - timedelta(hours=1)
    restarts_per_service: Dict[str, int] = {}
    for service in CORE_SERVICES:
        try:
            restarts_per_service[service] = count_systemd_starts(service, restart_since)
        except Exception as exc:  # pragma: no cover - operational fallback
            warnings.append(f"restart-count-unavailable:{service}:{exc}")
            restarts_per_service[service] = -1

    restart_warn = Threshold(warn=2.0, critical=5.0)
    restart_levels: List[str] = []
    for count in restarts_per_service.values():
        if count < 0:
            restart_levels.append("unknown")
            continue
        restart_levels.append(restart_warn.classify(float(count)))
    restart_kpi = {
        "severity": pick_worst_severity(restart_levels),
        "window": "1h",
        "warn_threshold": 2,
        "critical_threshold": 5,
        "max_restarts_per_service_last_hour": max(
            (count for count in restarts_per_service.values() if count >= 0),
            default=0,
        ),
        "restarts_last_hour": restarts_per_service,
    }

    telegram_since = now_dt - timedelta(minutes=15)
    telegram_events: List[Dict[str, object]] = []
    try:
        telegram_events = load_telegram_events(telegram_since)
    except Exception as exc:  # pragma: no cover - operational fallback
        warnings.append(f"telegram-events-unavailable:{exc}")

    retry_count = sum(
        1
        for row in telegram_events
        if row.get("event") == "bridge.telegram_api_retry_scheduled"
    )
    retry_threshold = Threshold(warn=6.0, critical=15.0)
    telegram_retry_kpi = {
        "severity": retry_threshold.classify(float(retry_count)),
        "window": "15m",
        "warn_threshold": 6,
        "critical_threshold": 15,
        "count_last_15m": retry_count,
    }

    edit_attempts = 0
    benign_edit_400_count = 0
    for row in telegram_events:
        if row.get("event") != "bridge.progress_edit_stats":
            continue
        edit_attempts += max(0, safe_int(row.get("edit_attempts"), default=0))
        benign_edit_400_count += max(
            0, safe_int(row.get("edit_failures_400"), default=0)
        )
    raw_edit_400_count = sum(
        1
        for row in telegram_events
        if row.get("event") == "bridge.telegram_api_failed"
        and row.get("method") == "editMessageText"
        and safe_int(row.get("error_code"), default=-1) == 400
    )
    edit_400_count = max(0, raw_edit_400_count - benign_edit_400_count)
    edit_rate: Optional[float]
    sample_size_suppressed = False
    if edit_attempts > 0:
        edit_rate = (edit_400_count / edit_attempts) * 100.0
        if edit_attempts >= TELEGRAM_EDIT_MIN_ATTEMPTS:
            edit_severity = Threshold(warn=3.0, critical=8.0).classify(edit_rate)
        else:
            # Keep low-volume 400s visible in status output but suppress paging
            # until we have enough edit attempts for a reliable signal.
            edit_severity = "ok"
            sample_size_suppressed = True
    elif edit_400_count > 0:
        edit_rate = None
        edit_severity = "warn"
        warnings.append("telegram-edit-rate-denominator-missing")
    else:
        edit_rate = 0.0
        edit_severity = "ok"
    telegram_edit_kpi = {
        "severity": edit_severity,
        "window": "15m",
        "warn_threshold_percent": 3.0,
        "critical_threshold_percent": 8.0,
        "min_attempts_threshold": TELEGRAM_EDIT_MIN_ATTEMPTS,
        "raw_edit_400_count": raw_edit_400_count,
        "benign_edit_400_count": benign_edit_400_count,
        "edit_400_count": edit_400_count,
        "edit_attempts": edit_attempts,
        "sample_size_suppressed": sample_size_suppressed,
        "rate_percent": round(edit_rate, 3) if isinstance(edit_rate, float) else None,
    }

    request_success = sum(
        1 for row in telegram_events if row.get("event") == "bridge.request_succeeded"
    )
    request_failed = sum(
        1
        for row in telegram_events
        if row.get("event")
        in {
            "bridge.request_failed",
            "bridge.request_timeout",
            "bridge.executor_missing",
            "bridge.request_worker_exception",
        }
    )
    request_total = request_success + request_failed
    if request_total > 0:
        request_fail_rate = (request_failed / request_total) * 100.0
    else:
        request_fail_rate = 0.0
    request_kpi = {
        "severity": Threshold(warn=1.0, critical=3.0).classify(request_fail_rate),
        "window": "15m",
        "warn_threshold_percent": 1.0,
        "critical_threshold_percent": 3.0,
        "failed": request_failed,
        "total": request_total,
        "rate_percent": round(request_fail_rate, 3),
    }

    wa_since = now_dt - timedelta(hours=1)
    wa_reconnects = 0
    try:
        wa_reconnects = count_wa_reconnects(wa_since, WA_RUNTIME_LOG)
    except Exception as exc:  # pragma: no cover - operational fallback
        warnings.append(f"wa-reconnect-unavailable:{exc}")
        wa_reconnects = -1
    if wa_reconnects < 0:
        wa_severity = "unknown"
    else:
        wa_severity = Threshold(warn=4.0, critical=10.0).classify(float(wa_reconnects))
    wa_kpi = {
        "severity": wa_severity,
        "window": "1h",
        "warn_threshold": 4,
        "critical_threshold": 10,
        "count_last_hour": wa_reconnects,
        "log_path": str(WA_RUNTIME_LOG),
    }

    return {
        "observed_at_utc": now_dt.isoformat(),
        "observed_at_local": iso_local(now_dt),
        "timezone": TZ_NAME,
        "mode": MODE,
        "kpis": {
            "service_up": service_kpi,
            "restart_count": restart_kpi,
            "telegram_retry_rate": telegram_retry_kpi,
            "telegram_edit_400_rate": telegram_edit_kpi,
            "wa_reconnect_rate": wa_kpi,
            "request_fail_rate": request_kpi,
        },
        "warnings": sorted(set(warnings)),
    }


def ensure_state_dir() -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)


def parse_snapshot_ts(snapshot: Dict[str, object]) -> Optional[datetime]:
    raw = snapshot.get("observed_at_utc")
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def load_snapshots() -> List[Dict[str, object]]:
    if not SNAPSHOT_PATH.exists():
        return []
    snapshots: List[Dict[str, object]] = []
    with open(SNAPSHOT_PATH, "r", encoding="utf-8") as handle:
        for raw in handle:
            line = raw.strip()
            if not line:
                continue
            try:
                decoded = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(decoded, dict):
                snapshots.append(decoded)
    return snapshots


def save_snapshots(snapshots: List[Dict[str, object]]) -> None:
    ensure_state_dir()
    temp_path = SNAPSHOT_PATH.with_suffix(".jsonl.tmp")
    with open(temp_path, "w", encoding="utf-8") as handle:
        for row in snapshots:
            handle.write(json.dumps(row, sort_keys=True, ensure_ascii=True))
            handle.write("\n")
    temp_path.replace(SNAPSHOT_PATH)


def append_snapshot(snapshot: Dict[str, object]) -> None:
    now_dt = now_utc()
    cutoff = now_dt - timedelta(hours=RETENTION_HOURS)
    kept: List[Dict[str, object]] = []
    for row in load_snapshots():
        ts = parse_snapshot_ts(row)
        if ts is None or ts < cutoff:
            continue
        kept.append(row)
    kept.append(snapshot)
    save_snapshots(kept)


def load_alert_state() -> Dict[str, object]:
    if not ALERT_STATE_PATH.exists():
        return {}
    try:
        with open(ALERT_STATE_PATH, "r", encoding="utf-8") as handle:
            decoded = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(decoded, dict):
        return {}
    return decoded


def save_alert_state(state: Dict[str, object]) -> None:
    ensure_state_dir()
    temp_path = ALERT_STATE_PATH.with_suffix(".json.tmp")
    with open(temp_path, "w", encoding="utf-8") as handle:
        json.dump(state, handle, sort_keys=True, ensure_ascii=True, indent=2)
        handle.write("\n")
    temp_path.replace(ALERT_STATE_PATH)


def parse_iso_utc(raw: object) -> Optional[datetime]:
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def kpi_alert_rows(snapshot: Dict[str, object]) -> List[Tuple[str, Dict[str, object]]]:
    kpis = snapshot.get("kpis")
    if not isinstance(kpis, dict):
        return []
    service_metric = kpis.get("service_up")
    service_degraded = False
    if isinstance(service_metric, dict):
        service_degraded = service_metric.get("severity") in {"warn", "critical", "unknown"}
    rows: List[Tuple[str, Dict[str, object]]] = []
    for name, metric in kpis.items():
        if not isinstance(name, str) or not isinstance(metric, dict):
            continue
        severity = metric.get("severity")
        if severity not in {"warn", "critical"}:
            continue
        # Restart-count alone becomes historical residue after a service recovers.
        # Alert on it only while there is also a live availability degradation.
        if name == "restart_count" and not service_degraded:
            continue
        rows.append((name, metric))
    rows.sort(key=lambda row: row[0])
    return rows


def alert_signature(rows: List[Tuple[str, Dict[str, object]]]) -> str:
    if not rows:
        return ""
    return "|".join(f"{name}:{metric.get('severity', 'unknown')}" for name, metric in rows)


def format_kpi_alert_line(name: str, metric: Dict[str, object]) -> str:
    severity = str(metric.get("severity", "unknown"))
    if name == "service_up":
        active = metric.get("active_services", "-")
        total = metric.get("total_services", "-")
        down = metric.get("down_over_60s")
        down_text = ",".join(down) if isinstance(down, list) and down else "-"
        return f"- {name}: {severity} active={active}/{total} down_over_60s={down_text}"
    if name == "restart_count":
        return (
            f"- {name}: {severity} max_per_service_last_hour="
            f"{metric.get('max_restarts_per_service_last_hour', '-')}"
        )
    if name == "telegram_retry_rate":
        return f"- {name}: {severity} count_last_15m={metric.get('count_last_15m', '-')}"
    if name == "telegram_edit_400_rate":
        suppressed = bool(metric.get("sample_size_suppressed", False))
        suppressed_suffix = " (suppressed:low_sample)" if suppressed else ""
        return (
            f"- {name}: {severity} rate={format_percent(metric.get('rate_percent'))} "
            f"edit_400={metric.get('edit_400_count', '-')} attempts={metric.get('edit_attempts', '-')}"
            f" min_attempts={metric.get('min_attempts_threshold', '-')}{suppressed_suffix}"
        )
    if name == "wa_reconnect_rate":
        return f"- {name}: {severity} count_last_hour={metric.get('count_last_hour', '-')}"
    if name == "request_fail_rate":
        return (
            f"- {name}: {severity} rate={format_percent(metric.get('rate_percent'))} "
            f"failed={metric.get('failed', '-')} total={metric.get('total', '-')}"
        )
    return f"- {name}: {severity}"


def format_alert_message(snapshot: Dict[str, object], rows: List[Tuple[str, Dict[str, object]]]) -> str:
    observed_local = snapshot.get("observed_at_local", "-")
    host = os.uname().nodename
    highest = pick_worst_severity(str(metric.get("severity", "unknown")) for _, metric in rows)
    lines = [
        f"[Server3] Runtime alert ({observed_local})",
        f"host={host} mode={MODE} highest={highest}",
    ]
    for name, metric in rows:
        lines.append(format_kpi_alert_line(name, metric))
    warnings = snapshot.get("warnings")
    if isinstance(warnings, list) and warnings:
        lines.append(f"warnings={json.dumps(warnings[:4], ensure_ascii=True)}")
    return "\n".join(lines)


def format_recovery_message(snapshot: Dict[str, object], previous_signature: str) -> str:
    observed_local = snapshot.get("observed_at_local", "-")
    host = os.uname().nodename
    lines = [
        f"[Server3] Runtime recovered ({observed_local})",
        f"host={host} mode={MODE}",
    ]
    if previous_signature:
        lines.append(f"cleared={previous_signature}")
    return "\n".join(lines)


def send_telegram_message(text: str) -> None:
    token = alert_telegram_bot_token()
    chat_ids = alert_telegram_chat_ids()
    if not token or not chat_ids:
        raise RuntimeError("missing telegram token/chat ids for runtime observer alerts")
    endpoint = f"https://api.telegram.org/bot{token}/sendMessage"
    for chat_id in chat_ids:
        payload = urllib.parse.urlencode(
            {"chat_id": chat_id, "text": text, "disable_web_page_preview": "true"}
        ).encode("utf-8")
        request = urllib.request.Request(endpoint, data=payload, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=ALERT_TIMEOUT_SECONDS) as response:
                _ = response.read()
        except urllib.error.URLError as exc:
            raise RuntimeError(f"telegram send failed for chat_id={chat_id}: {exc}") from exc


def maybe_send_alert(snapshot: Dict[str, object]) -> Tuple[bool, str]:
    rows = kpi_alert_rows(snapshot)
    state = load_alert_state()
    active = bool(state.get("active", False))
    last_signature = str(state.get("last_signature", ""))
    last_highest = str(state.get("last_highest", "ok"))
    last_sent_dt = parse_iso_utc(state.get("last_sent_utc"))
    now_dt = now_utc()
    cooldown_elapsed = True
    if isinstance(last_sent_dt, datetime):
        cooldown_elapsed = now_dt >= (last_sent_dt + timedelta(minutes=ALERT_COOLDOWN_MINUTES))

    if not rows:
        if active:
            message = format_recovery_message(snapshot, previous_signature=last_signature)
            send_telegram_message(message)
            save_alert_state(
                {
                    "active": False,
                    "last_signature": "",
                    "last_highest": "ok",
                    "last_sent_utc": now_dt.isoformat(),
                }
            )
            return True, "recovery_sent"
        return False, "no_alert"

    signature = alert_signature(rows)
    highest = pick_worst_severity(str(metric.get("severity", "unknown")) for _, metric in rows)
    severity_escalated = SEVERITY_ORDER.get(highest, SEVERITY_ORDER["unknown"]) > SEVERITY_ORDER.get(
        last_highest, SEVERITY_ORDER["ok"]
    )
    should_send = (not active) or (signature != last_signature) or severity_escalated or cooldown_elapsed
    if not should_send:
        return False, "cooldown"

    message = format_alert_message(snapshot, rows)
    send_telegram_message(message)
    save_alert_state(
        {
            "active": True,
            "last_signature": signature,
            "last_highest": highest,
            "last_sent_utc": now_dt.isoformat(),
        }
    )
    return True, "alert_sent"


def format_daily_summary_message(summary: Dict[str, object], observed_dt: datetime) -> str:
    host = os.uname().nodename
    lines = [
        f"[Server3] Daily runtime summary ({iso_local(observed_dt)})",
        f"host={host} mode={MODE} window={summary.get('hours', DAILY_SUMMARY_WINDOW_HOURS)}h",
        format_summary(summary),
    ]
    return "\n".join(lines)


def maybe_send_daily_summary(observed_dt: datetime) -> Tuple[bool, str]:
    if not DAILY_SUMMARY_ENABLED:
        return False, "daily_summary_disabled"

    local_now = to_local(observed_dt)
    local_date = local_now.date().isoformat()
    if (
        local_now.hour < DAILY_SUMMARY_HOUR_LOCAL
        or (
            local_now.hour == DAILY_SUMMARY_HOUR_LOCAL
            and local_now.minute < DAILY_SUMMARY_MINUTE_LOCAL
        )
    ):
        return False, "before_daily_summary_time"

    state = load_alert_state()
    if str(state.get("last_daily_summary_local_date", "")) == local_date:
        return False, "daily_summary_already_sent"

    summary = build_window_summary(DAILY_SUMMARY_WINDOW_HOURS)
    message = format_daily_summary_message(summary, observed_dt)
    send_telegram_message(message)

    next_state = dict(state)
    next_state["last_daily_summary_local_date"] = local_date
    next_state["last_daily_summary_sent_utc"] = observed_dt.isoformat()
    save_alert_state(next_state)
    return True, "daily_summary_sent"


def format_percent(value: Optional[float]) -> str:
    if value is None:
        return "n/a"
    return f"{value:.3f}%"


def format_status(snapshot: Dict[str, object]) -> str:
    kpis = snapshot["kpis"]
    service = kpis["service_up"]
    restart = kpis["restart_count"]
    retry = kpis["telegram_retry_rate"]
    edit = kpis["telegram_edit_400_rate"]
    wa = kpis["wa_reconnect_rate"]
    req = kpis["request_fail_rate"]
    lines = [
        f"Runtime observer status ({snapshot['observed_at_local']})",
        f"mode={snapshot['mode']} timezone={snapshot['timezone']}",
        (
            "service_up: "
            f"{service['severity']} value={format_percent(service['value_percent'])} "
            f"active={service['active_services']}/{service['total_services']} "
            f"down_over_60s={','.join(service['down_over_60s']) if service['down_over_60s'] else '-'}"
        ),
        (
            "restart_count: "
            f"{restart['severity']} max_per_service_last_hour={restart['max_restarts_per_service_last_hour']} "
            f"detail={json.dumps(restart['restarts_last_hour'], sort_keys=True)}"
        ),
        (
            "telegram_retry_rate: "
            f"{retry['severity']} count_last_15m={retry['count_last_15m']}"
        ),
        (
            "telegram_edit_400_rate: "
            f"{edit['severity']} rate={format_percent(edit['rate_percent'])} "
            f"edit_400={edit['edit_400_count']} attempts={edit['edit_attempts']} "
            f"min_attempts={edit.get('min_attempts_threshold', '-')} "
            f"suppressed={bool(edit.get('sample_size_suppressed', False))}"
        ),
        (
            "wa_reconnect_rate: "
            f"{wa['severity']} count_last_hour={wa['count_last_hour']} "
            f"log_path={wa['log_path']}"
        ),
        (
            "request_fail_rate: "
            f"{req['severity']} rate={format_percent(req['rate_percent'])} "
            f"failed={req['failed']} total={req['total']}"
        ),
    ]
    warnings = snapshot.get("warnings")
    if isinstance(warnings, list) and warnings:
        lines.append(f"warnings={json.dumps(warnings, ensure_ascii=True)}")
    return "\n".join(lines)


def summarize_values(values: List[float]) -> Dict[str, Optional[float]]:
    if not values:
        return {"min": None, "avg": None, "max": None}
    return {
        "min": min(values),
        "avg": sum(values) / len(values),
        "max": max(values),
    }


def format_triplet(stats: Dict[str, Optional[float]], suffix: str = "") -> str:
    min_value = stats.get("min")
    avg_value = stats.get("avg")
    max_value = stats.get("max")
    if min_value is None or avg_value is None or max_value is None:
        return f"n/a{suffix}"
    return f"{min_value:.3f}/{avg_value:.3f}/{max_value:.3f}{suffix}"


def format_operator_summary_line(kpis: Dict[str, Dict[str, object]]) -> str:
    def worst(name: str) -> str:
        metric = kpis.get(name, {})
        if not isinstance(metric, dict):
            return "unknown"
        value = str(metric.get("worst_severity", "unknown"))
        return value if value in SEVERITY_ORDER else "unknown"

    issues: List[str] = []
    if worst("telegram_edit_400_rate") in {"warn", "critical", "unknown"}:
        issues.append("intermittent Telegram edit-400 spikes")
    if worst("restart_count") in {"warn", "critical", "unknown"}:
        issues.append("some restarts that triggered warnings")
    if worst("telegram_retry_rate") in {"warn", "critical", "unknown"}:
        issues.append("Telegram retry spikes")
    if worst("wa_reconnect_rate") in {"warn", "critical", "unknown"}:
        issues.append("WhatsApp reconnect spikes")
    if worst("request_fail_rate") in {"warn", "critical", "unknown"}:
        issues.append("request failures")
    if worst("service_up") in {"warn", "critical", "unknown"}:
        issues.append("service availability drops")

    if not issues:
        return "Summary: system is healthy overall, and no attention is needed right now."

    high_attention = (
        worst("service_up") in {"critical", "unknown"}
        or worst("request_fail_rate") in {"critical", "unknown"}
    )
    if high_attention:
        return f"Summary: attention needed now due to {', '.join(issues)}."
    return f"Summary: system is healthy overall, but you had {', '.join(issues)}."


def build_window_summary(hours: int) -> Dict[str, object]:
    since_dt = now_utc() - timedelta(hours=hours)
    rows = [
        row
        for row in load_snapshots()
        if (ts := parse_snapshot_ts(row)) is not None and ts >= since_dt
    ]
    if not rows:
        return {
            "hours": hours,
            "timezone": TZ_NAME,
            "snapshot_count": 0,
            "message": "no snapshots available for this window",
        }

    def metric_rows(name: str) -> List[Dict[str, object]]:
        output = []
        for row in rows:
            kpis = row.get("kpis")
            if not isinstance(kpis, dict):
                continue
            metric = kpis.get(name)
            if isinstance(metric, dict):
                output.append(metric)
        return output

    service_rows = metric_rows("service_up")
    restart_rows = metric_rows("restart_count")
    retry_rows = metric_rows("telegram_retry_rate")
    edit_rows = metric_rows("telegram_edit_400_rate")
    wa_rows = metric_rows("wa_reconnect_rate")
    req_rows = metric_rows("request_fail_rate")

    service_values = [
        float(row["value_percent"])
        for row in service_rows
        if isinstance(row.get("value_percent"), (int, float))
    ]
    restart_values = [
        float(row["max_restarts_per_service_last_hour"])
        for row in restart_rows
        if isinstance(row.get("max_restarts_per_service_last_hour"), (int, float))
    ]
    retry_values = [
        float(row["count_last_15m"])
        for row in retry_rows
        if isinstance(row.get("count_last_15m"), (int, float))
    ]
    edit_values = [
        float(row["rate_percent"])
        for row in edit_rows
        if isinstance(row.get("rate_percent"), (int, float))
    ]
    wa_values = [
        float(row["count_last_hour"])
        for row in wa_rows
        if isinstance(row.get("count_last_hour"), (int, float)) and float(row["count_last_hour"]) >= 0
    ]
    req_values = [
        float(row["rate_percent"])
        for row in req_rows
        if isinstance(row.get("rate_percent"), (int, float))
    ]

    def severity_counts(metric_rows: List[Dict[str, object]]) -> Dict[str, int]:
        return {
            "warn": sum(1 for row in metric_rows if row.get("severity") == "warn"),
            "critical": sum(1 for row in metric_rows if row.get("severity") == "critical"),
            "unknown": sum(1 for row in metric_rows if row.get("severity") == "unknown"),
        }

    return {
        "hours": hours,
        "timezone": TZ_NAME,
        "snapshot_count": len(rows),
        "first_snapshot_local": rows[0].get("observed_at_local"),
        "last_snapshot_local": rows[-1].get("observed_at_local"),
        "kpis": {
            "service_up": {
                "worst_severity": pick_worst_severity(
                    row.get("severity", "unknown") for row in service_rows
                ),
                "severity_counts": severity_counts(service_rows),
                "value_percent": summarize_values(service_values),
            },
            "restart_count": {
                "worst_severity": pick_worst_severity(
                    row.get("severity", "unknown") for row in restart_rows
                ),
                "severity_counts": severity_counts(restart_rows),
                "max_restarts_per_service_last_hour": summarize_values(restart_values),
            },
            "telegram_retry_rate": {
                "worst_severity": pick_worst_severity(
                    row.get("severity", "unknown") for row in retry_rows
                ),
                "severity_counts": severity_counts(retry_rows),
                "count_last_15m": summarize_values(retry_values),
            },
            "telegram_edit_400_rate": {
                "worst_severity": pick_worst_severity(
                    row.get("severity", "unknown") for row in edit_rows
                ),
                "severity_counts": severity_counts(edit_rows),
                "rate_percent": summarize_values(edit_values),
            },
            "wa_reconnect_rate": {
                "worst_severity": pick_worst_severity(
                    row.get("severity", "unknown") for row in wa_rows
                ),
                "severity_counts": severity_counts(wa_rows),
                "count_last_hour": summarize_values(wa_values),
            },
            "request_fail_rate": {
                "worst_severity": pick_worst_severity(
                    row.get("severity", "unknown") for row in req_rows
                ),
                "severity_counts": severity_counts(req_rows),
                "rate_percent": summarize_values(req_values),
            },
        },
    }


def format_summary(summary: Dict[str, object]) -> str:
    if summary.get("snapshot_count", 0) == 0:
        return (
            "Runtime observer summary "
            f"(last {summary['hours']}h, timezone={summary['timezone']}): "
            f"{summary.get('message', 'no data')}\n"
            "Summary: no data in this window, so manual attention may be needed."
        )
    kpis = summary["kpis"]
    lines = [
        (
            "Runtime observer summary "
            f"(last {summary['hours']}h, timezone={summary['timezone']})"
        ),
        f"snapshots={summary['snapshot_count']}",
        f"window_start={summary['first_snapshot_local']}",
        f"window_end={summary['last_snapshot_local']}",
        (
            "service_up: "
            f"worst={kpis['service_up']['worst_severity']} "
            "warn/critical="
            f"{kpis['service_up']['severity_counts']['warn']}/"
            f"{kpis['service_up']['severity_counts']['critical']} "
            f"min/avg/max={format_triplet(kpis['service_up']['value_percent'], '%')}"
        ),
        (
            "restart_count: "
            f"worst={kpis['restart_count']['worst_severity']} "
            "warn/critical="
            f"{kpis['restart_count']['severity_counts']['warn']}/"
            f"{kpis['restart_count']['severity_counts']['critical']} "
            "min/avg/max="
            f"{format_triplet(kpis['restart_count']['max_restarts_per_service_last_hour'])}"
        ),
        (
            "telegram_retry_rate: "
            f"worst={kpis['telegram_retry_rate']['worst_severity']} "
            "warn/critical="
            f"{kpis['telegram_retry_rate']['severity_counts']['warn']}/"
            f"{kpis['telegram_retry_rate']['severity_counts']['critical']} "
            f"min/avg/max={format_triplet(kpis['telegram_retry_rate']['count_last_15m'])}"
        ),
        (
            "telegram_edit_400_rate: "
            f"worst={kpis['telegram_edit_400_rate']['worst_severity']} "
            "warn/critical="
            f"{kpis['telegram_edit_400_rate']['severity_counts']['warn']}/"
            f"{kpis['telegram_edit_400_rate']['severity_counts']['critical']} "
            f"min/avg/max={format_triplet(kpis['telegram_edit_400_rate']['rate_percent'], '%')}"
        ),
        (
            "wa_reconnect_rate: "
            f"worst={kpis['wa_reconnect_rate']['worst_severity']} "
            "warn/critical="
            f"{kpis['wa_reconnect_rate']['severity_counts']['warn']}/"
            f"{kpis['wa_reconnect_rate']['severity_counts']['critical']} "
            f"min/avg/max={format_triplet(kpis['wa_reconnect_rate']['count_last_hour'])}"
        ),
        (
            "request_fail_rate: "
            f"worst={kpis['request_fail_rate']['worst_severity']} "
            "warn/critical="
            f"{kpis['request_fail_rate']['severity_counts']['warn']}/"
            f"{kpis['request_fail_rate']['severity_counts']['critical']} "
            f"min/avg/max={format_triplet(kpis['request_fail_rate']['rate_percent'], '%')}"
        ),
        format_operator_summary_line(kpis),
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Server3 runtime observer")
    parser.add_argument(
        "--json",
        action="store_true",
        help="print machine-readable JSON",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("collect", help="collect a KPI snapshot and persist it")
    sub.add_parser("status", help="compute and print current KPI state")
    sub.add_parser("notify-test", help="send a runtime observer test message to configured Telegram chat(s)")
    summary = sub.add_parser("summary", help="print rolling summary from stored snapshots")
    summary.add_argument("--hours", type=int, default=24, help="window size in hours (default: 24)")

    args = parser.parse_args()
    if args.command == "collect":
        observed_dt = now_utc()
        snapshot = build_snapshot(observed_dt)
        append_snapshot(snapshot)
        if ALERT_ENABLED:
            try:
                sent, reason = maybe_send_alert(snapshot)
                if sent:
                    print(f"observer_alert={reason}")
                else:
                    print(f"observer_alert_skipped={reason}")
            except Exception as exc:
                print(f"observer_alert_error={exc}", file=sys.stderr)
        if DAILY_SUMMARY_ENABLED:
            try:
                sent, reason = maybe_send_daily_summary(observed_dt)
                if sent:
                    print(f"observer_daily_summary={reason}")
                else:
                    print(f"observer_daily_summary_skipped={reason}")
            except Exception as exc:
                print(f"observer_daily_summary_error={exc}", file=sys.stderr)
        if args.json:
            print(json.dumps(snapshot, indent=2, sort_keys=True, ensure_ascii=True))
        else:
            print(format_status(snapshot))
        return 0
    if args.command == "status":
        snapshot = build_snapshot(now_utc())
        if args.json:
            print(json.dumps(snapshot, indent=2, sort_keys=True, ensure_ascii=True))
        else:
            print(format_status(snapshot))
        return 0
    if args.command == "summary":
        hours = max(1, args.hours)
        summary_obj = build_window_summary(hours)
        if args.json:
            print(json.dumps(summary_obj, indent=2, sort_keys=True, ensure_ascii=True))
        else:
            print(format_summary(summary_obj))
        return 0
    if args.command == "notify-test":
        if not (ALERT_ENABLED or DAILY_SUMMARY_ENABLED):
            print(
                "Runtime observer Telegram notifications are disabled "
                "(set RUNTIME_OBSERVER_MODE=telegram_alerts, telegram_daily_summary, or telegram_alerts_daily)."
            )
            return 2
        text = (
            f"[Server3] Runtime observer test message ({iso_local(now_utc())})\n"
            f"host={os.uname().nodename} mode={MODE}"
        )
        send_telegram_message(text)
        print("Runtime observer test alert sent.")
        return 0

    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
