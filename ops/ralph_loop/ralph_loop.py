#!/usr/bin/env python3
"""Ralph loop: rank and execute live optimization targets from bridge telemetry.

Ralph = Reliability, Availability, Latency, Price, Health.

The loop continuously measures live bridge behavior, ranks the most valuable
operational optimization targets, and can run one bounded optimization pass
against the current top target before re-ranking.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import shlex
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request

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


RALPH_NAME = os.getenv("RALPH_LOOP_NAME", "Server3 Ralph Autopilot").strip() or "Server3 Ralph Autopilot"
TZ_NAME = os.getenv("RALPH_LOOP_TZ", "Australia/Brisbane")
STATE_DIR = Path(os.getenv("RALPH_LOOP_STATE_DIR", "/var/lib/server3-ralph-loop"))
TELEGRAM_UNIT = os.getenv("RALPH_LOOP_TELEGRAM_UNIT", "telegram-architect-bridge.service").strip()
WINDOW_HOURS = max(1, int(os.getenv("RALPH_LOOP_WINDOW_HOURS", "6") or "6"))
LOW_AGENCY_REPEAT_THRESHOLD = max(1, int(os.getenv("RALPH_LOOP_LOW_AGENCY_REPEAT_THRESHOLD", "3") or "3"))
LOW_AGENCY_SCORE_FLOOR = max(0, int(os.getenv("RALPH_LOOP_LOW_AGENCY_SCORE_FLOOR", "90") or "90"))
LOW_AGENCY_SCORE_PENALTY = max(0, int(os.getenv("RALPH_LOOP_LOW_AGENCY_SCORE_PENALTY", "35") or "35"))
LATEST_REPORT_PATH = STATE_DIR / "latest.md"
LATEST_BACKLOG_PATH = STATE_DIR / "optimization_backlog.json"
HISTORY_PATH = STATE_DIR / "history.jsonl"
RESULTS_PATH = STATE_DIR / "execution_results.jsonl"
REPORTS_DIR = STATE_DIR / "reports"
DEFAULT_EXECUTOR_CMD = [str(ROOT / "src" / "telegram_bridge" / "executor.sh"), "new"]
DEFAULT_QA_PYTHON = ROOT / ".venv" / "server3-qa" / "bin" / "python"
DAILY_REPORT_HOURS = max(1, int(os.getenv("RALPH_LOOP_DAILY_REPORT_HOURS", "24") or "24"))


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


LOW_AGENCY_CANDIDATES = {"codex_exec_latency"}


@dataclass(frozen=True)
class ExecutionHandler:
    candidate_id: str
    summary: str
    verification_commands: List[List[str]]
    guidance: str


@dataclass(frozen=True)
class VerificationResult:
    command: List[str]
    returncode: int
    stdout: str
    stderr: str


@dataclass(frozen=True)
class ExecutionResult:
    observed_at_utc: str
    selected_candidate_id: Optional[str]
    selected_candidate_score: int
    handler_found: bool
    status: str
    summary: str
    codex_returncode: Optional[int]
    codex_stdout: str
    codex_stderr: str
    verification_results: List[Dict[str, object]]
    changed_files: List[str]
    preexisting_dirty_files: List[str]
    git_head_before: str
    git_head_after: str
    commit_message: str = ""
    committed_sha: str = ""
    push_succeeded: bool = False
    push_stdout: str = ""
    push_stderr: str = ""
    report_only: bool = False


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def ensure_state_dir() -> None:
    global STATE_DIR, LATEST_REPORT_PATH, LATEST_BACKLOG_PATH, HISTORY_PATH, RESULTS_PATH, REPORTS_DIR
    fallback = Path(
        os.getenv(
            "RALPH_LOOP_FALLBACK_STATE_DIR",
            str(ROOT / ".state" / "server3-ralph-loop"),
        )
    )

    def _switch_to_fallback() -> None:
        nonlocal fallback
        global STATE_DIR, LATEST_REPORT_PATH, LATEST_BACKLOG_PATH, HISTORY_PATH, RESULTS_PATH
        if fallback == STATE_DIR:
            raise PermissionError(f"state dir is not writable: {STATE_DIR}")
        STATE_DIR = fallback
        LATEST_REPORT_PATH = STATE_DIR / "latest.md"
        LATEST_BACKLOG_PATH = STATE_DIR / "optimization_backlog.json"
        HISTORY_PATH = STATE_DIR / "history.jsonl"
        RESULTS_PATH = STATE_DIR / "execution_results.jsonl"
        REPORTS_DIR = STATE_DIR / "reports"
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
    except PermissionError:
        _switch_to_fallback()
        return
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    if os.access(STATE_DIR, os.W_OK | os.X_OK):
        return
    _switch_to_fallback()


def parse_json_lines(text: str) -> Iterable[Dict[str, object]]:
    return runtime_observer.parse_json_lines(text)


def run_command(args: List[str]) -> str:
    proc = subprocess.run(args, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        stderr = proc.stderr.strip()
        raise RuntimeError(f"command failed ({' '.join(args)}): {stderr}")
    return proc.stdout


def run_command_capture(
    args: Sequence[str],
    *,
    input_text: Optional[str] = None,
    cwd: Optional[Path] = None,
    env: Optional[Dict[str, str]] = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(args),
        input=input_text,
        capture_output=True,
        text=True,
        check=False,
        cwd=str(cwd) if cwd else None,
        env=env,
    )


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


def recent_repeat_count(results: Sequence["ExecutionResult"], candidate_id: str) -> int:
    count = 0
    for item in reversed(results):
        if item.selected_candidate_id != candidate_id:
            break
        count += 1
    return count


def apply_low_agency_cooldowns(
    candidates: Sequence[Candidate],
    *,
    recent_results: Sequence["ExecutionResult"],
) -> List[Candidate]:
    adjusted: List[Candidate] = []
    for item in candidates:
        if item.id not in LOW_AGENCY_CANDIDATES or item.score < LOW_AGENCY_SCORE_FLOOR:
            adjusted.append(item)
            continue
        repeat_count = recent_repeat_count(recent_results, item.id)
        if repeat_count < LOW_AGENCY_REPEAT_THRESHOLD:
            adjusted.append(item)
            continue
        cooldown_evidence = dict(item.evidence)
        cooldown_evidence["low_agency_repeat_count"] = repeat_count
        cooldown_evidence["low_agency_penalty"] = LOW_AGENCY_SCORE_PENALTY
        adjusted.append(
            Candidate(
                id=item.id,
                title=item.title,
                score=max(0, item.score - LOW_AGENCY_SCORE_PENALTY),
                category=item.category,
                why=item.why,
                next_action=(
                    item.next_action
                    + " Ralph cooldown applied after repeated high-score low-agency passes; prefer another local target this round."
                ),
                evidence=cooldown_evidence,
                target_paths=item.target_paths,
            )
        )
    return sorted(adjusted, key=lambda item: item.score, reverse=True)


def qa_python_command() -> List[str]:
    override = os.getenv("RALPH_LOOP_QA_PYTHON", "").strip()
    if override:
        return shlex.split(override)
    if DEFAULT_QA_PYTHON.exists():
        return [str(DEFAULT_QA_PYTHON)]
    return ["python3"]


def pytest_command(*args: str) -> List[str]:
    return qa_python_command() + ["-m", "pytest", *args]


EXECUTION_HANDLERS: Dict[str, ExecutionHandler] = {
    "codex_exec_latency": ExecutionHandler(
        candidate_id="codex_exec_latency",
        summary="Inspect Codex executor hot paths and land one concrete latency improvement.",
        verification_commands=[
            pytest_command("tests/telegram_bridge/test_executor.py", "-q"),
            pytest_command("tests/telegram_bridge/test_executor_phase_breakdown.py", "-q"),
            pytest_command("tests/runtime_observer/test_ralph_loop.py", "-q"),
        ],
        guidance=(
            "Prefer setup, retry, or wrapper overhead reductions before changing model behavior. "
            "Keep the change scoped to executor/runtime paths plus directly affected tests."
        ),
    ),
    "progress_edit_noise": ExecutionHandler(
        candidate_id="progress_edit_noise",
        summary="Reduce Telegram progress edit volume without regressing visible progress quality.",
        verification_commands=[
            pytest_command("tests/telegram_bridge/test_handler_progress.py", "-q"),
            pytest_command("tests/telegram_bridge/test_executor.py", "-q"),
            pytest_command("tests/runtime_observer/test_ralph_loop.py", "-q"),
        ],
        guidance=(
            "Prefer throttling, deduplication, or compact progress semantics over removing progress entirely. "
            "Keep user-facing behavior intact while lowering edit count."
        ),
    ),
}


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


def parse_iso_utc(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def save_history(record: Dict[str, object]) -> None:
    ensure_state_dir()
    with open(HISTORY_PATH, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True, ensure_ascii=True))
        handle.write("\n")


def save_execution_result(result: ExecutionResult) -> None:
    ensure_state_dir()
    with open(RESULTS_PATH, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(asdict(result), sort_keys=True, ensure_ascii=True))
        handle.write("\n")


def write_outputs(report: str, backlog: Dict[str, object]) -> None:
    ensure_state_dir()
    with open(LATEST_REPORT_PATH, "w", encoding="utf-8") as handle:
        handle.write(report)
    with open(LATEST_BACKLOG_PATH, "w", encoding="utf-8") as handle:
        json.dump(backlog, handle, indent=2, sort_keys=True)
        handle.write("\n")


def collect_snapshot(*, persist: bool) -> Dict[str, object]:
    observed_at = now_utc()
    since_dt = observed_at - timedelta(hours=WINDOW_HOURS)
    snapshot = runtime_observer.build_snapshot(observed_at)
    rows = load_bridge_events(TELEGRAM_UNIT, since_dt)
    raw_candidates = build_candidates(rows)
    recent_results = load_execution_results()
    candidates = apply_low_agency_cooldowns(raw_candidates, recent_results=recent_results)
    backlog = {
        "observed_at_utc": observed_at.isoformat(),
        "timezone": TZ_NAME,
        "telegram_unit": TELEGRAM_UNIT,
        "window_hours": WINDOW_HOURS,
        "candidate_count": len(candidates),
        "top_candidate_id": candidates[0].id if candidates else None,
        "candidates": [asdict(item) for item in candidates],
        "raw_top_candidate_id": raw_candidates[0].id if raw_candidates else None,
        "kpi_snapshot": snapshot.get("kpis", {}),
    }
    report = format_report(
        observed_at=observed_at,
        unit=TELEGRAM_UNIT,
        window_hours=WINDOW_HOURS,
        snapshot=snapshot,
        candidates=candidates,
    )
    if persist:
        write_outputs(report, backlog)
        save_history(backlog)
    return {
        "observed_at": observed_at,
        "snapshot": snapshot,
        "rows": rows,
        "candidates": candidates,
        "backlog": backlog,
        "report": report,
    }


def load_execution_results(*, since_dt: Optional[datetime] = None) -> List[ExecutionResult]:
    ensure_state_dir()
    if not RESULTS_PATH.exists():
        return []
    rows: List[ExecutionResult] = []
    for line in RESULTS_PATH.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        payload.setdefault("preexisting_dirty_files", [])
        payload.setdefault("commit_message", "")
        payload.setdefault("committed_sha", "")
        payload.setdefault("push_succeeded", False)
        payload.setdefault("push_stdout", "")
        payload.setdefault("push_stderr", "")
        payload.setdefault("report_only", False)
        observed_dt = parse_iso_utc(payload.get("observed_at_utc"))
        if since_dt and observed_dt and observed_dt < since_dt:
            continue
        rows.append(ExecutionResult(**payload))
    return rows


def find_candidate(candidates: Sequence[Candidate], candidate_id: Optional[str]) -> Optional[Candidate]:
    if candidate_id:
        for item in candidates:
            if item.id == candidate_id:
                return item
        return None
    return candidates[0] if candidates else None


def build_execution_prompt(candidate: Candidate, handler: ExecutionHandler) -> str:
    verification_lines = "\n".join(f"- {shlex.join(command)}" for command in handler.verification_commands)
    target_paths = "\n".join(f"- {path}" for path in candidate.target_paths)
    return (
        "Ralph Execute mode.\n\n"
        "Goal:\n"
        f"- Candidate: {candidate.id}\n"
        f"- Title: {candidate.title}\n"
        f"- Score: {candidate.score}\n"
        f"- Category: {candidate.category}\n"
        f"- Why: {candidate.why}\n"
        f"- Guidance: {handler.guidance}\n"
        f"- Suggested next action: {candidate.next_action}\n"
        f"- Evidence: {json.dumps(candidate.evidence, sort_keys=True)}\n\n"
        "Target paths for this pass:\n"
        f"{target_paths}\n\n"
        "Execution contract for this pass:\n"
        "- Make one concrete optimization pass for this candidate.\n"
        "- Prefer the smallest change that produces a measurable operational win.\n"
        "- Run the relevant verification yourself before finishing.\n"
        "- Do not commit or push; Ralph handles that after verification.\n"
        "- If no safe improvement is justified, leave the tree unchanged and say so plainly.\n\n"
        "Required verification commands:\n"
        f"{verification_lines}\n\n"
        "Final response format:\n"
        "1. Outcome\n"
        "2. Files changed\n"
        "3. Verification run\n"
        "4. Remaining risk\n"
    )


def executor_command() -> List[str]:
    override = os.getenv("RALPH_LOOP_EXECUTOR_CMD", "").strip()
    if override:
        return shlex.split(override)
    return list(DEFAULT_EXECUTOR_CMD)


def git_head() -> str:
    proc = run_command_capture(["git", "rev-parse", "HEAD"], cwd=ROOT)
    if proc.returncode != 0:
        return ""
    return proc.stdout.strip()


def current_branch() -> str:
    proc = run_command_capture(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=ROOT)
    if proc.returncode != 0:
        return ""
    return proc.stdout.strip()


def git_status_entries(paths: Optional[Sequence[str]] = None) -> Dict[str, str]:
    args = ["git", "status", "--short"]
    if paths:
        args.extend(["--"] + list(paths))
    proc = run_command_capture(args, cwd=ROOT)
    if proc.returncode != 0:
        return {}
    entries: Dict[str, str] = {}
    for line in proc.stdout.splitlines():
        if len(line) < 4:
            continue
        entries[line[3:].strip()] = line[:2]
    return entries


def changed_files_since(before: Dict[str, str], after: Dict[str, str]) -> List[str]:
    changed = set(after) - set(before)
    for path, status in after.items():
        if before.get(path) != status:
            changed.add(path)
    return sorted(changed)


def file_content_signature(path: str) -> str:
    full_path = ROOT / path
    if not full_path.exists() or not full_path.is_file():
        return ""
    digest = hashlib.sha256()
    digest.update(full_path.read_bytes())
    return digest.hexdigest()


def snapshot_file_signatures(paths: Sequence[str]) -> Dict[str, str]:
    return {path: file_content_signature(path) for path in paths}


def commit_message_for_candidate(candidate: Candidate) -> str:
    return f"Ralph: {candidate.title}"


def commit_and_push(commit_message: str, paths: Sequence[str]) -> tuple[str, bool, str, str]:
    if not paths:
        return "", False, "", ""
    add_proc = run_command_capture(["git", "add", "--", *paths], cwd=ROOT)
    if add_proc.returncode != 0:
        return "", False, add_proc.stdout, add_proc.stderr
    commit_proc = run_command_capture(["git", "commit", "-m", commit_message], cwd=ROOT)
    if commit_proc.returncode != 0:
        return "", False, commit_proc.stdout, commit_proc.stderr
    committed_sha = git_head()
    branch = current_branch() or "main"
    push_proc = run_command_capture(["git", "push", "origin", branch], cwd=ROOT)
    return committed_sha, push_proc.returncode == 0, push_proc.stdout, push_proc.stderr


def telegram_target(prefix: str) -> tuple[str, str]:
    chat_id = os.getenv(f"{prefix}_CHAT_ID", "").strip()
    thread_id = os.getenv(f"{prefix}_TOPIC_ID", "").strip()
    return chat_id, thread_id


def send_telegram_message(text: str, *, prefix: str) -> bool:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    api_base = os.getenv("TELEGRAM_API_BASE", "https://api.telegram.org").rstrip("/")
    chat_id, thread_id = telegram_target(prefix)
    if not token or not chat_id:
        return False
    payload = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": "true",
    }
    if thread_id:
        payload["message_thread_id"] = thread_id
    data = urllib_parse.urlencode(payload).encode("utf-8")
    request = urllib_request.Request(
        f"{api_base}/bot{token}/sendMessage",
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib_request.urlopen(request, timeout=20) as response:
            _ = response.read()
    except urllib_error.URLError:
        return False
    return True


def send_telegram_document(document_path: Path, caption: str, *, prefix: str) -> bool:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    api_base = os.getenv("TELEGRAM_API_BASE", "https://api.telegram.org").rstrip("/")
    chat_id, thread_id = telegram_target(prefix)
    if not token or not chat_id or not document_path.exists():
        return False
    boundary = "ralphboundary"
    body = bytearray()

    def add_field(name: str, value: str) -> None:
        body.extend(f"--{boundary}\r\n".encode("utf-8"))
        body.extend(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8"))
        body.extend(value.encode("utf-8"))
        body.extend(b"\r\n")

    add_field("chat_id", chat_id)
    if thread_id:
        add_field("message_thread_id", thread_id)
    add_field("caption", caption[:1024])
    body.extend(f"--{boundary}\r\n".encode("utf-8"))
    body.extend(
        (
            f'Content-Disposition: form-data; name="document"; filename="{document_path.name}"\r\n'
            "Content-Type: text/markdown\r\n\r\n"
        ).encode("utf-8")
    )
    body.extend(document_path.read_bytes())
    body.extend(b"\r\n")
    body.extend(f"--{boundary}--\r\n".encode("utf-8"))
    request = urllib_request.Request(
        f"{api_base}/bot{token}/sendDocument",
        data=bytes(body),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    try:
        with urllib_request.urlopen(request, timeout=30) as response:
            _ = response.read()
    except urllib_error.URLError:
        return False
    return True


def run_verification_commands(commands: Sequence[Sequence[str]]) -> List[VerificationResult]:
    results: List[VerificationResult] = []
    for command in commands:
        proc = run_command_capture(command, cwd=ROOT)
        results.append(
            VerificationResult(
                command=list(command),
                returncode=proc.returncode,
                stdout=proc.stdout,
                stderr=proc.stderr,
            )
        )
        if proc.returncode != 0:
            break
    return results


def build_execution_result(
    *,
    observed_at: datetime,
    selected_candidate_id: Optional[str],
    selected_candidate_score: int,
    handler_found: bool,
    status: str,
    summary: str,
    codex_returncode: Optional[int],
    codex_stdout: str,
    codex_stderr: str,
    verification_results: List[VerificationResult],
    changed_files: List[str],
    preexisting_dirty_files: List[str],
    git_head_before: str,
    git_head_after: str,
    commit_message: str = "",
    committed_sha: str = "",
    push_succeeded: bool = False,
    push_stdout: str = "",
    push_stderr: str = "",
    report_only: bool = False,
) -> ExecutionResult:
    return ExecutionResult(
        observed_at_utc=observed_at.isoformat(),
        selected_candidate_id=selected_candidate_id,
        selected_candidate_score=selected_candidate_score,
        handler_found=handler_found,
        status=status,
        summary=summary,
        codex_returncode=codex_returncode,
        codex_stdout=codex_stdout,
        codex_stderr=codex_stderr,
        verification_results=[
            {
                "command": result.command,
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }
            for result in verification_results
        ],
        changed_files=changed_files,
        preexisting_dirty_files=preexisting_dirty_files,
        git_head_before=git_head_before,
        git_head_after=git_head_after,
        commit_message=commit_message,
        committed_sha=committed_sha,
        push_succeeded=push_succeeded,
        push_stdout=push_stdout,
        push_stderr=push_stderr,
        report_only=report_only,
    )


def format_execution_update(result: ExecutionResult) -> str:
    lines = [
        f"[{RALPH_NAME}] hourly execute update",
        f"status={result.status}",
        f"candidate={result.selected_candidate_id or '-'}",
    ]
    if result.changed_files:
        lines.append(f"changed={', '.join(result.changed_files)}")
    if result.preexisting_dirty_files:
        lines.append(f"preexisting_dirty={', '.join(result.preexisting_dirty_files[:8])}")
    if result.committed_sha:
        push_state = "pushed" if result.push_succeeded else "push_failed"
        lines.append(f"commit={result.committed_sha[:7]} {push_state}")
    lines.append(f"summary={result.summary}")
    return "\n".join(lines)


def render_daily_report(*, observed_at: datetime, results: Sequence[ExecutionResult], backlog: Dict[str, object]) -> str:
    local_observed = observed_at.astimezone(runtime_observer.ZoneInfo(TZ_NAME)).isoformat()
    applied = [item for item in results if item.status == "applied"]
    blocked = [item for item in results if item.status not in {"applied", "no_change"}]
    lines = [
        f"# {RALPH_NAME} Daily Report",
        "",
        f"- Observed at: {local_observed}",
        f"- Window: last {DAILY_REPORT_HOURS} hour(s)",
        f"- Total runs: {len(results)}",
        f"- Applied: {len(applied)}",
        f"- Blocked/attention: {len(blocked)}",
        "",
        "## Current Top Target",
    ]
    top_candidate_id = backlog.get("top_candidate_id")
    if top_candidate_id:
        lines.append(f"- `{top_candidate_id}`")
    else:
        lines.append("- none")

    lines.extend(["", "## Runs"])
    if not results:
        lines.append("- No Ralph execute results in this window.")
    for item in results:
        observed = parse_iso_utc(item.observed_at_utc)
        observed_local = observed.astimezone(runtime_observer.ZoneInfo(TZ_NAME)).isoformat() if observed else item.observed_at_utc
        lines.append(f"- {observed_local} status={item.status} candidate={item.selected_candidate_id or '-'}")
        if item.changed_files:
            lines.append(f"  changed: {', '.join(item.changed_files)}")
        if item.committed_sha:
            push_state = "pushed" if item.push_succeeded else "push_failed"
            lines.append(f"  commit: {item.committed_sha} {push_state}")
        if item.preexisting_dirty_files:
            lines.append(f"  preexisting dirty: {', '.join(item.preexisting_dirty_files[:8])}")
        lines.append(f"  summary: {item.summary}")

    lines.extend(["", "## Important Info"])
    if blocked:
        for item in blocked[:10]:
            lines.append(f"- attention: status={item.status} candidate={item.selected_candidate_id or '-'} summary={item.summary}")
    else:
        lines.append("- No blocked Ralph runs in this window.")

    return "\n".join(lines) + "\n"


def write_daily_report(observed_at: datetime, text: str) -> Path:
    ensure_state_dir()
    report_path = REPORTS_DIR / f"ralph-daily-{observed_at.astimezone(runtime_observer.ZoneInfo(TZ_NAME)).date().isoformat()}.md"
    report_path.write_text(text, encoding="utf-8")
    return report_path


def notify_daily_report() -> int:
    observed_at = now_utc()
    since_dt = observed_at - timedelta(hours=DAILY_REPORT_HOURS)
    results = load_execution_results(since_dt=since_dt)
    collected = collect_snapshot(persist=True)
    report_text = render_daily_report(
        observed_at=observed_at,
        results=results,
        backlog=collected["backlog"],
    )
    report_path = write_daily_report(observed_at, report_text)
    sent = send_telegram_document(
        report_path,
        f"{RALPH_NAME} daily report",
        prefix="RALPH_LOOP_DAILY_REPORT",
    )
    if not sent:
        raise RuntimeError(f"failed to send daily report document: {report_path}")
    print(report_path)
    return 0


def execute_candidate(candidate: Candidate, handler: ExecutionHandler, observed_at: datetime) -> ExecutionResult:
    prompt = build_execution_prompt(candidate, handler)
    worktree_before = git_status_entries()
    dirty_before = sorted(worktree_before)
    dirty_before_signatures = snapshot_file_signatures(dirty_before)
    head_before = git_head()
    codex_proc = run_command_capture(executor_command(), input_text=prompt, cwd=ROOT)
    worktree_after = git_status_entries()
    changed_files = changed_files_since(worktree_before, worktree_after)
    for path in dirty_before:
        if file_content_signature(path) != dirty_before_signatures.get(path, "") and path not in changed_files:
            changed_files.append(path)
    changed_files = sorted(changed_files)
    verification_results = run_verification_commands(handler.verification_commands)
    head_after = git_head()

    status = "applied"
    summary = "Optimization applied and verification passed."
    commit_message = ""
    committed_sha = ""
    push_succeeded = False
    push_stdout = ""
    push_stderr = ""
    report_only = False
    if codex_proc.returncode != 0:
        status = "blocked"
        summary = "Codex execute pass failed before verification completed."
    elif not changed_files:
        status = "no_change"
        summary = "Codex completed without changing target files."
    elif any(result.returncode != 0 for result in verification_results):
        status = "qa_failed"
        summary = "Optimization changed files but verification failed."
    else:
        dirty_overlap = sorted(set(dirty_before) & set(changed_files))
        if dirty_overlap:
            report_only = True
            summary = (
                "Optimization applied and verified, but Ralph left it uncommitted because the run touched files "
                "that were already dirty before execution."
            )
        else:
            commit_message = commit_message_for_candidate(candidate)
            committed_sha, push_succeeded, push_stdout, push_stderr = commit_and_push(
                commit_message,
                changed_files,
            )
            head_after = git_head()
            if not committed_sha:
                status = "commit_failed"
                summary = "Optimization passed verification but Ralph could not create the commit."
            elif not push_succeeded:
                status = "push_failed"
                summary = "Optimization passed verification and was committed locally, but push failed."

    return build_execution_result(
        observed_at=observed_at,
        selected_candidate_id=candidate.id,
        selected_candidate_score=candidate.score,
        handler_found=True,
        status=status,
        summary=summary,
        codex_returncode=codex_proc.returncode,
        codex_stdout=codex_proc.stdout,
        codex_stderr=codex_proc.stderr,
        verification_results=verification_results,
        changed_files=changed_files,
        preexisting_dirty_files=dirty_before,
        git_head_before=head_before,
        git_head_after=head_after,
        commit_message=commit_message,
        committed_sha=committed_sha,
        push_succeeded=push_succeeded,
        push_stdout=push_stdout,
        push_stderr=push_stderr,
        report_only=report_only,
    )


def execute_once(*, candidate_id: Optional[str]) -> int:
    collected = collect_snapshot(persist=True)
    candidates = collected["candidates"]
    observed_at = collected["observed_at"]
    selected = find_candidate(candidates, candidate_id)
    if selected is None:
        result = build_execution_result(
            observed_at=observed_at,
            selected_candidate_id=candidate_id,
            selected_candidate_score=0,
            handler_found=False,
            status="blocked",
            summary="Requested candidate was not present in the fresh backlog.",
            codex_returncode=None,
            codex_stdout="",
            codex_stderr="",
            verification_results=[],
            changed_files=[],
            preexisting_dirty_files=[],
            git_head_before=git_head(),
            git_head_after=git_head(),
        )
        save_execution_result(result)
        print(result.summary)
        return 1

    handler = EXECUTION_HANDLERS.get(selected.id)
    if handler is None:
        result = build_execution_result(
            observed_at=observed_at,
            selected_candidate_id=selected.id,
            selected_candidate_score=selected.score,
            handler_found=False,
            status="blocked",
            summary="Fresh top candidate has no registered execution handler.",
            codex_returncode=None,
            codex_stdout="",
            codex_stderr="",
            verification_results=[],
            changed_files=[],
            preexisting_dirty_files=[],
            git_head_before=git_head(),
            git_head_after=git_head(),
        )
        save_execution_result(result)
        print(result.summary)
        return 1

    result = execute_candidate(selected, handler, observed_at)
    save_execution_result(result)
    collect_snapshot(persist=True)
    send_telegram_message(format_execution_update(result), prefix="RALPH_LOOP_NOTIFY")
    print(json.dumps(asdict(result), indent=2, sort_keys=True))
    return 0 if result.status in {"applied", "no_change"} else 1


def collect_once() -> int:
    collected = collect_snapshot(persist=True)
    print(collected["report"], end="")
    return 0


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Ralph loop for live operational optimization ranking and execution."
    )
    parser.add_argument("command", choices=("collect", "execute", "notify-daily"))
    parser.add_argument("--candidate-id", dest="candidate_id")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_arg_parser().parse_args(argv)
    if args.command == "collect":
        return collect_once()
    if args.command == "execute":
        return execute_once(candidate_id=args.candidate_id)
    if args.command == "notify-daily":
        return notify_daily_report()
    raise RuntimeError(f"unsupported command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
