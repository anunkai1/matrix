#!/usr/bin/env python3
"""Export a browser-local Server3 control-plane snapshot for the static sketch."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import socket
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import urlparse
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_JSON_OUT = ROOT / "docs" / "server3-control-plane-data.json"
DEFAULT_JS_OUT = ROOT / "docs" / "server3-control-plane-data.js"
DEFAULT_TZ = "Australia/Brisbane"
MAX_MESSAGE_CHARS = 140
DEFAULT_AUDIT_LOG = Path("/home/architect/.local/state/server3-control-plane/audit.jsonl")
DEFAULT_BUNDLES_DIR = Path("/home/architect/.local/state/server3-control-plane/bundles")


@dataclass(frozen=True)
class CommandResult:
    stdout: str
    stderr: str
    returncode: int


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json-out", type=Path, default=DEFAULT_JSON_OUT)
    parser.add_argument("--js-out", type=Path, default=DEFAULT_JS_OUT)
    return parser.parse_args(argv)


def run_capture(command: Sequence[str]) -> CommandResult:
    attempts: List[List[str]] = [list(command)]
    if os.geteuid() != 0 and shutil.which("sudo"):
        sudo_attempt = ["sudo", "-n", *command]
        if command and command[0] == "journalctl":
            attempts = [sudo_attempt, list(command)]
        else:
            attempts.append(sudo_attempt)
    last: Optional[subprocess.CompletedProcess[str]] = None
    for attempt in attempts:
        result = subprocess.run(attempt, capture_output=True, text=True, check=False)
        if result.returncode == 0:
            return CommandResult(stdout=result.stdout, stderr=result.stderr, returncode=result.returncode)
        last = result
    if last is None:
        raise RuntimeError(f"failed to run command: {' '.join(command)}")
    return CommandResult(stdout=last.stdout, stderr=last.stderr, returncode=last.returncode)


def parse_key_value_output(text: str) -> Dict[str, str]:
    values: Dict[str, str] = {}
    for line in text.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def compact_state(active_state: str, sub_state: str) -> str:
    active = (active_state or "unknown").strip() or "unknown"
    sub = (sub_state or "unknown").strip() or "unknown"
    if active in {"active", "inactive", "failed"} and sub not in {"", "dead", "running", "exited", "waiting"}:
        return f"{active}({sub})"
    if active == "active" and sub == "waiting":
        return "active(waiting)"
    return active


def systemctl_show(unit: str, *properties: str) -> Dict[str, str]:
    command = ["systemctl", "show", unit, "--no-pager"]
    for prop in properties:
        command.extend(["-p", prop])
    result = run_capture(command)
    return parse_key_value_output(result.stdout)


def parse_runtime_status_payload() -> Dict[str, object]:
    result = run_capture(["python3", str(ROOT / "ops" / "server3_runtime_status.py"), "--json"])
    if result.returncode != 0 and not result.stdout.strip():
        raise RuntimeError(result.stderr.strip() or "runtime status command failed")
    return json.loads(result.stdout)


def load_runtime_manifest() -> Dict[str, Dict[str, object]]:
    payload = json.loads((ROOT / "infra" / "server3-runtime-manifest.json").read_text(encoding="utf-8"))
    return {runtime["name"]: runtime for runtime in payload.get("runtimes", [])}


def parse_iso_datetime(value: str) -> Optional[datetime]:
    value = value.strip()
    if not value or value in {"n/a", "0"}:
        return None
    for fmt in ("%a %Y-%m-%d %H:%M:%S %Z", "%a %Y-%m-%d %H:%M:%S %z", "%Y-%m-%d %H:%M:%S %Z", "%Y-%m-%d %H:%M:%S %z"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def local_now() -> datetime:
    return datetime.now(ZoneInfo(DEFAULT_TZ))


def audit_log_path() -> Path:
    override = os.environ.get("SERVER3_CONTROL_PLANE_AUDIT_LOG", "").strip()
    return Path(override) if override else DEFAULT_AUDIT_LOG


def bundles_dir() -> Path:
    override = os.environ.get("SERVER3_CONTROL_PLANE_BUNDLES_DIR", "").strip()
    return Path(override) if override else DEFAULT_BUNDLES_DIR


def format_local_compact(value: Optional[datetime]) -> str:
    if value is None:
        return "not scheduled"
    return value.astimezone(ZoneInfo(DEFAULT_TZ)).strftime("%d %b %H:%M")


def format_clock(value: Optional[datetime]) -> str:
    if value is None:
        return "--:--:--"
    return value.astimezone(ZoneInfo(DEFAULT_TZ)).strftime("%H:%M:%S")


def format_audit_clock(value: Optional[str]) -> str:
    dt = parse_iso_datetime(value or "")
    return format_clock(dt)


def format_audit_compact(value: Optional[str]) -> str:
    dt = parse_iso_datetime(value or "")
    if dt is None:
        return "unknown"
    return dt.astimezone(ZoneInfo(DEFAULT_TZ)).strftime("%d %b %H:%M")


def timer_snapshot(unit: str, label: str) -> Dict[str, str]:
    fields = systemctl_show(
        unit,
        "ActiveState",
        "SubState",
        "NextElapseUSecRealtime",
        "LastTriggerUSec",
        "UnitFileState",
    )
    next_dt = parse_iso_datetime(fields.get("NextElapseUSecRealtime", ""))
    last_dt = parse_iso_datetime(fields.get("LastTriggerUSec", ""))
    state = compact_state(fields.get("ActiveState", "unknown"), fields.get("SubState", "unknown"))
    return {
        "unit": unit,
        "label": label,
        "state": state,
        "next": format_local_compact(next_dt),
        "last": format_local_compact(last_dt),
        "unit_file_state": fields.get("UnitFileState", "unknown"),
    }


def latest_journal_line(unit: str) -> Tuple[Optional[datetime], str]:
    result = run_capture(["journalctl", "-u", unit, "-n", "8", "--output=json", "--no-pager", "-q"])
    rows = [row.strip() for row in result.stdout.splitlines() if row.strip()]
    if not rows:
        return None, "no recent log line"
    ignored_prefixes = (
        "pam_unix(sudo:session):",
        "session opened for user",
        "session closed for user",
    )
    for line in reversed(rows):
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        message = str(payload.get("MESSAGE") or "").strip()
        if not message:
            continue
        if str(payload.get("SYSLOG_IDENTIFIER") or "").strip() == "sudo":
            continue
        if str(payload.get("_COMM") or "").strip() == "sudo":
            continue
        lowered = message.lower()
        if any(prefix in lowered for prefix in ignored_prefixes):
            continue
        timestamp = None
        raw_us = str(payload.get("__REALTIME_TIMESTAMP") or "").strip()
        if raw_us.isdigit():
            timestamp = datetime.fromtimestamp(int(raw_us) / 1_000_000, tz=ZoneInfo("UTC"))
        return timestamp, summarize_log_message(message)
    return None, "no recent log line"


def summarize_log_message(message: str) -> str:
    text = " ".join((message or "").split())
    if not text:
        return "no recent log line"
    if text.startswith("{") and text.endswith("}"):
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, dict):
            parts: List[str] = []
            event = str(payload.get("event") or payload.get("action") or payload.get("msg") or "").strip()
            if event:
                parts.append(event)
            reason = str(payload.get("reason") or payload.get("status") or "").strip()
            if reason:
                parts.append(reason)
            method = str(payload.get("method") or payload.get("service") or "").strip()
            if method:
                parts.append(method)
            text = " | ".join(parts) or "structured runtime event"
    text = re.sub(r"\b(chat_id|message_id|snapshot_id|tab_id|uid|thread_id|ts)=[^ ,;]+", "", text)
    text = re.sub(r"\s+", " ", text).strip(" |")
    if len(text) > MAX_MESSAGE_CHARS:
        return text[:MAX_MESSAGE_CHARS].rstrip() + "..."
    return text


def action_label(action: str) -> str:
    mapping = {
        "snapshot.refresh": "snapshot refresh",
        "runtime.logs": "runtime logs",
        "runtime.restart": "runtime restart",
        "incident.bundle": "incident bundle",
    }
    return mapping.get(action, action.replace(".", " "))


def load_audit_entries(limit: int = 80) -> List[Dict[str, Any]]:
    path = audit_log_path()
    if not path.exists():
        return []
    rows = [row for row in path.read_text(encoding="utf-8").splitlines() if row.strip()]
    entries: List[Dict[str, Any]] = []
    for row in rows[-limit:]:
        try:
            payload = json.loads(row)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            entries.append(payload)
    return entries


def bundle_rows(limit: int = 4) -> List[Dict[str, str]]:
    directory = bundles_dir()
    if not directory.exists():
        return []
    files = sorted(directory.glob("incident-bundle-*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    rows: List[Dict[str, str]] = []
    for path in files[:limit]:
        stamp = datetime.fromtimestamp(path.stat().st_mtime, tz=ZoneInfo(DEFAULT_TZ))
        rows.append(
            {
                "label": path.name,
                "value": f"{stamp.strftime('%d %b %H:%M')} / {round(path.stat().st_size / 1024)} KiB",
            }
        )
    return rows


def playback_items(audit_entries: List[Dict[str, Any]], *, limit: int = 8) -> List[Dict[str, str]]:
    items: List[Dict[str, str]] = []
    for entry in reversed(audit_entries[-limit:]):
        runtime_key = str(entry.get("runtime_key") or "").strip()
        scope = str(entry.get("scope") or "board").strip()
        actor_mode = str(entry.get("actor_mode") or "system").strip()
        items.append(
            {
                "time": format_audit_clock(str(entry.get("ts") or "")),
                "title": str(entry.get("summary") or action_label(str(entry.get("action") or "operator action"))),
                "channel": runtime_key or scope,
                "statusClass": "ok" if str(entry.get("outcome") or "") == "ok" else "danger",
                "statusText": str(entry.get("outcome") or "unknown"),
                "copy": f"{action_label(str(entry.get('action') or 'operator action'))} via {actor_mode}. {str(entry.get('detail') or '').strip()}".strip(),
            }
        )
    return items


def runtime_audit_trail(runtime_key: str, audit_entries: List[Dict[str, Any]], *, limit: int = 5) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    for entry in reversed(audit_entries):
        if str(entry.get("runtime_key") or "") != runtime_key:
            continue
        rows.append(
            {
                "label": f"{format_audit_compact(str(entry.get('ts') or ''))} / {action_label(str(entry.get('action') or 'operator action'))}",
                "value": f"{str(entry.get('outcome') or 'unknown')} via {str(entry.get('actor_mode') or 'system')} | {str(entry.get('detail') or entry.get('summary') or '').strip()}",
            }
        )
        if len(rows) >= limit:
            break
    return rows


def path_disk_summary(path: Path) -> Dict[str, str]:
    if not path.exists():
        return {"path": str(path), "status": "missing", "usage": "missing"}
    usage = shutil.disk_usage(path)
    used_pct = 0 if usage.total <= 0 else round((usage.used / usage.total) * 100)
    total_gb = usage.total / (1024 ** 3)
    free_gb = usage.free / (1024 ** 3)
    host_state = f"{load_avg_summary()} / {memory_summary()}"
    return {
        "path": str(path),
        "status": "present",
        "usage": f"{used_pct}% used",
        "detail": f"{free_gb:.0f} GiB free of {total_gb:.0f} GiB",
    }


def memory_summary() -> str:
    try:
        fields: Dict[str, int] = {}
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            key, value = line.split(":", 1)
            fields[key] = int(value.strip().split()[0])
        total = fields.get("MemTotal", 0)
        available = fields.get("MemAvailable", 0)
        if total <= 0:
            return "ram unknown"
        used_pct = round(((total - available) / total) * 100)
        return f"ram {used_pct}%"
    except Exception:
        return "ram unknown"


def network_summary() -> str:
    result = run_capture(["ip", "-4", "route", "get", "1.1.1.1"])
    line = next((row.strip() for row in result.stdout.splitlines() if row.strip()), "")
    if not line:
        return "route unknown"
    parts = line.split()
    iface = parts[parts.index("dev") + 1] if "dev" in parts else "?"
    src = parts[parts.index("src") + 1] if "src" in parts else "?"
    return f"{iface} / {src}"


def load_avg_summary() -> str:
    try:
        load1, _, _ = os.getloadavg()
        return f"load {load1:.2f}"
    except OSError:
        return "load unknown"


def resolve_browser_note(runtime: Dict[str, object]) -> str:
    if runtime.get("matches_expected"):
        return "existing-session path available"
    issues = []
    for unit in runtime.get("units", []):
        issues.extend(unit.get("issues", []))
    return "; ".join(issues[:2]) or "review browser service"


def read_pending_action() -> Optional[Dict[str, object]]:
    default_db = Path("/home/mavali_eth/.local/state/telegram-mavali-eth-bridge/mavali_eth.sqlite3")
    query = """
import json, sqlite3
from pathlib import Path
db_path = Path("/home/mavali_eth/.local/state/telegram-mavali-eth-bridge/mavali_eth.sqlite3")
if not db_path.exists():
    print("null")
    raise SystemExit(0)
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row
row = conn.execute(
    "SELECT action_id, session_key, action_kind, module, summary, payload_json, created_at, expires_at "
    "FROM pending_action_envelopes ORDER BY created_at DESC LIMIT 1"
).fetchone()
if row is None:
    print("null")
else:
    payload = dict(row)
    payload["payload_json"] = json.loads(payload["payload_json"])
    print(json.dumps(payload, ensure_ascii=True))
"""
    result = run_capture(["python3", "-c", query])
    if result.returncode != 0 or not result.stdout.strip():
        return None
    value = result.stdout.strip()
    if value == "null":
        return None
    return json.loads(value)


def browser_brain_status() -> Optional[Dict[str, Any]]:
    result = run_capture(["python3", str(ROOT / "ops" / "browser_brain" / "browser_brain_ctl.py"), "status"])
    if result.returncode != 0 or not result.stdout.strip():
        return None
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def browser_brain_recent_events(limit: int = 8) -> List[Dict[str, str]]:
    result = run_capture(["journalctl", "-u", "server3-browser-brain.service", "-n", "60", "--output=json", "--no-pager", "-q"])
    rows = [row.strip() for row in result.stdout.splitlines() if row.strip()]
    events: List[Dict[str, str]] = []
    for row in reversed(rows):
        try:
            payload = json.loads(row)
        except json.JSONDecodeError:
            continue
        message = payload.get("MESSAGE")
        if not isinstance(message, str) or not message.startswith("{"):
            continue
        try:
            data = json.loads(message)
        except json.JSONDecodeError:
            continue
        action = str(data.get("action") or "").strip()
        timestamp = parse_iso_datetime(str(data.get("ts") or ""))
        if not action:
            continue
        detail_parts: List[str] = []
        if data.get("url"):
            detail_parts.append(compact_url(str(data["url"])))
        if data.get("value"):
            detail_parts.append(str(data["value"]))
        if data.get("elements"):
            detail_parts.append(f"{data['elements']} elements")
        if data.get("snapshot_id"):
            detail_parts.append(str(data["snapshot_id"]))
        events.append(
            {
                "time": format_clock(timestamp),
                "action": action,
                "tab_id": str(data.get("tab_id") or ""),
                "detail": " | ".join(detail_parts) or "browser event",
            }
        )
        if len(events) >= limit:
            break
    return events


def compact_url(url: str) -> str:
    if not url:
        return "unknown"
    if url.startswith("data:"):
        return "session tab"
    parsed = urlparse(url)
    host = parsed.netloc or url
    path = parsed.path.rstrip("/")
    if not path:
        return host
    short_path = path if len(path) <= 36 else path[:33] + "..."
    return f"{host}{short_path}"


def compact_title(title: str, *, max_chars: int = 72) -> str:
    text = " ".join((title or "").split())
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3].rstrip() + "..."


def browser_tv_window() -> Optional[str]:
    command = [
        "sudo",
        "-n",
        "-u",
        "tv",
        "bash",
        "-lc",
        "export DISPLAY=:0 XAUTHORITY=/home/tv/.Xauthority; wmctrl -lx | grep -i 'server3-browser-brain-brave-profile' || true",
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    line = next((row.strip() for row in result.stdout.splitlines() if row.strip()), "")
    if not line:
        return None
    return line.split(None, 4)[-1] if len(line.split(None, 4)) >= 5 else line


def browser_capture_rows(limit: int = 3) -> List[Tuple[str, str]]:
    capture_dir = Path("/var/lib/server3-browser-brain/captures")
    if not capture_dir.exists():
        return [("captures", "capture directory missing")]
    files = sorted(capture_dir.glob("*"), key=lambda path: path.stat().st_mtime, reverse=True)
    rows: List[Tuple[str, str]] = []
    for capture in files[:limit]:
        stamp = datetime.fromtimestamp(capture.stat().st_mtime, tz=ZoneInfo(DEFAULT_TZ))
        size_kib = round(capture.stat().st_size / 1024)
        rows.append((capture.name, f"{stamp.strftime('%d %b %H:%M')} / {size_kib} KiB"))
    if not rows:
        rows.append(("captures", "no retained captures"))
    return rows


def browser_auth_posture(tabs: List[Dict[str, Any]]) -> str:
    urls = [str(tab.get("url") or "") for tab in tabs]
    titles = [str(tab.get("title") or "") for tab in tabs]
    notes: List[str] = []
    if any(url.startswith("https://x.com/home") for url in urls):
        notes.append("x session live")
    if any("sign-in" in title.lower() or "login" in title.lower() for title in titles):
        notes.append("manual login tab open")
    if not notes:
        notes.append("no explicit auth cue")
    return "; ".join(notes[:2])


def browser_current_target(status_payload: Optional[Dict[str, Any]], recent_events: List[Dict[str, str]]) -> str:
    tabs = {str(tab.get("tab_id") or ""): tab for tab in (status_payload or {}).get("tabs", [])}
    for event in recent_events:
        tab = tabs.get(event["tab_id"])
        if tab:
            return compact_title(str(tab.get("title") or compact_url(str(tab.get("url") or ""))), max_chars=84)
    if tabs:
        first = next(iter(tabs.values()))
        return compact_title(str(first.get("title") or compact_url(str(first.get("url") or ""))), max_chars=84)
    return "no live browser target"


def browser_domain_mix(tabs: List[Dict[str, Any]]) -> str:
    hosts = [urlparse(str(tab.get("url") or "")).netloc for tab in tabs if str(tab.get("url") or "").startswith("http")]
    if not hosts:
        return "no http tabs"
    top = Counter(hosts).most_common(2)
    return ", ".join(f"{host} x{count}" for host, count in top)


def build_browser_lane() -> Dict[str, object]:
    status_payload = browser_brain_status() or {}
    tabs = list(status_payload.get("tabs") or [])
    recent_events = browser_brain_recent_events()
    tv_window = browser_tv_window()
    current_target = browser_current_target(status_payload, recent_events)
    targets: List[Tuple[str, str]] = [("current target", current_target)]
    for tab in tabs[:4]:
        targets.append((str(tab.get("tab_id") or "tab"), compact_title(str(tab.get("title") or compact_url(str(tab.get("url") or ""))), max_chars=84)))
    activity_rows: List[Tuple[str, str]] = []
    for event in recent_events[:4]:
        activity_rows.append((f"{event['time']} {event['action']}", event["detail"]))
    if not activity_rows:
        activity_rows.append(("recent activity", "no browser events surfaced"))
    return {
        "state": [
            {"label": "connection", "value": f"{status_payload.get('connection_mode', 'unknown')} / {'running' if status_payload.get('running') else 'stopped'}"},
            {"label": "auth posture", "value": browser_auth_posture(tabs)},
            {"label": "manual takeover", "value": compact_title(tv_window or "tv helper not visible", max_chars=84)},
            {"label": "tab footprint", "value": f"{len(tabs)} live tabs / {browser_domain_mix(tabs)}"},
        ],
        "targets": [{"label": label, "value": value} for label, value in targets[:5]],
        "captures": [{"label": label, "value": value} for label, value in browser_capture_rows()],
        "activity": [{"label": label, "value": value} for label, value in activity_rows],
        "summary": {
            "current_target": current_target,
            "tab_count": len(tabs),
            "auth_posture": browser_auth_posture(tabs),
            "manual_takeover": "visible tv helper open" if tv_window else "tv helper not visible",
            "capture_dir": str(status_payload.get("capture_dir") or "/var/lib/server3-browser-brain/captures"),
            "started_at": str(status_payload.get("started_at") or ""),
        },
    }


def classify_state(matches_expected: bool, live_state: str, issues: Iterable[str], *, default_ok: str = "ok") -> Tuple[str, str]:
    issue_list = [item for item in issues if item]
    lowered = live_state.lower()
    if "failed" in lowered:
        return "danger", "failed"
    if lowered.startswith("inactive"):
        return "danger", "offline"
    if issue_list or not matches_expected:
        return "danger", "degraded"
    return default_ok, "healthy"


def action_labels(name: str) -> List[str]:
    if name == "Browser Brain":
        return ["show browser lane", "show recent logs", "refresh snapshot"]
    return ["restart runtime", "show recent logs", "refresh snapshot"]


def runtime_docs(name: str) -> List[Tuple[str, str]]:
    if name == "Architect":
        return [
            ("logs", "journalctl -u telegram-architect-bridge.service"),
            ("docs", "docs/telegram-architect-bridge.md"),
            ("policy", "ARCHITECT_INSTRUCTION.md"),
        ]
    if name == "Tank":
        return [
            ("logs", "journalctl -u telegram-tank-bridge.service"),
            ("docs", "docs/runtime_docs/tank"),
            ("runbook", "ops/runtime_personas/check_runtime_repo_links.sh"),
        ]
    if name == "Diary":
        return [
            ("logs", "journalctl -u telegram-diary-bridge.service"),
            ("docs", "docs/runtime_docs/diary"),
            ("policy", "docs/runtime_docs/diary/DIARY_INSTRUCTION.md"),
        ]
    if name == "Govorun":
        return [
            ("logs", "journalctl -u whatsapp-govorun-bridge.service -u govorun-whatsapp-bridge.service"),
            ("docs", "docs/runbooks/whatsapp-govorun-operations.md"),
            ("guard", "ops/chat-routing/validate_chat_routing_contract.py"),
        ]
    if name == "Oracle":
        return [
            ("logs", "journalctl -u signal-oracle-bridge.service -u oracle-signal-bridge.service"),
            ("docs", "docs/runbooks/oracle-signal-operations.md"),
            ("voice", "ops/telegram-voice/transcribe_voice.sh"),
        ]
    if name == "Mavali ETH":
        return [
            ("logs", "journalctl -u telegram-mavali-eth-bridge.service"),
            ("docs", "docs/runbooks/mavali-eth-operations.md"),
            ("guard", "bridge-side pending-action guard"),
        ]
    return [
        ("logs", "journalctl -u server3-browser-brain.service"),
        ("summary", "SERVER3_SUMMARY.md"),
        ("policy", "existing_session is canonical"),
    ]


def build_selected_runtimes(
    runtime_status_payload: Dict[str, object],
    manifest: Dict[str, Dict[str, object]],
    pending_action: Optional[Dict[str, object]],
    audit_entries: List[Dict[str, Any]],
) -> List[Dict[str, object]]:
    runtimes = {row["name"]: row for row in runtime_status_payload.get("runtimes", [])}
    browser_lane = build_browser_lane()

    selected: List[Tuple[str, List[str], str, str]] = [
        ("architect", ["Architect"], "Telegram primary", "owner-facing runtime"),
        ("tank", ["Tank"], "Telegram sibling", "isolated Telegram runtime"),
        ("diary", ["Diary"], "capture runtime", "capture-focused sibling"),
        ("govorun", ["Govorun transport", "Govorun bridge"], "WhatsApp runtime", "dual transport + bridge"),
        ("oracle", ["Oracle transport", "Oracle bridge"], "Signal runtime", "transport + bridge"),
        ("mavali", ["Mavali ETH"], "venue operations runtime", "owner-bound wallet runtime"),
        ("browser", ["Browser brain"], "browser control surface", "existing-session browser runtime"),
    ]
    rows: List[Dict[str, object]] = []
    for key, source_names, role, operator_note in selected:
        live_rows = [runtimes[name] for name in source_names if name in runtimes]
        if not live_rows:
            continue
        issue_list: List[str] = []
        unit_names: List[str] = []
        live_states: List[str] = []
        notes: List[str] = []
        workspace_root = ""
        owner = ""
        for source_name in source_names:
            manifest_row = manifest.get(source_name, {})
            if not workspace_root:
                workspace_root = str(manifest_row.get("workspace_root") or "")
        for row in live_rows:
            live_states.append(str(row.get("live_state", "unknown")))
            unit_names.extend(unit["name"] for unit in row.get("units", []))
            owner = owner or str(row.get("owner_user") or "")
            notes.extend(str(item) for item in row.get("notes", []))
            for unit in row.get("units", []):
                issue_list.extend(str(item) for item in unit.get("issues", []))
        state_class, state_text = classify_state(
            all(bool(row.get("matches_expected")) for row in live_rows),
            " / ".join(live_states),
            issue_list,
        )
        if key == "mavali" and pending_action is not None:
            state_class, state_text = "warn", "waiting"
        elif key == "browser" and all(bool(row.get("matches_expected")) for row in live_rows):
            state_class, state_text = "busy", "attached"

        recent_jobs: List[Tuple[str, str]] = []
        watchouts: List[Tuple[str, str]] = []
        for unit_name in unit_names[:2]:
            journal_dt, message = latest_journal_line(unit_name)
            recent_jobs.append((unit_name, f"{format_clock(journal_dt)} {message}"))
        if key == "mavali" and pending_action is not None:
            recent_jobs.insert(0, ("pending action", str(pending_action.get("summary") or pending_action.get("action_kind") or "staged action")))
            watchouts.append(("approval gate", "reply path remains explicit: approve, reject, or clear the pending action"))
            watchouts.append(("infra risk", "temporary public RPC remains a live production caveat"))
        elif issue_list:
            watchouts.append(("current issue", issue_list[0]))
        else:
            watchouts.append(("current issue", "no active unit mismatch detected"))
        if notes:
            watchouts.append(("operator note", notes[0]))
        if key == "browser":
            watchouts.append(("recovery path", resolve_browser_note(live_rows[0])))
            watchouts.append(("current target", str(browser_lane["summary"]["current_target"])))
            recent_jobs = [(row["label"], row["value"]) for row in browser_lane["activity"][:3]]
        if key == "govorun":
            watchouts.append(("routing contract", "daily contract drift timer should stay green"))
        if key == "oracle":
            watchouts.append(("voice path", "keep local transcription runtime separate from transport health"))
        if key == "tank":
            watchouts.append(("identity", "preserve isolated runtime root and Joplin profile"))
        if key == "diary":
            watchouts.append(("delivery", "capture routing should stay friction-light"))
        if key == "architect":
            watchouts.append(("change control", "persistent repo edits still require commit and push proof"))

        service_stats = [
            ("unit set", ", ".join(unit_names)),
            ("workspace", workspace_root or "runtime-local"),
            ("owner", owner or "system"),
            ("live state", " / ".join(live_states)),
        ]

        rows.append(
            {
                "key": key,
                "name": "Govorun" if key == "govorun" else "Oracle" if key == "oracle" else "Browser Brain" if key == "browser" else live_rows[0]["name"],
                "stateClass": state_class,
                "stateText": state_text,
                "role": role,
                "operatorNote": operator_note,
                "summary": str(live_rows[0].get("purpose") or ""),
                "actions": action_labels("Browser Brain" if key == "browser" else "Govorun" if key == "govorun" else "Oracle" if key == "oracle" else str(live_rows[0]["name"])),
                "serviceStats": [{"label": label, "value": value} for label, value in service_stats],
                "recentJobs": [{"label": label, "value": value} for label, value in recent_jobs[:3]],
                "watchouts": [{"label": label, "value": value} for label, value in watchouts[:3]],
                "docsAndLogs": [{"label": label, "value": value} for label, value in runtime_docs("Browser Brain" if key == "browser" else "Govorun" if key == "govorun" else "Oracle" if key == "oracle" else str(live_rows[0]["name"]))],
                "unitNames": unit_names,
                "auditTrail": runtime_audit_trail(key, audit_entries),
                "browserLane": browser_lane if key == "browser" else None,
            }
        )
    return rows


def build_approvals(pending_action: Optional[Dict[str, object]], ui_layer_issue: Optional[str]) -> List[Dict[str, str]]:
    items: List[Dict[str, str]] = []
    if pending_action is not None:
        payload = pending_action.get("payload_json") or {}
        detail = []
        for key in ("submission_state", "symbol", "side", "quantity_display", "price_display", "amount_display"):
            value = payload.get(key)
            if value:
                detail.append(f"{key}={value}")
        body = str(pending_action.get("summary") or pending_action.get("action_kind") or "pending action")
        if detail:
            body += ". " + ", ".join(detail[:4])
        items.append(
            {
                "title": "Mavali ETH staged action",
                "riskClass": "warn",
                "riskText": "high risk",
                "body": body,
                "approveLabel": "approve exact action",
                "rejectLabel": "clear pending",
            }
        )
    if ui_layer_issue:
        items.append(
            {
                "title": "UI layer is active outside its default posture",
                "riskClass": "danger",
                "riskText": "operator review",
                "body": ui_layer_issue,
                "approveLabel": "accept for session",
                "rejectLabel": "turn desktop off",
            }
        )
    return items


def build_jobs(timers: List[Dict[str, str]], approvals: List[Dict[str, str]]) -> List[Dict[str, str]]:
    items: List[Dict[str, str]] = []
    for timer in timers:
        tag_class = "busy" if timer["state"].startswith("active") else "danger"
        items.append(
            {
                "title": timer["label"],
                "tagClass": tag_class,
                "tagText": timer["next"],
                "body": f"{timer['unit']} is {timer['state']}. Last trigger: {timer['last']}.",
            }
        )
    if approvals:
        items.insert(
            0,
            {
                "title": "Approval queue",
                "tagClass": "warn",
                "tagText": f"{len(approvals)} waiting",
                "body": "Pending actions are rendered here as operator work, not buried in prompt text.",
            },
        )
    return items[:5]


def build_playback(audit_entries: List[Dict[str, Any]]) -> Dict[str, object]:
    items = playback_items(audit_entries)
    bundles = bundle_rows()
    last_entry = audit_entries[-1] if audit_entries else {}
    return {
        "items": items,
        "meta": [
            {"label": "recent operator actions", "value": str(len(items))},
            {"label": "last actor path", "value": str(last_entry.get("actor_mode") or "none yet")},
            {"label": "last action", "value": action_label(str(last_entry.get("action") or "none yet"))},
            {"label": "captured bundles", "value": str(len(bundles))},
        ],
        "bundles": bundles,
    }


def build_activity(
    selected_runtimes: List[Dict[str, object]],
    approvals: List[Dict[str, str]],
    timers: List[Dict[str, str]],
    ui_layer_issue: Optional[str],
) -> List[Dict[str, str]]:
    entries: List[Tuple[Optional[datetime], Dict[str, str]]] = []
    for runtime in selected_runtimes:
        unit_name = str(runtime["unitNames"][0])
        journal_dt, message = latest_journal_line(unit_name)
        if runtime["name"] == "Browser Brain" and runtime.get("browserLane"):
            summary = runtime["browserLane"].get("summary", {})
            message = f"{summary.get('current_target', 'browser target unknown')} | {summary.get('auth_posture', 'auth posture unknown')}"
        entries.append(
            (
                journal_dt,
                {
                    "time": format_clock(journal_dt),
                    "title": f"{runtime['name']} recent service activity",
                    "channel": runtime["role"].lower(),
                    "statusClass": str(runtime["stateClass"]),
                    "statusText": str(runtime["stateText"]),
                    "copy": message,
                },
            )
        )
    if approvals:
        entries.append(
            (
                local_now(),
                {
                    "time": local_now().strftime("%H:%M:%S"),
                    "title": approvals[0]["title"],
                    "channel": "approval",
                    "statusClass": approvals[0]["riskClass"],
                    "statusText": approvals[0]["riskText"],
                    "copy": approvals[0]["body"],
                },
            )
        )
    if ui_layer_issue:
        entries.append(
            (
                local_now(),
                {
                    "time": local_now().strftime("%H:%M:%S"),
                    "title": "Optional UI layer is active",
                    "channel": "host",
                    "statusClass": "danger",
                    "statusText": "watch",
                    "copy": ui_layer_issue,
                },
            )
        )
    for timer in timers[:2]:
        entries.append(
            (
                None,
                {
                    "time": timer["next"],
                    "title": timer["label"],
                    "channel": "timer",
                    "statusClass": "busy",
                    "statusText": timer["state"],
                    "copy": f"Next run {timer['next']} | last trigger {timer['last']}",
                },
            )
        )
    entries.sort(key=lambda item: item[0] or datetime.min.replace(tzinfo=ZoneInfo(DEFAULT_TZ)), reverse=True)
    return [payload for _, payload in entries[:6]]


def build_overview(summary_counts: Dict[str, int], approvals: List[Dict[str, str]], ui_layer_issue: Optional[str]) -> Tuple[List[Dict[str, str]], List[Dict[str, str]]]:
    bands = [
        {
            "title": "Nominal lane",
            "stateClass": "ok",
            "stateText": "healthy",
            "body": f"{summary_counts['healthy']} selected runtimes match expected live posture.",
        },
        {
            "title": "Approval lane",
            "stateClass": "warn" if approvals else "ok",
            "stateText": "approval" if approvals else "clear",
            "body": f"{len(approvals)} operator approval item(s) currently surfaced.",
        },
        {
            "title": "Watch lane",
            "stateClass": "danger" if ui_layer_issue else "ok",
            "stateText": "watch" if ui_layer_issue else "clear",
            "body": ui_layer_issue or "No selected runtime is currently off its default expected posture.",
        },
        {
            "title": "Offline lane",
            "stateClass": "danger" if summary_counts["offline"] else "ok",
            "stateText": "offline" if summary_counts["offline"] else "none",
            "body": f"{summary_counts['offline']} selected runtime(s) are currently offline.",
        },
    ]
    side = [
        {"label": "service footprint", "value": str(summary_counts["tracked"]), "copy": "selected runtimes in the operator rail"},
        {"label": "operator gates", "value": str(len(approvals)), "copy": "explicit human approvals, not implicit risk"},
    ]
    return bands, side


def build_floor(timers: List[Dict[str, str]]) -> List[Dict[str, str]]:
    root_disk = path_disk_summary(Path("/"))
    arr_disk = path_disk_summary(Path("/srv/external/server3-arr"))
    backup_disk = path_disk_summary(Path("/srv/external/server3-backups"))
    data_disk = path_disk_summary(Path("/data/downloads"))
    host_state = f"{load_avg_summary()} / {memory_summary()}"
    return [
        {
            "title": "Internal disk",
            "stateClass": "ok",
            "stateText": "nominal",
            "value": root_disk.get("usage", "unknown"),
            "body": f"{root_disk['path']} | {root_disk.get('detail', 'path unavailable')}",
            "statusLine": "system root filesystem",
        },
        {
            "title": "External disk",
            "stateClass": "warn",
            "stateText": "watch",
            "value": arr_disk.get("usage", "unknown"),
            "body": f"{arr_disk['path']} | {arr_disk.get('detail', 'path unavailable')}",
            "statusLine": f"backup disk: {backup_disk.get('usage', 'unknown')}",
        },
        {
            "title": "Host health",
            "stateClass": "ok",
            "stateText": "nominal",
            "value": host_state,
            "body": f"primary route {network_summary()}",
            "statusLine": f"host: {socket.gethostname()}",
        },
        {
            "title": "Key paths",
            "stateClass": "busy",
            "stateText": "live",
            "value": data_disk["path"],
            "body": f"{data_disk.get('usage', 'unknown')} | {data_disk.get('detail', 'path unavailable')}",
            "statusLine": "canonical media namespace is /data/downloads and /data/media/...",
        },
        {
            "title": "Schedules",
            "stateClass": "busy",
            "stateText": "queued",
            "value": ", ".join(timer["label"] for timer in timers[:3]),
            "body": "Visible timers stay on the floor so continuity work is never hidden behind another tool.",
            "statusLine": f"next: {timers[0]['next']}" if timers else "next: unknown",
        },
    ]


def build_snapshot() -> Dict[str, object]:
    runtime_status_payload = parse_runtime_status_payload()
    manifest = load_runtime_manifest()
    pending_action = read_pending_action()
    audit_entries = load_audit_entries()
    selected_runtimes = build_selected_runtimes(runtime_status_payload, manifest, pending_action, audit_entries)
    ui_layer = next((row for row in runtime_status_payload.get("runtimes", []) if row.get("name") == "UI layer"), None)
    ui_layer_issue = None
    if ui_layer and not ui_layer.get("matches_expected"):
        issues = []
        for unit in ui_layer.get("units", []):
            issues.extend(unit.get("issues", []))
        ui_layer_issue = issues[0] if issues else "UI layer is active while its default posture expects inactivity."
    approvals = build_approvals(pending_action, ui_layer_issue)
    timers = [
        timer_snapshot("server3-runtime-observer.timer", "Observer summary"),
        timer_snapshot("server3-chat-routing-contract-check.timer", "Routing drift check"),
        timer_snapshot("server3-state-backup.timer", "State backup"),
        timer_snapshot("mavali-eth-receipt-monitor.timer", "Receipt monitor"),
    ]
    summary_counts = {
        "tracked": len(selected_runtimes),
        "healthy": sum(1 for runtime in selected_runtimes if runtime["stateText"] in {"healthy", "attached"}),
        "busy": sum(1 for runtime in selected_runtimes if runtime["stateText"] in {"busy", "attached"}),
        "waiting": sum(1 for runtime in selected_runtimes if runtime["stateText"] == "waiting"),
        "degraded": sum(1 for runtime in selected_runtimes if runtime["stateText"] == "degraded"),
        "offline": sum(1 for runtime in selected_runtimes if runtime["stateText"] == "offline"),
    }
    overview_bands, overview_side = build_overview(summary_counts, approvals, ui_layer_issue)
    playback = build_playback(audit_entries)
    generated_at = parse_iso_datetime(str(runtime_status_payload.get("generated_at", ""))) or local_now()
    host_state = f"{load_avg_summary()} / {memory_summary()}"
    return {
        "generatedAt": generated_at.isoformat(),
        "timezone": DEFAULT_TZ,
        "defaultRuntime": "architect",
        "summary": {
            "runtimeValue": f"{summary_counts['tracked']} live",
            "runtimeCopy": (
                f"{summary_counts['healthy']} healthy, {summary_counts['degraded']} degraded, "
                f"{summary_counts['waiting']} waiting, {summary_counts['offline']} offline"
            ),
            "approvalValue": f"{len(approvals)} pending",
            "approvalCopy": "explicit human gates from live Server3 state",
            "jobValue": f"{len(timers) + len(approvals) + len(playback['items'])} tracked",
            "jobCopy": "timers, approvals, and operator playback in one surface",
            "hostValue": host_state,
            "hostCopy": "browser, timers, storage, and network summarized from the host",
            "currentPicture": [
                generated_at.astimezone(ZoneInfo(DEFAULT_TZ)).strftime("%d %b %Y %H:%M AEST"),
                f"snapshot file {DEFAULT_JS_OUT.name}",
                f"{len(approvals)} approval item(s)",
            ],
            "surfaceBias": [
                "read-only live snapshot",
                "browser-local file:// compatible",
                "state color only",
            ],
            "chips": [
                {"tone": "ok", "label": "live status loaded"},
                {"tone": "busy", "label": timers[0]["label"].lower()},
                {"tone": "warn", "label": f"{len(approvals)} approval item(s)"},
                {"tone": "busy", "label": f"{len(playback['items'])} operator actions"},
                {"tone": "danger", "label": "storage remains continuity sensitive"},
            ],
        },
        "overview": {
            "bands": overview_bands,
            "side": overview_side,
        },
        "activity": build_activity(selected_runtimes, approvals, timers, ui_layer_issue),
        "playback": playback,
        "approvals": approvals,
        "jobs": build_jobs(timers, approvals),
        "floor": build_floor(timers),
        "runtimes": selected_runtimes,
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    snapshot = build_snapshot()
    args.json_out.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    args.js_out.write_text(
        "window.SERVER3_CONTROL_PLANE_DATA = " + json.dumps(snapshot, indent=2, ensure_ascii=False) + ";\n",
        encoding="utf-8",
    )
    print(json.dumps({"json_out": str(args.json_out), "js_out": str(args.js_out)}, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
