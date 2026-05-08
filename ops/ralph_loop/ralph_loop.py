#!/usr/bin/env python3
"""Ralph loop: rank live optimization targets from bridge telemetry.

Ralph = Reliability, Availability, Latency, Price, Health.

The loop is intentionally bounded. It does not edit code or deploy changes by
itself. It continuously measures live bridge behavior, ranks the most valuable
operational optimization targets, and refreshes a machine-readable backlog plus
an operator-facing report.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional

ROOT = Path(__file__).resolve().parents[2]


def _load_runtime_observer():
    module_path = ROOT / "ops" / "runtime_observer" / "runtime_observer.py"
    spec = importlib.util.spec_from_file_location("runtime_observer", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load runtime_observer module spec")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


runtime_observer = _load_runtime_observer()


TZ_NAME = os.getenv("RALPH_LOOP_TZ", "Australia/Brisbane")
STATE_DIR = Path(os.getenv("RALPH_LOOP_STATE_DIR", "/var/lib/server3-ralph-loop"))
TELEGRAM_UNIT = os.getenv("RALPH_LOOP_TELEGRAM_UNIT", "telegram-architect-bridge.service").strip()
WINDOW_HOURS = max(1, int(os.getenv("RALPH_LOOP_WINDOW_HOURS", "6") or "6"))
LATEST_REPORT_PATH = STATE_DIR / "latest.md"
LATEST_BACKLOG_PATH = STATE_DIR / "optimization_backlog.json"
HISTORY_PATH = STATE_DIR / "history.jsonl"


@dataclass(frozen=True)
class Candidate:
    id: str
    title: str
    score: int
    category: str
    why: str
    next_action: str
    evidence: Dict[str, object]
    target_paths: List[str]


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def ensure_state_dir() -> None:
    global STATE_DIR, LATEST_REPORT_PATH, LATEST_BACKLOG_PATH, HISTORY_PATH
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        return
    except PermissionError:
        fallback = Path(
            os.getenv(
                "RALPH_LOOP_FALLBACK_STATE_DIR",
                str(ROOT / ".state" / "server3-ralph-loop"),
            )
        )
        if fallback == STATE_DIR:
            raise
        STATE_DIR = fallback
        LATEST_REPORT_PATH = STATE_DIR / "latest.md"
        LATEST_BACKLOG_PATH = STATE_DIR / "optimization_backlog.json"
        HISTORY_PATH = STATE_DIR / "history.jsonl"
        STATE_DIR.mkdir(parents=True, exist_ok=True)


def parse_json_lines(text: str) -> Iterable[Dict[str, object]]:
    return runtime_observer.parse_json_lines(text)


def run_command(args: List[str]) -> str:
    proc = subprocess.run(args, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        stderr = proc.stderr.strip()
        raise RuntimeError(f"command failed ({' '.join(args)}): {stderr}")
    return proc.stdout


def since_arg(dt: datetime) -> str:
    return f"@{int(dt.timestamp())}"


def load_bridge_events(unit: str, since_dt: datetime) -> List[Dict[str, object]]:
    raw = run_command(
        [
            "journalctl",
            "-u",
            unit,
            "--since",
            since_arg(since_dt),
            "--no-pager",
            "-q",
            "-o",
            "cat",
        ]
    )
    rows: List[Dict[str, object]] = []
    for row in parse_json_lines(raw):
        if isinstance(row.get("event"), str):
            rows.append(row)
    return rows


def safe_int(value: object, default: int = 0) -> int:
    return runtime_observer.safe_int(value, default=default)


def safe_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def percentile(values: List[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * p
    low = math.floor(rank)
    high = math.ceil(rank)
    if low == high:
        return ordered[low]
    weight = rank - low
    return ordered[low] * (1.0 - weight) + ordered[high] * weight


def count_events(rows: Iterable[Dict[str, object]], event_name: str) -> int:
    return sum(1 for row in rows if row.get("event") == event_name)


def phase_stats(rows: Iterable[Dict[str, object]], event_name: str, phase: str) -> Dict[str, float]:
    durations = [
        safe_float(row.get("duration_ms"))
        for row in rows
        if row.get("event") == event_name and row.get("phase") == phase
    ]
    durations = [value for value in durations if value > 0.0]
    if not durations:
        return {"count": 0.0, "avg_ms": 0.0, "p95_ms": 0.0, "max_ms": 0.0}
    return {
        "count": float(len(durations)),
        "avg_ms": round(sum(durations) / len(durations), 3),
        "p95_ms": round(percentile(durations, 0.95), 3),
        "max_ms": round(max(durations), 3),
    }


def build_candidates(rows: List[Dict[str, object]]) -> List[Candidate]:
    request_success = count_events(rows, "bridge.request_succeeded")
    request_failed = sum(
        1
        for row in rows
        if row.get("event")
        in {
            "bridge.request_failed",
            "bridge.request_timeout",
            "bridge.executor_missing",
            "bridge.request_worker_exception",
        }
    )
    request_total = request_success + request_failed
    request_fail_rate = (request_failed / request_total) * 100.0 if request_total else 0.0
    worker_capacity_rejected = count_events(rows, "bridge.worker_capacity_rejected")
    progress_edit_attempts = sum(
        max(0, safe_int(row.get("edit_attempts"), default=0))
        for row in rows
        if row.get("event") == "bridge.progress_edit_stats"
    )
    progress_edit_failures = sum(
        max(0, safe_int(row.get("edit_failures_other"), default=0))
        for row in rows
        if row.get("event") == "bridge.progress_edit_stats"
    )
    process_prompt_total = phase_stats(rows, "bridge.request_phase_timing", "process_prompt_total")
    engine_run = phase_stats(rows, "bridge.request_phase_timing", "engine_run")
    codex_exec = phase_stats(rows, "bridge.executor_phase_timing", "codex_exec")
    prompt_prepare = phase_stats(rows, "bridge.request_phase_timing", "prepare_prompt_input")

    candidates = [
        Candidate(
            id="worker_capacity_pressure",
            title="Reduce worker capacity pressure",
            score=min(100, worker_capacity_rejected * 12),
            category="capacity",
            why="Worker-capacity rejects directly drop requests under load instead of slowing gracefully.",
            next_action=(
                "Inspect worker reuse, idle-expiry, and admission policy in session_manager.py; "
                "consider queueing or more aggressive stale-worker reclamation."
            ),
            evidence={
                "worker_capacity_rejected_last_window": worker_capacity_rejected,
                "request_total_last_window": request_total,
            },
            target_paths=[
                "src/telegram_bridge/session_manager.py",
                "src/telegram_bridge/request_starts.py",
            ],
        ),
        Candidate(
            id="request_failure_rate",
            title="Lower live request failure rate",
            score=min(100, int(round(request_fail_rate * 20))),
            category="reliability",
            why="Request failures and timeouts are user-visible reliability losses.",
            next_action=(
                "Break down failure causes by timeout, executor missing, and worker exception; "
                "optimize the hottest failure path first."
            ),
            evidence={
                "request_failed_last_window": request_failed,
                "request_total_last_window": request_total,
                "request_fail_rate_percent": round(request_fail_rate, 3),
            },
            target_paths=[
                "src/telegram_bridge/prompt_runtime.py",
                "src/telegram_bridge/special_request_processing.py",
                "src/telegram_bridge/youtube_processing.py",
            ],
        ),
        Candidate(
            id="codex_exec_latency",
            title="Reduce Codex executor latency",
            score=min(100, int(round(codex_exec["p95_ms"] / 3000.0))),
            category="latency",
            why="Long Codex subprocess phases dominate end-to-end response time and hold worker capacity.",
            next_action=(
                "Inspect executor and engine-run latency spikes; target setup, auth sync, or retry paths "
                "before changing model behavior."
            ),
            evidence={
                "codex_exec": codex_exec,
                "engine_run": engine_run,
                "process_prompt_total": process_prompt_total,
            },
            target_paths=[
                "src/telegram_bridge/executor.py",
                "src/telegram_bridge/executor.sh",
                "src/telegram_bridge/prompt_runtime.py",
            ],
        ),
        Candidate(
            id="prompt_preparation_latency",
            title="Reduce prompt preparation overhead",
            score=min(100, int(round(prompt_prepare["p95_ms"] / 1500.0))),
            category="latency",
            why="Slow prompt preparation wastes time before any engine work begins and can multiply under attachment-heavy traffic.",
            next_action=(
                "Profile attachment lookup, archive fallback, and transcription/prewarm behavior in the request-entry path."
            ),
            evidence={
                "prepare_prompt_input": prompt_prepare,
                "process_prompt_total": process_prompt_total,
            },
            target_paths=[
                "src/telegram_bridge/prompt_preparation.py",
                "src/telegram_bridge/attachment_processing.py",
                "src/telegram_bridge/prompt_inputs.py",
            ],
        ),
        Candidate(
            id="progress_edit_noise",
            title="Reduce progress update noise",
            score=min(100, progress_edit_failures * 10 + max(0, progress_edit_attempts - 50)),
            category="api_noise",
            why="Excess progress edits create avoidable Telegram API work and can amplify failures during long jobs.",
            next_action=(
                "Tune progress update cadence and compact-mode behavior in handler_progress.py using observed edit-attempt volume."
            ),
            evidence={
                "progress_edit_attempts_last_window": progress_edit_attempts,
                "progress_edit_failures_other_last_window": progress_edit_failures,
            },
            target_paths=[
                "src/telegram_bridge/handler_progress.py",
                "src/telegram_bridge/response_delivery.py",
            ],
        ),
    ]
    return sorted(candidates, key=lambda item: item.score, reverse=True)


def format_report(
    *,
    observed_at: datetime,
    unit: str,
    window_hours: int,
    snapshot: Dict[str, object],
    candidates: List[Candidate],
) -> str:
    lines = [
        "# Ralph Loop",
        "",
        f"Observed at: {observed_at.astimezone(runtime_observer.ZoneInfo(TZ_NAME)).isoformat()}",
        f"Unit: {unit}",
        f"Window: last {window_hours} hour(s)",
        "",
        "## Top target",
    ]
    if candidates:
        top = candidates[0]
        lines.extend(
            [
                f"- id: `{top.id}`",
                f"- title: {top.title}",
                f"- score: {top.score}",
                f"- why: {top.why}",
                f"- next action: {top.next_action}",
                f"- target paths: {', '.join(top.target_paths)}",
                f"- evidence: `{json.dumps(top.evidence, sort_keys=True)}`",
            ]
        )
    else:
        lines.append("- no candidates")

    lines.extend(["", "## Ranked backlog"])
    for item in candidates:
        lines.append(f"- `{item.id}` score={item.score} category={item.category} title={item.title}")

    kpis = snapshot.get("kpis", {}) if isinstance(snapshot.get("kpis"), dict) else {}
    request_fail_rate = kpis.get("request_fail_rate", {})
    lines.extend(
        [
            "",
            "## Current KPI snapshot",
            f"- request_fail_rate: `{json.dumps(request_fail_rate, sort_keys=True)}`",
        ]
    )
    return "\n".join(lines) + "\n"


def save_history(record: Dict[str, object]) -> None:
    ensure_state_dir()
    with open(HISTORY_PATH, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True, ensure_ascii=True))
        handle.write("\n")


def write_outputs(report: str, backlog: Dict[str, object]) -> None:
    ensure_state_dir()
    with open(LATEST_REPORT_PATH, "w", encoding="utf-8") as handle:
        handle.write(report)
    with open(LATEST_BACKLOG_PATH, "w", encoding="utf-8") as handle:
        json.dump(backlog, handle, indent=2, sort_keys=True)
        handle.write("\n")


def collect_once() -> int:
    observed_at = now_utc()
    since_dt = observed_at - timedelta(hours=WINDOW_HOURS)
    snapshot = runtime_observer.build_snapshot(observed_at)
    rows = load_bridge_events(TELEGRAM_UNIT, since_dt)
    candidates = build_candidates(rows)
    backlog = {
        "observed_at_utc": observed_at.isoformat(),
        "timezone": TZ_NAME,
        "telegram_unit": TELEGRAM_UNIT,
        "window_hours": WINDOW_HOURS,
        "candidate_count": len(candidates),
        "top_candidate_id": candidates[0].id if candidates else None,
        "candidates": [asdict(item) for item in candidates],
        "kpi_snapshot": snapshot.get("kpis", {}),
    }
    report = format_report(
        observed_at=observed_at,
        unit=TELEGRAM_UNIT,
        window_hours=WINDOW_HOURS,
        snapshot=snapshot,
        candidates=candidates,
    )
    write_outputs(report, backlog)
    save_history(backlog)
    print(report, end="")
    return 0


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Ralph loop for live operational optimization ranking."
    )
    parser.add_argument("command", choices=("collect",))
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_arg_parser().parse_args(argv)
    if args.command == "collect":
        return collect_once()
    raise RuntimeError(f"unsupported command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
