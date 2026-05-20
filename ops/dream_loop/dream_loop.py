#!/usr/bin/env python3
"""Bounded v1 Server3 dream-loop runner.

This runner keeps the first slice narrow:
- scan a fixed set of truth and health inputs
- normalize them into machine-readable truth/health/run state
- write the three v1 state artifacts plus a conservative report
- support dry-run and manual invocation

It does not send chat notifications, expose bridge commands, or push commits.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from telegram_bridge.dream_loop_state import (
    LATEST_HEALTH_STATE,
    LATEST_REPORT,
    LATEST_RUN_STATE,
    LATEST_TRUTH_STATE,
    apply_stale_context_updates,
    build_stale_context_state_path,
    load_stale_context_statuses,
    persist_stale_context_statuses,
    snapshot_stale_context_statuses,
)


DEFAULT_STATE_DIR = Path(os.getenv("DREAM_LOOP_STATE_DIR", "/var/lib/server3-dream-loop"))
DEFAULT_BRIDGE_STATE_DIR = Path(
    os.getenv("DREAM_LOOP_ARCHITECT_BRIDGE_STATE_DIR", "/home/architect/.local/state/telegram-architect-bridge")
)
DEFAULT_TZ = os.getenv("DREAM_LOOP_TZ", "Australia/Brisbane")
RECENT_ACTIVITY_DAYS = 7

TRUTH_INPUT_PATHS = (
    ROOT / "ARCHITECT_INSTRUCTION.md",
    ROOT / "LESSONS.md",
    ROOT / "infra" / "server3-runtime-manifest.json",
)
POLICY_INPUT_PATHS = (
    ROOT / "src" / "telegram_bridge" / "runtime_config.py",
    ROOT / "src" / "telegram_bridge" / "session_manager.py",
    ROOT / "src" / "telegram_bridge" / "bridge_runtime_setup.py",
)
TELEGRAM_CONTEXT_ROUTING_INPUT_PATHS = (
    ROOT / "src" / "telegram_bridge" / "message_inputs.py",
    ROOT / "src" / "telegram_bridge" / "session_manager.py",
)

DEFAULT_SUMMARY_PATH = ROOT / "SERVER3_SUMMARY.md"


@dataclass(frozen=True)
class DreamLoopConfig:
    state_dir: Path = DEFAULT_STATE_DIR
    bridge_state_dir: Path = DEFAULT_BRIDGE_STATE_DIR
    timezone: str = DEFAULT_TZ
    dry_run: bool = False
    summary_path: Path = DEFAULT_SUMMARY_PATH


@dataclass(frozen=True)
class DreamLoopCheckSpec:
    check_id: str
    truth_area: str
    mode: str
    trigger: str
    inputs: Tuple[str, ...]
    executor: str
    mismatch_rule: str
    correction_target: str
    severity: str


@dataclass
class DreamLoopExecutionContext:
    config: DreamLoopConfig
    generated_at: str
    run_started_at: datetime
    previous_truth_state: Dict[str, Any]
    run_json_command: Callable[[Sequence[str]], Dict[str, Any]]
    run_text_command: Callable[[Sequence[str]], str]
    checks_executed: List[str] = field(default_factory=list)
    skipped_checks: List[Dict[str, str]] = field(default_factory=list)
    unresolved_items: List[str] = field(default_factory=list)
    warnings_emitted: List[str] = field(default_factory=list)
    files_updated: List[str] = field(default_factory=list)
    truth_state: Dict[str, Any] = field(default_factory=dict)
    health_state: Dict[str, Any] = field(default_factory=dict)
    registry_check_results: List[Dict[str, Any]] = field(default_factory=list)
    truth_entries: List[Dict[str, Any]] = field(default_factory=list)
    policy_entries: List[Dict[str, Any]] = field(default_factory=list)
    routing_entries: List[Dict[str, Any]] = field(default_factory=list)
    machine_truth_fingerprint: str = ""
    policy_truth_fingerprint: str = ""
    changed_machine_inputs: List[str] = field(default_factory=list)
    changed_policy_inputs: List[str] = field(default_factory=list)
    runtime_status_payload: Dict[str, Any] = field(default_factory=dict)
    runtime_shape: Dict[str, Any] = field(default_factory=dict)
    runtime_shape_findings: List[str] = field(default_factory=list)
    runtime_state_mismatches: List[Dict[str, Any]] = field(default_factory=list)
    observer_status_payload: Dict[str, Any] = field(default_factory=dict)
    observer_summary_payload: Dict[str, Any] = field(default_factory=dict)
    observer_worst: str = "ok"
    summary_live_facts: Dict[str, Any] = field(default_factory=dict)
    telegram_context_routing: Dict[str, Any] = field(default_factory=dict)
    summary_text: str = ""
    aligned_summary_text: str = ""
    summary_changed_fields: List[str] = field(default_factory=list)


GitCommandRunner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the bounded v1 Server3 dream loop.")
    parser.add_argument(
        "--state-dir",
        type=Path,
        default=DEFAULT_STATE_DIR,
        help="Directory for latest truth/health/run/report outputs.",
    )
    parser.add_argument(
        "--bridge-state-dir",
        type=Path,
        default=DEFAULT_BRIDGE_STATE_DIR,
        help="Architect bridge state directory used for stale-context scope eligibility.",
    )
    parser.add_argument(
        "--timezone",
        default=DEFAULT_TZ,
        help="Timezone for generated timestamps.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute the bounded runner outputs without writing files.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the full bounded runner result as JSON.",
    )
    parser.add_argument(
        "--summary-path",
        type=Path,
        default=DEFAULT_SUMMARY_PATH,
        help="Secondary summary file that the loop may align conservatively.",
    )
    return parser.parse_args(argv)


def build_check_registry(config: DreamLoopConfig) -> List[DreamLoopCheckSpec]:
    return [
        DreamLoopCheckSpec(
            check_id="truth_files_fingerprint",
            truth_area="machine_truth",
            mode="fixed",
            trigger="always",
            inputs=tuple(str(path.relative_to(ROOT)) for path in TRUTH_INPUT_PATHS),
            executor="truth_files_fingerprint",
            mismatch_rule="watched_truth_input_fingerprint_changed",
            correction_target="truth_state",
            severity="info",
        ),
        DreamLoopCheckSpec(
            check_id="runtime_manifest_vs_status",
            truth_area="runtime_alignment",
            mode="fixed",
            trigger="always",
            inputs=(
                "infra/server3-runtime-manifest.json",
                "python3 ops/server3_runtime_status.py --json",
            ),
            executor="runtime_manifest_vs_status",
            mismatch_rule="manifest_runtime_names_or_expected_states_do_not_match_live_runtime_status",
            correction_target="truth_state,health_state",
            severity="warn",
        ),
        DreamLoopCheckSpec(
            check_id="runtime_observer_truth",
            truth_area="health_truth",
            mode="fixed",
            trigger="always",
            inputs=(
                "python3 ops/runtime_observer/runtime_observer.py --json status",
                "python3 ops/runtime_observer/runtime_observer.py --json summary --hours 24",
                "systemctl cat server3-runtime-observer.timer",
                "systemctl is-enabled server3-dream-loop.timer",
            ),
            executor="runtime_observer_truth",
            mismatch_rule="observer_status_or_summary_reports_non_ok_health",
            correction_target="health_state",
            severity="warn",
        ),
        DreamLoopCheckSpec(
            check_id="policy_watch_truth",
            truth_area="policy_truth",
            mode="conditional",
            trigger="all_inputs_exist",
            inputs=tuple(str(path.relative_to(ROOT)) for path in POLICY_INPUT_PATHS),
            executor="policy_watch_truth",
            mismatch_rule="watched_policy_inputs_changed",
            correction_target="truth_state",
            severity="info",
        ),
        DreamLoopCheckSpec(
            check_id="telegram_context_routing_truth",
            truth_area="telegram_context_routing",
            mode="conditional",
            trigger="all_inputs_exist",
            inputs=tuple(str(path.relative_to(ROOT)) for path in TELEGRAM_CONTEXT_ROUTING_INPUT_PATHS),
            executor="telegram_context_routing_truth",
            mismatch_rule="routing_anchor_markers_missing",
            correction_target="truth_state",
            severity="warn",
        ),
        DreamLoopCheckSpec(
            check_id="server3_summary_truth",
            truth_area="secondary_truth_surface",
            mode="conditional",
            trigger="summary_target_exists",
            inputs=(
                str(config.summary_path.relative_to(ROOT) if config.summary_path.is_relative_to(ROOT) else config.summary_path),
                "systemctl cat server3-runtime-observer.timer",
                "systemctl is-enabled server3-dream-loop.timer",
            ),
            executor="server3_summary_truth",
            mismatch_rule="mapped_summary_fields_do_not_match_structured_truth_or_approved_live_inputs",
            correction_target="SERVER3_SUMMARY.md",
            severity="warn",
        ),
    ]


def _serialize_registry_check(spec: DreamLoopCheckSpec) -> Dict[str, Any]:
    return {
        "check_id": spec.check_id,
        "truth_area": spec.truth_area,
        "mode": spec.mode,
        "trigger": spec.trigger,
        "inputs": list(spec.inputs),
        "executor": spec.executor,
        "mismatch_rule": spec.mismatch_rule,
        "correction_target": spec.correction_target,
        "severity": spec.severity,
    }


def _now(tz_name: str) -> datetime:
    return datetime.now(ZoneInfo(tz_name))


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _read_json_file(path: Path) -> Optional[Dict[str, Any]]:
    try:
        decoded = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except Exception:
        return None
    if not isinstance(decoded, dict):
        return None
    return decoded


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _hash_json_payload(payload: object) -> str:
    normalized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return _sha256_text(normalized)


def _file_entry(path: Path) -> Dict[str, Any]:
    entry: Dict[str, Any] = {"path": str(path.relative_to(ROOT) if path.is_relative_to(ROOT) else path)}
    if not path.exists():
        entry.update({"exists": False, "sha256": "", "size_bytes": 0})
        return entry
    stat = path.stat()
    entry.update(
        {
            "exists": True,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "size_bytes": stat.st_size,
            "mtime_ns": stat.st_mtime_ns,
        }
    )
    return entry


def _file_entries(paths: Iterable[Path]) -> List[Dict[str, Any]]:
    return [_file_entry(path) for path in paths]


def _file_entries_fingerprint(entries: Iterable[Dict[str, Any]]) -> str:
    normalized = [
        {
            "path": entry.get("path", ""),
            "exists": bool(entry.get("exists")),
            "sha256": entry.get("sha256", ""),
        }
        for entry in entries
    ]
    return _hash_json_payload(normalized)


def _run_json_command(args: Sequence[str]) -> Dict[str, Any]:
    proc = subprocess.run(args, capture_output=True, text=True, check=False, cwd=str(ROOT))
    stdout_text = proc.stdout.strip()
    try:
        decoded = json.loads(stdout_text)
    except Exception:
        decoded = None
    if proc.returncode != 0 and not isinstance(decoded, dict):
        stderr = proc.stderr.strip() or proc.stdout.strip() or "command failed"
        raise RuntimeError(f"{' '.join(args)} -> {stderr}")
    if not isinstance(decoded, dict):
        raise RuntimeError(f"{' '.join(args)} did not return a JSON object")
    return decoded


def _run_text_command(args: Sequence[str]) -> str:
    proc = subprocess.run(args, capture_output=True, text=True, check=False, cwd=str(ROOT))
    if proc.returncode != 0:
        stderr = proc.stderr.strip() or proc.stdout.strip() or "command failed"
        raise RuntimeError(f"{' '.join(args)} -> {stderr}")
    return proc.stdout


def _run_capture_command(args: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, text=True, check=False, cwd=str(ROOT))


def _compare_entries(
    current_entries: Iterable[Dict[str, Any]],
    previous_entries: Iterable[Dict[str, Any]],
) -> List[str]:
    previous_by_path = {
        str(entry.get("path", "")): str(entry.get("sha256", ""))
        for entry in previous_entries
        if isinstance(entry, dict)
    }
    changed: List[str] = []
    for entry in current_entries:
        path = str(entry.get("path", ""))
        sha = str(entry.get("sha256", ""))
        if previous_by_path.get(path, "") != sha:
            changed.append(path)
    return changed


def _load_scope_activity_from_canonical_sqlite(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    scopes: List[Dict[str, Any]] = []
    with sqlite3.connect(str(path)) as conn:
        rows = conn.execute(
            """
            SELECT
                scope_key,
                thread_id,
                worker_created_at,
                worker_last_used_at,
                in_flight_started_at,
                in_flight_message_id
            FROM canonical_sessions
            ORDER BY scope_key
            """
        ).fetchall()
    for row in rows:
        scope_key = str(row[0] or "").strip()
        if not scope_key:
            continue
        scopes.append(
            {
                "scope_key": scope_key,
                "thread_id": str(row[1] or "").strip(),
                "worker_created_at": float(row[2]) if row[2] is not None else None,
                "worker_last_used_at": float(row[3]) if row[3] is not None else None,
                "in_flight_started_at": float(row[4]) if row[4] is not None else None,
                "in_flight_message_id": int(row[5]) if row[5] is not None else None,
            }
        )
    return scopes


def _load_scope_activity_from_json(path: Path) -> List[Dict[str, Any]]:
    raw = _read_json_file(path)
    if raw is None:
        return []
    scopes: List[Dict[str, Any]] = []
    for scope_key, value in raw.items():
        if not isinstance(value, dict):
            continue
        scopes.append(
            {
                "scope_key": str(scope_key).strip(),
                "thread_id": str(value.get("thread_id") or "").strip(),
                "worker_created_at": (
                    float(value["worker_created_at"])
                    if isinstance(value.get("worker_created_at"), (int, float))
                    else None
                ),
                "worker_last_used_at": (
                    float(value["worker_last_used_at"])
                    if isinstance(value.get("worker_last_used_at"), (int, float))
                    else None
                ),
                "in_flight_started_at": (
                    float(value["in_flight_started_at"])
                    if isinstance(value.get("in_flight_started_at"), (int, float))
                    else None
                ),
                "in_flight_message_id": (
                    int(value["in_flight_message_id"])
                    if isinstance(value.get("in_flight_message_id"), int)
                    else None
                ),
            }
        )
    return scopes


def _collect_recent_or_active_scopes(bridge_state_dir: Path, *, now_ts: float) -> List[Dict[str, Any]]:
    sqlite_path = bridge_state_dir / "chat_sessions.sqlite3"
    json_path = bridge_state_dir / "chat_sessions.json"
    if sqlite_path.exists():
        scopes = _load_scope_activity_from_canonical_sqlite(sqlite_path)
    else:
        scopes = _load_scope_activity_from_json(json_path)
    cutoff = now_ts - timedelta(days=RECENT_ACTIVITY_DAYS).total_seconds()
    eligible: List[Dict[str, Any]] = []
    for scope in scopes:
        timestamps = [
            scope.get("worker_created_at"),
            scope.get("worker_last_used_at"),
            scope.get("in_flight_started_at"),
        ]
        has_recent_activity = any(isinstance(value, float) and value >= cutoff for value in timestamps)
        has_persisted_context = bool(scope.get("thread_id"))
        if has_recent_activity or has_persisted_context:
            eligible.append(scope)
    return eligible


def _extract_runtime_shape_truth(
    manifest_payload: Dict[str, Any],
    runtime_status_payload: Dict[str, Any],
) -> Tuple[Dict[str, Any], List[str]]:
    manifest_runtimes = manifest_payload.get("runtimes", [])
    status_runtimes = runtime_status_payload.get("runtimes", [])
    manifest_names = sorted(
        str(item.get("name", "")).strip()
        for item in manifest_runtimes
        if isinstance(item, dict) and str(item.get("name", "")).strip()
    )
    status_names = sorted(
        str(item.get("name", "")).strip()
        for item in status_runtimes
        if isinstance(item, dict) and str(item.get("name", "")).strip()
    )
    missing_in_status = sorted(set(manifest_names) - set(status_names))
    unexpected_in_status = sorted(set(status_names) - set(manifest_names))
    runtime_shape = {
        "manifest_runtime_names": manifest_names,
        "status_runtime_names": status_names,
        "missing_in_status": missing_in_status,
        "unexpected_in_status": unexpected_in_status,
        "manifest_path": runtime_status_payload.get("manifest"),
        "status_generated_at": runtime_status_payload.get("generated_at"),
        "all_runtime_names_match": not missing_in_status and not unexpected_in_status,
    }
    findings: List[str] = []
    if missing_in_status:
        findings.append(f"manifest runtimes missing from runtime_status: {', '.join(missing_in_status)}")
    if unexpected_in_status:
        findings.append(f"runtime_status reported unexpected runtimes: {', '.join(unexpected_in_status)}")
    return runtime_shape, findings


def _collect_telegram_context_routing_truth() -> Dict[str, Any]:
    anchors = {
        "message_inputs.py": (
            "def build_reply_context_prompt",
            "def should_include_telegram_context_prompt",
            "def build_telegram_context_prompt",
        ),
        "session_manager.py": (
            "def _resolve_scope_key",
            "def mark_busy",
            "def clear_busy",
        ),
    }
    source_status: List[Dict[str, Any]] = []
    all_present = True
    for relative_path, required_markers in anchors.items():
        path = ROOT / "src" / "telegram_bridge" / relative_path
        text = path.read_text(encoding="utf-8") if path.exists() else ""
        missing = [marker for marker in required_markers if marker not in text]
        if missing:
            all_present = False
        source_status.append(
            {
                "path": str(path.relative_to(ROOT)),
                "all_markers_present": not missing,
                "missing_markers": missing,
            }
        )
    return {
        "validated": all_present,
        "sources": source_status,
    }


def _health_findings_from_observer_status(observer_status: Dict[str, Any]) -> Tuple[str, List[Dict[str, Any]], List[str]]:
    kpis = observer_status.get("kpis", {})
    if not isinstance(kpis, dict):
        kpis = {}
    severity_order = {"ok": 0, "warn": 1, "unknown": 2, "critical": 3}
    worst = "ok"
    findings: List[Dict[str, Any]] = []
    warnings: List[str] = []
    for warning in observer_status.get("warnings", []) or []:
        warnings.append(str(warning))
    for name, payload in sorted(kpis.items()):
        if not isinstance(payload, dict):
            continue
        severity = str(payload.get("severity", "unknown"))
        if severity_order.get(severity, 3) > severity_order.get(worst, 0):
            worst = severity if severity in severity_order else "unknown"
        if severity != "ok":
            findings.append(
                {
                    "source": "runtime_observer_status",
                    "name": name,
                    "severity": severity,
                    "summary": f"{name} severity is {severity}",
                }
            )
    return worst, findings, warnings


def _observer_schedule_text(timer_unit_text: str) -> str:
    match = re.search(r"^OnCalendar=(.+)$", timer_unit_text, flags=re.MULTILINE)
    if not match:
        return "on its configured schedule"
    on_calendar = match.group(1).strip()
    if on_calendar == "*:0/5":
        return "every 5 minutes"
    return f"on `{on_calendar}`"


def _collect_summary_live_facts(
    run_text_command: Callable[[Sequence[str]], str],
    observer_status_payload: Dict[str, Any],
) -> Dict[str, Any]:
    timer_unit_text = run_text_command(("systemctl", "cat", "server3-runtime-observer.timer"))
    dream_loop_timer_enabled = False
    try:
        enabled_text = run_text_command(
            ("systemctl", "is-enabled", "server3-dream-loop.timer")
        ).strip()
        dream_loop_timer_enabled = enabled_text == "enabled"
    except Exception:
        dream_loop_timer_enabled = False
    observer_mode = str(observer_status_payload.get("mode") or "").strip() or "unknown"
    return {
        "observer_mode": observer_mode,
        "observer_schedule_text": _observer_schedule_text(timer_unit_text),
        "dream_loop_timer_enabled": dream_loop_timer_enabled,
    }


def _replace_or_insert_bullet(
    section_text: str,
    *,
    prefix: str,
    new_line: str,
) -> Tuple[str, bool]:
    lines = section_text.splitlines()
    changed = False
    for index, line in enumerate(lines):
        if line.startswith(prefix):
            if line != new_line:
                lines[index] = new_line
                changed = True
            return "\n".join(lines), changed
    insert_at = len(lines)
    for index, line in enumerate(lines):
        if line.startswith("## "):
            insert_at = index
            break
    lines.insert(insert_at, new_line)
    changed = True
    return "\n".join(lines), changed


def _replace_or_insert_bullet_in_section(
    document_text: str,
    *,
    section_header: str,
    prefix: str,
    new_line: str,
) -> Tuple[str, bool]:
    start = document_text.find(section_header)
    if start == -1:
        return document_text, False
    section_start = start + len(section_header)
    next_header = document_text.find("\n## ", section_start)
    if next_header == -1:
        next_header = len(document_text)
    section_text = document_text[section_start:next_header]
    updated_section, changed = _replace_or_insert_bullet(
        section_text,
        prefix=prefix,
        new_line=new_line,
    )
    if not changed:
        return document_text, False
    if next_header != len(document_text) and not updated_section.endswith("\n"):
        updated_section += "\n"
    return document_text[:section_start] + updated_section + document_text[next_header:], True


def _ensure_recent_change_entry(
    summary_text: str,
    *,
    date_text: str,
    entry_text: str,
) -> Tuple[str, bool]:
    header = "## Recent Changes (Rolling Max 8)"
    start = summary_text.find(header)
    if start == -1:
        return summary_text, False
    after_header = start + len(header)
    next_header = summary_text.find("\n## ", after_header)
    if next_header == -1:
        next_header = len(summary_text)
    section = summary_text[after_header:next_header]
    target_line = f"- {date_text}: {entry_text}"
    bullet_lines = [line for line in section.splitlines() if line.startswith("- ")]
    if target_line in bullet_lines:
        return summary_text, False
    new_bullets = [target_line, *bullet_lines]
    new_bullets = new_bullets[:8]
    prefix = section.splitlines()
    rebuilt_lines: List[str] = []
    inserted = False
    for line in prefix:
        if line.startswith("- "):
            if not inserted:
                rebuilt_lines.extend(new_bullets)
                inserted = True
            continue
        rebuilt_lines.append(line)
    if not inserted:
        rebuilt_lines.append("")
        rebuilt_lines.extend(new_bullets)
    rebuilt_section = "\n".join(rebuilt_lines)
    if next_header != len(summary_text) and not rebuilt_section.endswith("\n"):
        rebuilt_section += "\n"
    return summary_text[:after_header] + rebuilt_section + summary_text[next_header:], True


def _align_server3_summary(
    summary_text: str,
    *,
    generated_at: datetime,
    summary_facts: Dict[str, Any],
) -> Tuple[str, List[str]]:
    del generated_at
    original_text = summary_text
    changed_fields: List[str] = []
    observer_mode = summary_facts.get("observer_mode", "unknown")
    observer_schedule = summary_facts.get("observer_schedule_text", "on its configured schedule")
    observer_line = (
        f"- Runtime observer runs from `server3-runtime-observer.timer` {observer_schedule}; "
        f"live mode is currently `{observer_mode}`."
    )
    summary_text, changed = _replace_or_insert_bullet_in_section(
        summary_text,
        section_header="## Operational Memory (Pinned)",
        prefix="- Runtime observer runs from `server3-runtime-observer.timer`",
        new_line=observer_line,
    )
    if changed:
        changed_fields.append("runtime_observer_line")

    if summary_facts.get("dream_loop_timer_enabled"):
        dream_loop_line = (
            "- Dream loop now runs from `server3-dream-loop.timer` around `02:15 AEST` and "
            "writes the production truth/health baseline under `/var/lib/server3-dream-loop`."
        )
        summary_text, changed = _replace_or_insert_bullet_in_section(
            summary_text,
            section_header="## Operational Memory (Pinned)",
            prefix="- Dream loop now runs from `server3-dream-loop.timer`",
            new_line=dream_loop_line,
        )
        if changed:
            changed_fields.append("dream_loop_operational_memory")

    if summary_text == original_text:
        return summary_text, []
    return summary_text, changed_fields


def _build_runtime_state_mismatches(runtime_status_payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    mismatches: List[Dict[str, Any]] = []
    for runtime in runtime_status_payload.get("runtimes", []) or []:
        if not isinstance(runtime, dict):
            continue
        if runtime.get("matches_expected", True):
            continue
        mismatches.append(
            {
                "name": str(runtime.get("name") or "runtime"),
                "live_state": str(runtime.get("live_state") or "unknown"),
                "expected_default_state": str(runtime.get("expected_default_state") or "unknown"),
            }
        )
    return mismatches


def _render_secondary_doc_alignment(
    *,
    summary_path: Path,
    summary_changed_fields: Sequence[str],
) -> Dict[str, Any]:
    documents = [
        {
            "path": str(summary_path),
            "doc_role": "secondary_rendered_explainer",
            "managed_by_loop": True,
            "out_of_alignment": bool(summary_changed_fields),
            "changed_fields": list(summary_changed_fields),
        },
    ]
    return {
        "summary_path": str(summary_path),
        "summary_changed_fields": list(summary_changed_fields),
        "summary_out_of_alignment": bool(summary_changed_fields),
        "documents": documents,
        "any_secondary_doc_out_of_alignment": any(
            bool(document.get("out_of_alignment")) for document in documents
        ),
    }


def _render_generated_output_status(
    *,
    report_path: Path,
) -> Dict[str, Any]:
    return {
        "outputs": [
            {
                "path": str(report_path),
                "output_role": "generated_report_layer",
                "managed_by_loop": True,
                "rendered_from_current_state": True,
                "expected_to_change_each_run": True,
            }
        ]
    }


def _verify_persisted_outputs(
    *,
    truth_state_path: Path,
    expected_truth_state: Dict[str, Any],
    health_state_path: Path,
    expected_health_state: Dict[str, Any],
    run_state_path: Path,
    expected_run_state: Dict[str, Any],
    report_path: Path,
    expected_report_text: str,
    summary_path: Path,
    expected_summary_text: Optional[str],
) -> List[str]:
    mismatches: List[str] = []

    persisted_truth_state = _read_json_file(truth_state_path)
    if persisted_truth_state != expected_truth_state:
        mismatches.append(f"persisted truth state mismatch: {truth_state_path}")

    persisted_health_state = _read_json_file(health_state_path)
    if persisted_health_state != expected_health_state:
        mismatches.append(f"persisted health state mismatch: {health_state_path}")

    persisted_run_state = _read_json_file(run_state_path)
    if persisted_run_state != expected_run_state:
        mismatches.append(f"persisted run state mismatch: {run_state_path}")

    try:
        persisted_report_text = report_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        persisted_report_text = None
    if persisted_report_text != expected_report_text:
        mismatches.append(f"persisted report mismatch: {report_path}")

    if expected_summary_text is not None:
        try:
            persisted_summary_text = summary_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            persisted_summary_text = None
        if persisted_summary_text != expected_summary_text:
            mismatches.append(f"persisted summary mismatch: {summary_path}")

    return mismatches


def _build_execution_context(
    config: DreamLoopConfig,
    *,
    generated_at: str,
    run_started_at: datetime,
    previous_truth_state: Dict[str, Any],
    run_json_command: Callable[[Sequence[str]], Dict[str, Any]],
    run_text_command: Callable[[Sequence[str]], str],
) -> DreamLoopExecutionContext:
    previous_watched = previous_truth_state.get("watched_inputs", {}) if isinstance(previous_truth_state, dict) else {}
    previous_truth_entries = previous_watched.get("machine_truth_inputs", []) if isinstance(previous_watched, dict) else []
    previous_policy_entries = previous_watched.get("policy_inputs", []) if isinstance(previous_watched, dict) else []

    truth_entries = _file_entries(TRUTH_INPUT_PATHS)
    policy_entries = _file_entries(POLICY_INPUT_PATHS)
    routing_entries = _file_entries(TELEGRAM_CONTEXT_ROUTING_INPUT_PATHS)

    machine_truth_fingerprint = _file_entries_fingerprint(truth_entries)
    policy_truth_fingerprint = _file_entries_fingerprint(policy_entries)

    changed_machine_inputs = _compare_entries(truth_entries, previous_truth_entries)
    changed_policy_inputs = _compare_entries(policy_entries, previous_policy_entries)

    return DreamLoopExecutionContext(
        config=config,
        generated_at=generated_at,
        run_started_at=run_started_at,
        previous_truth_state=previous_truth_state,
        run_json_command=run_json_command,
        run_text_command=run_text_command,
        truth_state={
            "generated_at": generated_at,
            "timezone": config.timezone,
            "machine_truth_fingerprint": machine_truth_fingerprint,
            "policy_truth_fingerprint": policy_truth_fingerprint,
            "watched_inputs": {
                "machine_truth_inputs": truth_entries,
                "policy_inputs": policy_entries,
                "telegram_context_routing_inputs": routing_entries,
            },
            "registry_checks": {
                "approved_secondary_truth_surfaces": ["SERVER3_SUMMARY.md"],
                "checks": [],
            },
            "runtime_shape": {},
            "live_runtime_alignment": {
                "machine_truth_fingerprint_uses_structured_inputs_only": True,
                "machine_truth_boundary_reason": (
                    "The machine-truth fingerprint follows the spec and only hashes watched structured-truth inputs. "
                    "Live runtime state and log-derived health are recorded separately so drift is visible without "
                    "changing the stale-context trigger."
                ),
                "runtime_shape_matches_manifest": False,
                "runtime_shape_findings": [],
                "runtime_state_mismatches": [],
                "live_inputs_reflected_in_health_state": [],
            },
            "telegram_context_routing": {},
            "secondary_doc_alignment": {},
            "generated_output_status": {},
            "stale_context_eligibility": {
                "rollout_scope": "Architect",
                "machine_truth_changed": False,
                "policy_inputs_changed": False,
                "changed_machine_inputs": changed_machine_inputs,
                "changed_policy_inputs": changed_policy_inputs,
                "eligible_scope_keys": [],
                "eligible_scope_count": 0,
                "scope_basis": {
                    "recent_activity_window_days": RECENT_ACTIVITY_DAYS,
                    "active_or_recent_scopes": [],
                },
                "scope_warning_statuses": [],
                "stale_warning_state_path": build_stale_context_state_path(str(config.bridge_state_dir)),
            },
        },
        health_state={
            "generated_at": generated_at,
            "timezone": config.timezone,
            "health_status": "ok",
            "health_findings": [],
            "observer_status": {},
            "observer_summary": {},
            "runtime_status_summary": {
                "generated_at": None,
                "runtime_count": 0,
                "mismatched_runtime_count": 0,
            },
            "registry_checks": [],
        },
        truth_entries=truth_entries,
        policy_entries=policy_entries,
        routing_entries=routing_entries,
        machine_truth_fingerprint=machine_truth_fingerprint,
        policy_truth_fingerprint=policy_truth_fingerprint,
        changed_machine_inputs=changed_machine_inputs,
        changed_policy_inputs=changed_policy_inputs,
    )


def _check_truth_files_fingerprint(spec: DreamLoopCheckSpec, ctx: DreamLoopExecutionContext) -> Dict[str, Any]:
    ctx.truth_state["machine_truth_fingerprint"] = ctx.machine_truth_fingerprint
    ctx.truth_state["watched_inputs"]["machine_truth_inputs"] = ctx.truth_entries
    return {
        **_serialize_registry_check(spec),
        "status": "ok",
        "fingerprint": ctx.machine_truth_fingerprint,
        "changed_inputs": list(ctx.changed_machine_inputs),
    }


def _check_policy_watch_truth(spec: DreamLoopCheckSpec, ctx: DreamLoopExecutionContext) -> Dict[str, Any]:
    ctx.truth_state["policy_truth_fingerprint"] = ctx.policy_truth_fingerprint
    ctx.truth_state["watched_inputs"]["policy_inputs"] = ctx.policy_entries
    return {
        **_serialize_registry_check(spec),
        "status": "ok",
        "fingerprint": ctx.policy_truth_fingerprint,
        "changed_inputs": list(ctx.changed_policy_inputs),
    }


def _check_runtime_manifest_vs_status(spec: DreamLoopCheckSpec, ctx: DreamLoopExecutionContext) -> Dict[str, Any]:
    manifest_payload = json.loads((ROOT / "infra" / "server3-runtime-manifest.json").read_text(encoding="utf-8"))
    ctx.runtime_status_payload = ctx.run_json_command(("python3", "ops/server3_runtime_status.py", "--json"))
    ctx.runtime_shape, ctx.runtime_shape_findings = _extract_runtime_shape_truth(
        manifest_payload,
        ctx.runtime_status_payload,
    )
    ctx.runtime_state_mismatches = _build_runtime_state_mismatches(ctx.runtime_status_payload)
    ctx.truth_state["runtime_shape"] = ctx.runtime_shape
    ctx.truth_state["live_runtime_alignment"].update(
        {
            "runtime_shape_matches_manifest": ctx.runtime_shape.get("all_runtime_names_match", False),
            "runtime_shape_findings": ctx.runtime_shape_findings,
            "runtime_state_mismatches": ctx.runtime_state_mismatches,
            "live_inputs_reflected_in_health_state": [
                "ops/server3_runtime_status.py --json",
            ],
        }
    )
    for finding in ctx.runtime_shape_findings:
        ctx.health_state["health_findings"].append(
            {
                "source": "runtime_manifest_vs_status",
                "name": "runtime_shape_mismatch",
                "severity": "warn",
                "summary": finding,
            }
        )
    for runtime in ctx.runtime_status_payload.get("runtimes", []) or []:
        if not isinstance(runtime, dict) or runtime.get("matches_expected", True):
            continue
        ctx.health_state["health_findings"].append(
            {
                "source": "server3_runtime_status",
                "name": str(runtime.get("name") or "runtime"),
                "severity": "warn",
                "summary": (
                    f"{runtime.get('name', 'runtime')} is {runtime.get('live_state', 'unknown')}, "
                    f"expected {runtime.get('expected_default_state', 'unknown')}"
                ),
            }
        )
    return {
        **_serialize_registry_check(spec),
        "status": "mismatch" if ctx.runtime_shape_findings or ctx.runtime_state_mismatches else "ok",
        "runtime_shape_matches_manifest": ctx.runtime_shape.get("all_runtime_names_match", False),
        "runtime_shape_findings": list(ctx.runtime_shape_findings),
        "runtime_state_mismatches": list(ctx.runtime_state_mismatches),
    }


def _check_runtime_observer_truth(spec: DreamLoopCheckSpec, ctx: DreamLoopExecutionContext) -> Dict[str, Any]:
    ctx.observer_status_payload = ctx.run_json_command(
        ("python3", "ops/runtime_observer/runtime_observer.py", "--json", "status")
    )
    ctx.observer_summary_payload = ctx.run_json_command(
        ("python3", "ops/runtime_observer/runtime_observer.py", "--json", "summary", "--hours", "24")
    )
    ctx.summary_live_facts = _collect_summary_live_facts(ctx.run_text_command, ctx.observer_status_payload)
    ctx.observer_worst, observer_findings, observer_warnings = _health_findings_from_observer_status(
        ctx.observer_status_payload
    )
    ctx.warnings_emitted.extend(observer_warnings)
    ctx.health_state["health_findings"].extend(observer_findings)
    summary_kpis = ctx.observer_summary_payload.get("kpis", {})
    if isinstance(summary_kpis, dict):
        for name, payload in sorted(summary_kpis.items()):
            if not isinstance(payload, dict):
                continue
            worst = str(payload.get("worst_severity", "ok"))
            if worst == "ok":
                continue
            ctx.health_state["health_findings"].append(
                {
                    "source": "runtime_observer_summary",
                    "name": name,
                    "severity": worst,
                    "summary": f"{name} worst severity in last 24h is {worst}",
                }
            )
    ctx.health_state["observer_status"] = ctx.observer_status_payload
    ctx.health_state["observer_summary"] = ctx.observer_summary_payload
    ctx.truth_state["live_runtime_alignment"]["live_inputs_reflected_in_health_state"] = [
        "ops/server3_runtime_status.py --json",
        "ops/runtime_observer/runtime_observer.py --json status",
        "ops/runtime_observer/runtime_observer.py --json summary --hours 24",
    ]
    return {
        **_serialize_registry_check(spec),
        "status": "mismatch" if ctx.observer_worst != "ok" else "ok",
        "observer_mode": str(ctx.observer_status_payload.get("mode") or "unknown"),
        "observer_worst_severity": ctx.observer_worst,
        "warning_count": len(observer_warnings),
    }


def _check_telegram_context_routing_truth(spec: DreamLoopCheckSpec, ctx: DreamLoopExecutionContext) -> Dict[str, Any]:
    ctx.truth_state["watched_inputs"]["telegram_context_routing_inputs"] = ctx.routing_entries
    ctx.telegram_context_routing = _collect_telegram_context_routing_truth()
    ctx.truth_state["telegram_context_routing"] = ctx.telegram_context_routing
    if not ctx.telegram_context_routing.get("validated", False):
        ctx.unresolved_items.append("telegram context routing anchors no longer match expected bridge functions")
    return {
        **_serialize_registry_check(spec),
        "status": "ok" if ctx.telegram_context_routing.get("validated", False) else "mismatch",
        "validated": bool(ctx.telegram_context_routing.get("validated", False)),
        "sources": list(ctx.telegram_context_routing.get("sources", [])),
    }


def _check_server3_summary_truth(spec: DreamLoopCheckSpec, ctx: DreamLoopExecutionContext) -> Dict[str, Any]:
    ctx.summary_text = ctx.config.summary_path.read_text(encoding="utf-8")
    ctx.aligned_summary_text, ctx.summary_changed_fields = _align_server3_summary(
        ctx.summary_text,
        generated_at=ctx.run_started_at,
        summary_facts=ctx.summary_live_facts,
    )
    return {
        **_serialize_registry_check(spec),
        "status": "mismatch" if ctx.summary_changed_fields else "ok",
        "approved_secondary_truth_surface": "SERVER3_SUMMARY.md",
        "mapped_fields": ["runtime_observer_line", "dream_loop_operational_memory"],
        "changed_fields": list(ctx.summary_changed_fields),
    }


CHECK_EXECUTORS: Dict[str, Callable[[DreamLoopCheckSpec, DreamLoopExecutionContext], Dict[str, Any]]] = {
    "truth_files_fingerprint": _check_truth_files_fingerprint,
    "policy_watch_truth": _check_policy_watch_truth,
    "runtime_manifest_vs_status": _check_runtime_manifest_vs_status,
    "runtime_observer_truth": _check_runtime_observer_truth,
    "telegram_context_routing_truth": _check_telegram_context_routing_truth,
    "server3_summary_truth": _check_server3_summary_truth,
}


def _should_execute_check(spec: DreamLoopCheckSpec, config: DreamLoopConfig) -> Tuple[bool, str]:
    if spec.trigger == "always":
        return True, ""
    if spec.trigger == "all_inputs_exist":
        for relative in spec.inputs:
            if relative.startswith("python3 ") or relative.startswith("systemctl "):
                continue
            path = ROOT / relative
            if not path.exists():
                return False, f"missing input: {relative}"
        return True, ""
    if spec.trigger == "summary_target_exists":
        if not config.summary_path.exists():
            return False, f"missing input: {config.summary_path}"
        return True, ""
    return False, f"unsupported trigger: {spec.trigger}"


def _run_registry_checks(
    registry: Sequence[DreamLoopCheckSpec],
    ctx: DreamLoopExecutionContext,
) -> None:
    for spec in registry:
        should_execute, reason = _should_execute_check(spec, ctx.config)
        if not should_execute:
            ctx.skipped_checks.append({"check_id": spec.check_id, "reason": reason})
            continue
        executor = CHECK_EXECUTORS[spec.executor]
        result = executor(spec, ctx)
        ctx.checks_executed.append(spec.check_id)
        ctx.registry_check_results.append(result)
    ctx.truth_state["registry_checks"]["checks"] = list(ctx.registry_check_results)
    ctx.health_state["registry_checks"] = [
        result
        for result in ctx.registry_check_results
        if result.get("correction_target") == "health_state" or "health_state" in str(result.get("correction_target"))
    ]


def _finalize_health_state(ctx: DreamLoopExecutionContext) -> None:
    severity_order = {"ok": 0, "warn": 1, "unknown": 2, "critical": 3}
    health_status = "ok"
    for finding in ctx.health_state.get("health_findings", []):
        severity = str(finding.get("severity", "unknown"))
        if severity_order.get(severity, 3) > severity_order.get(health_status, 0):
            health_status = severity if severity in severity_order else "unknown"
    if ctx.observer_worst != "ok" and severity_order.get(ctx.observer_worst, 3) > severity_order.get(health_status, 0):
        health_status = ctx.observer_worst
    ctx.health_state["health_status"] = health_status
    ctx.health_state["runtime_status_summary"] = {
        "generated_at": ctx.runtime_status_payload.get("generated_at"),
        "runtime_count": len(ctx.runtime_status_payload.get("runtimes", []) or []),
        "mismatched_runtime_count": sum(
            1
            for runtime in ctx.runtime_status_payload.get("runtimes", []) or []
            if isinstance(runtime, dict) and not runtime.get("matches_expected", True)
        ),
    }


def _finalize_stale_context_state(ctx: DreamLoopExecutionContext) -> None:
    recent_or_active_scopes = _collect_recent_or_active_scopes(
        ctx.config.bridge_state_dir,
        now_ts=ctx.run_started_at.timestamp(),
    )
    previous_machine_truth_fingerprint = str(ctx.previous_truth_state.get("machine_truth_fingerprint") or "")
    previous_policy_truth_fingerprint = str(ctx.previous_truth_state.get("policy_truth_fingerprint") or "")
    machine_truth_changed = bool(previous_machine_truth_fingerprint) and (
        previous_machine_truth_fingerprint != ctx.machine_truth_fingerprint
    )
    policy_inputs_changed = bool(previous_policy_truth_fingerprint) and (
        previous_policy_truth_fingerprint != ctx.policy_truth_fingerprint
    )
    eligible_scope_keys = (
        [scope["scope_key"] for scope in recent_or_active_scopes]
        if machine_truth_changed or policy_inputs_changed
        else []
    )
    stale_fingerprint = _hash_json_payload(
        {
            "machine_truth_fingerprint": ctx.machine_truth_fingerprint,
            "policy_truth_fingerprint": ctx.policy_truth_fingerprint,
        }
    )
    stale_state_path = build_stale_context_state_path(str(ctx.config.bridge_state_dir))
    persisted_statuses = load_stale_context_statuses(stale_state_path)
    updated_statuses = apply_stale_context_updates(
        persisted_statuses,
        eligible_scope_keys=eligible_scope_keys,
        stale_fingerprint=stale_fingerprint,
        generated_at=ctx.generated_at,
        trigger_changed=machine_truth_changed or policy_inputs_changed,
    )
    if not ctx.config.dry_run and updated_statuses != persisted_statuses:
        persist_stale_context_statuses(stale_state_path, updated_statuses)
    ctx.truth_state["stale_context_eligibility"] = {
        "rollout_scope": "Architect",
        "machine_truth_changed": machine_truth_changed,
        "policy_inputs_changed": policy_inputs_changed,
        "changed_machine_inputs": list(ctx.changed_machine_inputs),
        "changed_policy_inputs": list(ctx.changed_policy_inputs),
        "eligible_scope_keys": list(eligible_scope_keys),
        "eligible_scope_count": len(eligible_scope_keys),
        "scope_basis": {
            "recent_activity_window_days": RECENT_ACTIVITY_DAYS,
            "active_or_recent_scopes": [
                {
                    "scope_key": scope["scope_key"],
                    "has_thread": bool(scope.get("thread_id")),
                    "worker_last_used_at": scope.get("worker_last_used_at"),
                    "in_flight_started_at": scope.get("in_flight_started_at"),
                }
                for scope in recent_or_active_scopes
            ],
        },
        "scope_warning_statuses": snapshot_stale_context_statuses(updated_statuses, eligible_scope_keys),
        "stale_warning_state_path": stale_state_path,
        "stale_warning_fingerprint": stale_fingerprint,
    }


def _repo_relative_path(path_value: str | Path) -> Optional[str]:
    path = Path(path_value)
    try:
        relative = path.resolve().relative_to(ROOT.resolve())
    except Exception:
        return None
    return str(relative)


def _git_status_entries_for_paths(
    relative_paths: Sequence[str],
    *,
    run_capture_command: GitCommandRunner,
) -> Dict[str, str]:
    if not relative_paths:
        return {}
    proc = run_capture_command(("git", "status", "--porcelain", "--", *relative_paths))
    if proc.returncode != 0:
        stderr = proc.stderr.strip() or proc.stdout.strip() or "git status failed"
        raise RuntimeError(stderr)
    entries: Dict[str, str] = {}
    for line in (proc.stdout or "").splitlines():
        if len(line) < 4:
            continue
        status = line[:2]
        path_text = line[3:].strip()
        if " -> " in path_text:
            path_text = path_text.split(" -> ", 1)[1].strip()
        if path_text:
            entries[path_text] = status
    return entries


def _git_has_preexisting_staged_changes(*, run_capture_command: GitCommandRunner) -> bool:
    proc = run_capture_command(("git", "diff", "--cached", "--name-only"))
    if proc.returncode != 0:
        stderr = proc.stderr.strip() or proc.stdout.strip() or "git diff --cached failed"
        raise RuntimeError(stderr)
    return bool((proc.stdout or "").strip())


def _git_push_command(*, run_capture_command: GitCommandRunner) -> List[str]:
    proc = run_capture_command(("git", "remote"))
    if proc.returncode != 0:
        return ["git", "push"]
    remotes = {line.strip() for line in (proc.stdout or "").splitlines() if line.strip()}
    if "origin" in remotes:
        return ["git", "push", "origin", "HEAD"]
    return ["git", "push"]


def _commit_candidate_repo_paths(config: DreamLoopConfig) -> List[str]:
    candidates = [
        config.summary_path,
        config.state_dir / LATEST_TRUTH_STATE,
        config.state_dir / LATEST_HEALTH_STATE,
    ]
    relative_paths = []
    for candidate in candidates:
        relative = _repo_relative_path(candidate)
        if relative is not None:
            relative_paths.append(relative)
    return sorted(dict.fromkeys(relative_paths))


def _build_git_automation_result(
    *,
    status: str,
    candidate_paths: Sequence[str],
    skipped_dirty_paths: Sequence[str],
    safe_paths: Sequence[str],
    commit_attempted: bool,
    commit_message: str = "",
    committed_sha: str = "",
    push_attempted: bool = False,
    push_succeeded: bool = False,
    commit_stdout: str = "",
    commit_stderr: str = "",
    push_stdout: str = "",
    push_stderr: str = "",
    skip_reason: str = "",
    preexisting_staged_changes: bool = False,
) -> Dict[str, Any]:
    return {
        "status": status,
        "candidate_repo_paths": list(candidate_paths),
        "skipped_dirty_paths": list(skipped_dirty_paths),
        "safe_repo_paths": list(safe_paths),
        "preexisting_staged_changes": preexisting_staged_changes,
        "skip_reason": skip_reason,
        "commit_attempted": commit_attempted,
        "commit_message": commit_message,
        "committed_sha": committed_sha,
        "push_attempted": push_attempted,
        "push_succeeded": push_succeeded,
        "commit_stdout": commit_stdout,
        "commit_stderr": commit_stderr,
        "push_stdout": push_stdout,
        "push_stderr": push_stderr,
    }


def _run_git_automation(
    *,
    config: DreamLoopConfig,
    run_capture_command: GitCommandRunner,
    generated_at: str,
    candidate_paths: Sequence[str],
    preexisting_staged_changes: bool,
    pre_run_dirty_entries: Dict[str, str],
) -> Dict[str, Any]:
    if not candidate_paths:
        return _build_git_automation_result(
            status="skipped_no_repo_managed_paths",
            candidate_paths=[],
            skipped_dirty_paths=[],
            safe_paths=[],
            commit_attempted=False,
            skip_reason="no repo-managed dream-loop outputs are inside the git repo",
        )

    post_run_dirty_entries = _git_status_entries_for_paths(candidate_paths, run_capture_command=run_capture_command)
    changed_candidate_paths = [path for path in candidate_paths if path in post_run_dirty_entries]
    if not changed_candidate_paths:
        return _build_git_automation_result(
            status="skipped_no_repo_changes",
            candidate_paths=candidate_paths,
            skipped_dirty_paths=[],
            safe_paths=[],
            commit_attempted=False,
            skip_reason="no repo-managed candidate files changed in this run",
            preexisting_staged_changes=preexisting_staged_changes,
        )
    if preexisting_staged_changes:
        return _build_git_automation_result(
            status="skipped_preexisting_staged_changes",
            candidate_paths=candidate_paths,
            skipped_dirty_paths=[],
            safe_paths=[],
            commit_attempted=False,
            skip_reason="repo already had staged changes before dream-loop git automation",
            preexisting_staged_changes=True,
        )

    skipped_dirty_paths = [path for path in changed_candidate_paths if path in pre_run_dirty_entries]
    safe_paths = [path for path in changed_candidate_paths if path not in pre_run_dirty_entries]
    if not safe_paths:
        return _build_git_automation_result(
            status="skipped_only_preexisting_dirty_paths",
            candidate_paths=candidate_paths,
            skipped_dirty_paths=skipped_dirty_paths,
            safe_paths=[],
            commit_attempted=False,
            skip_reason="all changed repo-managed candidate files were already dirty before the run",
        )

    add_proc = run_capture_command(("git", "add", "--", *safe_paths))
    if add_proc.returncode != 0:
        return _build_git_automation_result(
            status="commit_failed",
            candidate_paths=candidate_paths,
            skipped_dirty_paths=skipped_dirty_paths,
            safe_paths=safe_paths,
            commit_attempted=True,
            commit_message="",
            commit_stdout=add_proc.stdout.strip(),
            commit_stderr=add_proc.stderr.strip(),
            skip_reason="git add failed",
        )
    commit_message = f"Dream loop v2.1 auto-align {generated_at}"
    commit_proc = run_capture_command(("git", "commit", "-m", commit_message))
    if commit_proc.returncode != 0:
        return _build_git_automation_result(
            status="commit_failed",
            candidate_paths=candidate_paths,
            skipped_dirty_paths=skipped_dirty_paths,
            safe_paths=safe_paths,
            commit_attempted=True,
            commit_message=commit_message,
            commit_stdout=commit_proc.stdout.strip(),
            commit_stderr=commit_proc.stderr.strip(),
            skip_reason="git commit failed",
        )
    sha_proc = run_capture_command(("git", "rev-parse", "HEAD"))
    committed_sha = (sha_proc.stdout or "").strip() if sha_proc.returncode == 0 else ""
    push_command = _git_push_command(run_capture_command=run_capture_command)
    push_proc = run_capture_command(tuple(push_command))
    if push_proc.returncode != 0:
        return _build_git_automation_result(
            status="push_failed",
            candidate_paths=candidate_paths,
            skipped_dirty_paths=skipped_dirty_paths,
            safe_paths=safe_paths,
            commit_attempted=True,
            commit_message=commit_message,
            committed_sha=committed_sha,
            push_attempted=True,
            push_succeeded=False,
            commit_stdout=commit_proc.stdout.strip(),
            commit_stderr=commit_proc.stderr.strip(),
            push_stdout=push_proc.stdout.strip(),
            push_stderr=push_proc.stderr.strip(),
        )
    return _build_git_automation_result(
        status="committed_and_pushed",
        candidate_paths=candidate_paths,
        skipped_dirty_paths=skipped_dirty_paths,
        safe_paths=safe_paths,
        commit_attempted=True,
        commit_message=commit_message,
        committed_sha=committed_sha,
        push_attempted=True,
        push_succeeded=True,
        commit_stdout=commit_proc.stdout.strip(),
        commit_stderr=commit_proc.stderr.strip(),
        push_stdout=push_proc.stdout.strip(),
        push_stderr=push_proc.stderr.strip(),
    )


def _build_report(
    truth_state: Dict[str, Any],
    health_state: Dict[str, Any],
    run_state: Dict[str, Any],
) -> str:
    stale = truth_state.get("stale_context_eligibility", {}) or {}
    doc_alignment = truth_state.get("secondary_doc_alignment", {}) or {}
    generated_outputs = truth_state.get("generated_output_status", {}) or {}
    live_runtime_alignment = truth_state.get("live_runtime_alignment", {}) or {}
    git_automation = run_state.get("git_automation", {}) or {}
    lines = [
        "# Server3 Dream Loop Report",
        "",
        f"- Generated at: {run_state['generated_at']}",
        f"- Run status: {run_state['run_status']}",
        f"- Dry run: {'yes' if run_state.get('dry_run') else 'no'}",
        f"- Machine truth changed: {'yes' if stale.get('machine_truth_changed') else 'no'}",
        f"- Policy eligibility changed: {'yes' if stale.get('policy_inputs_changed') else 'no'}",
        "- Machine truth fingerprint excludes live runtime/log health by design; those are tracked separately below.",
        f"- Health status: {health_state['health_status']}",
    ]
    if git_automation:
        lines.append(f"- Git automation: {git_automation.get('status', 'unknown')}")
        committed_sha = str(git_automation.get("committed_sha") or "")
        if committed_sha:
            lines.append(f"- Committed SHA: `{committed_sha}`")
        if git_automation.get("push_attempted"):
            lines.append(
                f"- Push succeeded: {'yes' if git_automation.get('push_succeeded') else 'no'}"
            )
    lines.extend([
        "",
        "## Artifacts",
        "",
    ])
    for artifact in run_state.get("artifacts_written", []):
        lines.append(f"- {artifact}")
    files_updated = run_state.get("files_updated", []) or []
    lines.extend(["", "## Files Updated", ""])
    if files_updated:
        for path in files_updated:
            lines.append(f"- {path}")
    else:
        lines.append("- none")
    lines.extend(["", "## Truth Summary", ""])
    lines.append(f"- Machine truth fingerprint: `{truth_state['machine_truth_fingerprint']}`")
    lines.append(f"- Policy truth fingerprint: `{truth_state['policy_truth_fingerprint']}`")
    changed_machine = stale.get("changed_machine_inputs", []) or []
    changed_policy = stale.get("changed_policy_inputs", []) or []
    lines.append(
        "- Changed machine inputs: "
        + (", ".join(changed_machine) if changed_machine else "none")
    )
    lines.append(
        "- Changed policy inputs: "
        + (", ".join(changed_policy) if changed_policy else "none")
    )
    eligible_scopes = stale.get("eligible_scope_keys", []) or []
    lines.append(
        "- Eligible Architect scopes: "
        + (", ".join(eligible_scopes) if eligible_scopes else "none")
    )
    lines.extend(["", "## Secondary Docs", ""])
    for document in doc_alignment.get("documents", []) or []:
        status = "out_of_alignment" if document.get("out_of_alignment") else "aligned"
        lines.append(f"- [{status}] {document.get('path', 'unknown')}")
    lines.extend(["", "## Generated Outputs", ""])
    for output in generated_outputs.get("outputs", []) or []:
        lines.append(f"- [rendered] {output.get('path', 'unknown')}")
    lines.extend(["", "## Git Automation", ""])
    if git_automation:
        lines.append(f"- Status: {git_automation.get('status', 'unknown')}")
        candidate_paths = git_automation.get("candidate_repo_paths", []) or []
        lines.append("- Candidate repo-managed files: " + (", ".join(candidate_paths) if candidate_paths else "none"))
        safe_paths = git_automation.get("safe_repo_paths", []) or []
        lines.append("- Safe files committed this run: " + (", ".join(safe_paths) if safe_paths else "none"))
        skipped_dirty = git_automation.get("skipped_dirty_paths", []) or []
        lines.append("- Skipped pre-existing dirty files: " + (", ".join(skipped_dirty) if skipped_dirty else "none"))
        skip_reason = str(git_automation.get("skip_reason") or "")
        if skip_reason:
            lines.append(f"- Skip/failure reason: {skip_reason}")
        committed_sha = str(git_automation.get("committed_sha") or "")
        if committed_sha:
            lines.append(f"- Commit SHA: `{committed_sha}`")
        if git_automation.get("push_attempted"):
            lines.append(
                f"- Push outcome: {'succeeded' if git_automation.get('push_succeeded') else 'failed'}"
            )
    else:
        lines.append("- none")
    lines.extend(["", "## Live Runtime Alignment", ""])
    lines.append(
        "- Structured machine-truth inputs only: "
        + ("yes" if live_runtime_alignment.get("machine_truth_fingerprint_uses_structured_inputs_only") else "no")
    )
    lines.append(
        "- Runtime shape matches manifest: "
        + ("yes" if live_runtime_alignment.get("runtime_shape_matches_manifest") else "no")
    )
    runtime_state_mismatches = live_runtime_alignment.get("runtime_state_mismatches", []) or []
    if runtime_state_mismatches:
        for mismatch in runtime_state_mismatches:
            lines.append(
                "- Runtime state mismatch: "
                f"{mismatch.get('name', 'runtime')} is {mismatch.get('live_state', 'unknown')}, "
                f"expected {mismatch.get('expected_default_state', 'unknown')}"
            )
    else:
        lines.append("- Runtime state mismatches: none")
    lines.append(
        "- Live log/runtime health is reflected in `latest_health_state.json` and does not trigger stale-context drift by itself."
    )
    lines.extend(["", "## Health Findings", ""])
    findings = health_state.get("health_findings", []) or []
    if findings:
        for finding in findings:
            lines.append(
                f"- [{finding.get('severity', 'unknown')}] {finding.get('summary', 'unspecified finding')}"
            )
    else:
        lines.append("- none")
    unresolved = run_state.get("unresolved_items", []) or []
    lines.extend(["", "## Unresolved", ""])
    if unresolved:
        for item in unresolved:
            lines.append(f"- {item}")
    else:
        lines.append("- none")
    return "\n".join(lines) + "\n"


def execute_dream_loop(
    config: DreamLoopConfig,
    *,
    now_fn: Callable[[str], datetime] = _now,
    run_json_command: Callable[[Sequence[str]], Dict[str, Any]] = _run_json_command,
    run_text_command: Callable[[Sequence[str]], str] = _run_text_command,
    run_capture_command: GitCommandRunner = _run_capture_command,
) -> Dict[str, Any]:
    run_started_at = now_fn(config.timezone)
    generated_at = _iso(run_started_at)
    previous_truth_state = _read_json_file(config.state_dir / LATEST_TRUTH_STATE) or {}
    git_candidate_paths = _commit_candidate_repo_paths(config)
    if config.dry_run or not git_candidate_paths:
        git_preexisting_staged_changes = False
        git_pre_run_dirty_entries: Dict[str, str] = {}
    else:
        git_preexisting_staged_changes = _git_has_preexisting_staged_changes(run_capture_command=run_capture_command)
        git_pre_run_dirty_entries = _git_status_entries_for_paths(
            git_candidate_paths,
            run_capture_command=run_capture_command,
        )
    ctx = _build_execution_context(
        config,
        generated_at=generated_at,
        run_started_at=run_started_at,
        previous_truth_state=previous_truth_state,
        run_json_command=run_json_command,
        run_text_command=run_text_command,
    )
    registry = build_check_registry(config)
    _run_registry_checks(registry, ctx)
    _finalize_health_state(ctx)
    _finalize_stale_context_state(ctx)

    artifact_paths = [
        str(config.state_dir / LATEST_TRUTH_STATE),
        str(config.state_dir / LATEST_HEALTH_STATE),
        str(config.state_dir / LATEST_RUN_STATE),
        str(config.state_dir / LATEST_REPORT),
    ]
    if ctx.summary_changed_fields:
        ctx.files_updated.append(str(config.summary_path))

    run_finished_at = now_fn(config.timezone)
    git_automation = _build_git_automation_result(
        status="dry_run_not_attempted" if config.dry_run else "not_attempted_yet",
        candidate_paths=git_candidate_paths,
        skipped_dirty_paths=[],
        safe_paths=[],
        commit_attempted=False,
        skip_reason="dry-run mode" if config.dry_run else "",
        preexisting_staged_changes=git_preexisting_staged_changes,
    )
    run_status = "dry_run_succeeded" if config.dry_run else "succeeded"
    run_state: Dict[str, Any] = {
        "generated_at": _iso(run_finished_at),
        "timezone": config.timezone,
        "run_started_at": generated_at,
        "run_finished_at": _iso(run_finished_at),
        "run_status": run_status,
        "dry_run": config.dry_run,
        "checks_executed": list(ctx.checks_executed),
        "skipped_checks": list(ctx.skipped_checks),
        "artifacts_written": [] if config.dry_run else artifact_paths,
        "planned_artifacts": artifact_paths,
        "files_updated": [] if config.dry_run else list(ctx.files_updated),
        "warnings_emitted": list(ctx.warnings_emitted),
        "unresolved_items": list(ctx.unresolved_items),
        "git_automation": git_automation,
    }
    effective_summary_changed_fields = list(ctx.summary_changed_fields) if config.dry_run else []
    ctx.truth_state["secondary_doc_alignment"] = _render_secondary_doc_alignment(
        summary_path=config.summary_path,
        summary_changed_fields=effective_summary_changed_fields,
    )
    ctx.truth_state["generated_output_status"] = _render_generated_output_status(
        report_path=config.state_dir / LATEST_REPORT,
    )
    report_text = _build_report(truth_state=ctx.truth_state, health_state=ctx.health_state, run_state=run_state)

    if not config.dry_run:
        config.state_dir.mkdir(parents=True, exist_ok=True)
        if ctx.summary_changed_fields:
            _atomic_write_text(config.summary_path, ctx.aligned_summary_text)
        _atomic_write_json(config.state_dir / LATEST_TRUTH_STATE, ctx.truth_state)
        _atomic_write_json(config.state_dir / LATEST_HEALTH_STATE, ctx.health_state)
        _atomic_write_json(config.state_dir / LATEST_RUN_STATE, run_state)
        _atomic_write_text(config.state_dir / LATEST_REPORT, report_text)
        verification_mismatches = _verify_persisted_outputs(
            truth_state_path=config.state_dir / LATEST_TRUTH_STATE,
            expected_truth_state=ctx.truth_state,
            health_state_path=config.state_dir / LATEST_HEALTH_STATE,
            expected_health_state=ctx.health_state,
            run_state_path=config.state_dir / LATEST_RUN_STATE,
            expected_run_state=run_state,
            report_path=config.state_dir / LATEST_REPORT,
            expected_report_text=report_text,
            summary_path=config.summary_path,
            expected_summary_text=ctx.aligned_summary_text if ctx.summary_changed_fields else None,
        )
        if verification_mismatches:
            raise RuntimeError("dream loop output verification failed: " + "; ".join(verification_mismatches))

        git_automation = _run_git_automation(
            config=config,
            run_capture_command=run_capture_command,
            generated_at=generated_at,
            candidate_paths=git_candidate_paths,
            preexisting_staged_changes=git_preexisting_staged_changes,
            pre_run_dirty_entries=git_pre_run_dirty_entries,
        )
        run_state["git_automation"] = git_automation
        if git_automation["status"] == "commit_failed":
            run_state["run_status"] = "succeeded_with_git_commit_failure"
        elif git_automation["status"] == "push_failed":
            run_state["run_status"] = "succeeded_with_git_push_failure"
        report_text = _build_report(truth_state=ctx.truth_state, health_state=ctx.health_state, run_state=run_state)
        _atomic_write_json(config.state_dir / LATEST_RUN_STATE, run_state)
        _atomic_write_text(config.state_dir / LATEST_REPORT, report_text)
        final_verification_mismatches = _verify_persisted_outputs(
            truth_state_path=config.state_dir / LATEST_TRUTH_STATE,
            expected_truth_state=ctx.truth_state,
            health_state_path=config.state_dir / LATEST_HEALTH_STATE,
            expected_health_state=ctx.health_state,
            run_state_path=config.state_dir / LATEST_RUN_STATE,
            expected_run_state=run_state,
            report_path=config.state_dir / LATEST_REPORT,
            expected_report_text=report_text,
            summary_path=config.summary_path,
            expected_summary_text=ctx.aligned_summary_text if ctx.summary_changed_fields else None,
        )
        if final_verification_mismatches:
            raise RuntimeError("dream loop output verification failed: " + "; ".join(final_verification_mismatches))

    return {
        "truth_state": ctx.truth_state,
        "health_state": ctx.health_state,
        "run_state": run_state,
        "report_text": report_text,
    }


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=str(path.parent), delete=False) as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
        tmp_path = Path(handle.name)
    os.replace(tmp_path, path)


def _atomic_write_json(path: Path, payload: Dict[str, Any]) -> None:
    _atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    config = DreamLoopConfig(
        state_dir=args.state_dir,
        bridge_state_dir=args.bridge_state_dir,
        timezone=args.timezone,
        dry_run=bool(args.dry_run),
        summary_path=args.summary_path,
    )
    result = execute_dream_loop(config)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(result["report_text"], end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
