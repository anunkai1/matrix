#!/usr/bin/env python3
"""Generic bounded task runner for end-to-end autonomous campaigns."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request

ROOT = Path(__file__).resolve().parents[2]
STATE_ROOT = Path(
    os.getenv(
        "SERVER3_MAVALI_LOOP_STATE_DIR",
        "/var/lib/server3-mavali-loop",
    )
)
FALLBACK_STATE_ROOT = Path(
    os.getenv(
        "SERVER3_MAVALI_LOOP_FALLBACK_STATE_DIR",
        str(ROOT / ".state" / "server3-mavali-loop"),
    )
)
DEFAULT_EXECUTOR_CMD = [str(ROOT / "src" / "telegram_bridge" / "executor.sh"), "new"]
DEFAULT_QA_PYTHON = ROOT / ".venv" / "server3-qa" / "bin" / "python"
DEFAULT_MAX_ATTEMPTS_PER_TASK = max(
    1,
    int(os.getenv("SERVER3_MAVALI_LOOP_MAX_ATTEMPTS_PER_TASK", "5") or "5"),
)
INTERRUPT_SIGNALS = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)
ACTIVE_CHILD_PROCESS: Optional[subprocess.Popen[str]] = None
LAST_INTERRUPT_SIGNAL: Optional[int] = None


@dataclass(frozen=True)
class CampaignTask:
    task_id: str
    title: str
    summary: str
    guidance: str
    target_paths: List[str]
    verification_commands: List[List[str]]
    on_success_commands: List[List[str]]
    on_failure_commands: List[List[str]]


@dataclass(frozen=True)
class CampaignSpec:
    campaign_id: str
    title: str
    summary: str
    tasks: List[CampaignTask]
    repo_root: str = str(ROOT)
    default_max_attempts_per_task: int = DEFAULT_MAX_ATTEMPTS_PER_TASK
    commit_prefix: str = "Mavali Loop"
    notify_prefix: str = "MAVALI_LOOP_NOTIFY"
    executor_cmd: Optional[List[str]] = None
    legacy_state_dirs: Optional[List[str]] = None
    allowed_dirty_paths: Optional[List[str]] = None


@dataclass(frozen=True)
class LoopPaths:
    state_root: Path
    campaign_dir: Path
    state_path: Path
    results_path: Path
    report_path: Path
    log_path: Path


@dataclass(frozen=True)
class VerificationResult:
    command: List[str]
    returncode: int
    stdout: str
    stderr: str


@dataclass(frozen=True)
class AttemptResult:
    observed_at_utc: str
    task_id: str
    attempt: int
    status: str
    summary: str
    codex_returncode: int
    codex_stdout: str
    codex_stderr: str
    verification_results: List[Dict[str, object]]
    changed_files: List[str]
    reverted_files: List[str]
    git_head_before: str
    git_head_after: str
    commit_message: str = ""
    committed_sha: str = ""
    push_succeeded: bool = False
    push_stdout: str = ""
    push_stderr: str = ""
    hook_results: List[Dict[str, object]] = field(default_factory=list)


class LoopInterrupted(RuntimeError):
    """Raised when the loop receives an external termination signal."""


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def empty_state(campaign_id: str) -> Dict[str, object]:
    return {"campaign_id": campaign_id, "tasks": {}, "updated_at_utc": ""}


def campaign_slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "campaign"


def ensure_state_root() -> Path:
    global STATE_ROOT
    try:
        STATE_ROOT.mkdir(parents=True, exist_ok=True)
    except PermissionError:
        STATE_ROOT = FALLBACK_STATE_ROOT
        STATE_ROOT.mkdir(parents=True, exist_ok=True)
        return STATE_ROOT
    if os.access(STATE_ROOT, os.W_OK | os.X_OK):
        return STATE_ROOT
    STATE_ROOT = FALLBACK_STATE_ROOT
    STATE_ROOT.mkdir(parents=True, exist_ok=True)
    return STATE_ROOT


def state_paths_for_campaign(spec: CampaignSpec) -> LoopPaths:
    state_root = ensure_state_root()
    campaign_dir = state_root / campaign_slug(spec.campaign_id)
    campaign_dir.mkdir(parents=True, exist_ok=True)
    return LoopPaths(
        state_root=state_root,
        campaign_dir=campaign_dir,
        state_path=campaign_dir / "state.json",
        results_path=campaign_dir / "results.jsonl",
        report_path=campaign_dir / "final_report.txt",
        log_path=campaign_dir / "tmux.log",
    )


def campaign_repo_root(spec: CampaignSpec) -> Path:
    return Path(spec.repo_root).expanduser().resolve()


def require_string(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{field_name} must not be empty")
    return cleaned


def require_string_list(value: object, field_name: str) -> List[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be a list")
    return [require_string(item, field_name) for item in value]


def parse_task(item: object, *, index: int) -> CampaignTask:
    if not isinstance(item, dict):
        raise ValueError(f"tasks[{index}] must be an object")
    verification_commands_raw = item.get("verification_commands", [])
    if not isinstance(verification_commands_raw, list):
        raise ValueError(f"tasks[{index}].verification_commands must be a list")
    verification_commands: List[List[str]] = []
    for command_index, command in enumerate(verification_commands_raw):
        if not isinstance(command, list) or not command:
            raise ValueError(f"tasks[{index}].verification_commands[{command_index}] must be a non-empty list")
        verification_commands.append(
            [
                require_string(part, f"tasks[{index}].verification_commands[{command_index}]")
                for part in command
            ]
        )
    def parse_hook_commands(field_name: str) -> List[List[str]]:
        raw_commands = item.get(field_name, [])
        if raw_commands is None:
            return []
        if not isinstance(raw_commands, list):
            raise ValueError(f"tasks[{index}].{field_name} must be a list")
        parsed: List[List[str]] = []
        for command_index, command in enumerate(raw_commands):
            if not isinstance(command, list) or not command:
                raise ValueError(f"tasks[{index}].{field_name}[{command_index}] must be a non-empty list")
            parsed.append(
                [
                    require_string(part, f"tasks[{index}].{field_name}[{command_index}]")
                    for part in command
                ]
            )
        return parsed
    return CampaignTask(
        task_id=require_string(item.get("task_id"), f"tasks[{index}].task_id"),
        title=require_string(item.get("title"), f"tasks[{index}].title"),
        summary=require_string(item.get("summary"), f"tasks[{index}].summary"),
        guidance=str(item.get("guidance", "")).strip(),
        target_paths=require_string_list(item.get("target_paths", []), f"tasks[{index}].target_paths"),
        verification_commands=verification_commands,
        on_success_commands=parse_hook_commands("on_success_commands"),
        on_failure_commands=parse_hook_commands("on_failure_commands"),
    )


def load_campaign_spec(path: str) -> CampaignSpec:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("campaign spec root must be an object")
    tasks_payload = raw.get("tasks")
    if not isinstance(tasks_payload, list) or not tasks_payload:
        raise ValueError("campaign spec must define a non-empty tasks list")
    tasks = [parse_task(item, index=index) for index, item in enumerate(tasks_payload)]
    task_ids = [task.task_id for task in tasks]
    if len(task_ids) != len(set(task_ids)):
        raise ValueError("campaign spec task_id values must be unique")
    executor_cmd = raw.get("executor_cmd")
    return CampaignSpec(
        campaign_id=require_string(raw.get("campaign_id"), "campaign_id"),
        title=require_string(raw.get("title") or raw.get("campaign_id"), "title"),
        summary=str(raw.get("summary") or ""),
        tasks=tasks,
        repo_root=resolve_spec_path_token(str(raw.get("repo_root") or "${ROOT}")),
        default_max_attempts_per_task=max(
            1,
            int(raw.get("default_max_attempts_per_task") or DEFAULT_MAX_ATTEMPTS_PER_TASK),
        ),
        commit_prefix=str(raw.get("commit_prefix") or "Mavali Loop"),
        notify_prefix=str(raw.get("notify_prefix") or "MAVALI_LOOP_NOTIFY"),
        executor_cmd=require_string_list(executor_cmd, "executor_cmd") or None,
        legacy_state_dirs=require_string_list(raw.get("legacy_state_dirs", []), "legacy_state_dirs") or None,
        allowed_dirty_paths=require_string_list(raw.get("allowed_dirty_paths", []), "allowed_dirty_paths") or None,
    )


def resolve_spec_path_token(value: str) -> str:
    return value.replace("${ROOT}", str(ROOT))


def run_command_capture(
    args: Sequence[str],
    *,
    cwd: Optional[Path] = None,
    input_text: Optional[str] = None,
    timeout_seconds: Optional[int] = None,
) -> subprocess.CompletedProcess[str]:
    global ACTIVE_CHILD_PROCESS
    proc = subprocess.Popen(
        list(args),
        cwd=str(cwd) if cwd else None,
        stdin=subprocess.PIPE if input_text is not None else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    ACTIVE_CHILD_PROCESS = proc
    try:
        stdout, stderr = proc.communicate(input=input_text, timeout=timeout_seconds)
    finally:
        ACTIVE_CHILD_PROCESS = None
    return subprocess.CompletedProcess(list(args), proc.returncode, stdout, stderr)


def executor_command(spec: CampaignSpec) -> List[str]:
    override = os.getenv("SERVER3_MAVALI_LOOP_EXECUTOR_CMD", "").strip()
    if override:
        return shlex.split(override)
    if spec.executor_cmd:
        return resolve_command_tokens(spec, spec.executor_cmd)
    return list(DEFAULT_EXECUTOR_CMD)


def qa_python_command(spec: CampaignSpec) -> List[str]:
    override = os.getenv("SERVER3_MAVALI_LOOP_QA_PYTHON", "").strip()
    if override:
        return shlex.split(override)
    repo_python = campaign_repo_root(spec) / ".venv" / "server3-qa" / "bin" / "python"
    if repo_python.exists():
        return [str(repo_python)]
    if DEFAULT_QA_PYTHON.exists():
        return [str(DEFAULT_QA_PYTHON)]
    return ["python3"]


def resolve_command_tokens(
    spec: CampaignSpec,
    command: Sequence[str],
    substitutions: Optional[Dict[str, str]] = None,
) -> List[str]:
    resolved: List[str] = []
    qa_python = qa_python_command(spec)
    replacement_map = {
        "ROOT": str(ROOT),
        "REPO_ROOT": str(campaign_repo_root(spec)),
    }
    if substitutions:
        replacement_map.update(substitutions)
    for part in command:
        if part == "${QA_PYTHON}":
            resolved.extend(qa_python)
            continue
        updated = part
        for key, value in replacement_map.items():
            updated = updated.replace(f"${{{key}}}", value)
        resolved.append(updated)
    return resolved


def git_head(spec: CampaignSpec) -> str:
    proc = run_command_capture(["git", "rev-parse", "HEAD"], cwd=campaign_repo_root(spec))
    return proc.stdout.strip() if proc.returncode == 0 else ""


def current_branch(spec: CampaignSpec) -> str:
    proc = run_command_capture(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=campaign_repo_root(spec))
    return proc.stdout.strip() if proc.returncode == 0 else ""


def state_paths_within_repo(spec: CampaignSpec, paths: LoopPaths) -> List[str]:
    try:
        state_dir_relative = paths.campaign_dir.resolve().relative_to(campaign_repo_root(spec))
    except ValueError:
        return []
    return [str(state_dir_relative)]


def path_matches_ignored_prefix(path: str, prefixes: Sequence[str]) -> bool:
    normalized = path.rstrip("/")
    for prefix in prefixes:
        clean_prefix = prefix.rstrip("/")
        if normalized == clean_prefix or normalized.startswith(f"{clean_prefix}/"):
            return True
        if clean_prefix.startswith(f"{normalized}/"):
            return True
    return False


def git_status_entries(spec: CampaignSpec, paths: LoopPaths) -> Dict[str, str]:
    proc = run_command_capture(["git", "status", "--short"], cwd=campaign_repo_root(spec))
    if proc.returncode != 0:
        return {}
    entries: Dict[str, str] = {}
    ignored_prefixes = tuple(state_paths_within_repo(spec, paths))
    for line in proc.stdout.splitlines():
        if len(line) < 4:
            continue
        path = line[3:].strip()
        if ignored_prefixes and path_matches_ignored_prefix(path, ignored_prefixes):
            continue
        entries[path] = line[:2]
    return entries


def split_dirty_entries(
    entries: Dict[str, str],
    allowed_prefixes: Sequence[str],
) -> tuple[Dict[str, str], Dict[str, str]]:
    allowed: Dict[str, str] = {}
    blocked: Dict[str, str] = {}
    for path, status in entries.items():
        if allowed_prefixes and path_matches_ignored_prefix(path, allowed_prefixes):
            allowed[path] = status
        else:
            blocked[path] = status
    return allowed, blocked


def changed_files_since(before: Dict[str, str], after: Dict[str, str]) -> List[str]:
    changed = set(after) - set(before)
    for path, status in after.items():
        if before.get(path) != status:
            changed.add(path)
    return sorted(changed)


def snapshot_file_signatures(spec: CampaignSpec, paths_to_check: Sequence[str]) -> Dict[str, str]:
    signatures: Dict[str, str] = {}
    repo_root = campaign_repo_root(spec)
    for path in paths_to_check:
        full_path = repo_root / path
        if not full_path.exists() or not full_path.is_file():
            signatures[path] = ""
            continue
        signatures[path] = hashlib.sha256(full_path.read_bytes()).hexdigest()
    return signatures


def diff_signatures(before: Dict[str, str], after: Dict[str, str]) -> List[str]:
    changed: List[str] = []
    for path in sorted(set(before) | set(after)):
        if before.get(path) != after.get(path):
            changed.append(path)
    return changed


def file_tracked_by_git(spec: CampaignSpec, path: str) -> bool:
    proc = run_command_capture(["git", "ls-files", "--error-unmatch", "--", path], cwd=campaign_repo_root(spec))
    return proc.returncode == 0


def restore_paths(spec: CampaignSpec, paths_to_restore: Sequence[str]) -> List[str]:
    restored: List[str] = []
    tracked = [path for path in paths_to_restore if file_tracked_by_git(spec, path)]
    untracked = [path for path in paths_to_restore if path not in tracked]
    if tracked:
        proc = run_command_capture(
            ["git", "restore", "--worktree", "--staged", "--source=HEAD", "--", *tracked],
            cwd=campaign_repo_root(spec),
        )
        if proc.returncode != 0:
            raise RuntimeError(f"failed to restore tracked paths: {proc.stderr.strip()}")
        restored.extend(tracked)
    repo_root = campaign_repo_root(spec)
    for path in untracked:
        target = repo_root / path
        if target.is_dir():
            shutil.rmtree(target, ignore_errors=True)
        elif target.exists():
            target.unlink()
        restored.append(path)
    return sorted(restored)


def commit_and_push(spec: CampaignSpec, commit_message: str, paths_to_commit: Sequence[str]) -> tuple[str, bool, str, str]:
    repo_root = campaign_repo_root(spec)
    add_proc = run_command_capture(["git", "add", "--", *paths_to_commit], cwd=repo_root)
    if add_proc.returncode != 0:
        return "", False, add_proc.stdout, add_proc.stderr
    commit_proc = run_command_capture(["git", "commit", "-m", commit_message], cwd=repo_root)
    if commit_proc.returncode != 0:
        return "", False, commit_proc.stdout, commit_proc.stderr
    committed_sha = git_head(spec)
    branch = current_branch(spec) or "main"
    push_proc = run_command_capture(["git", "push", "origin", branch], cwd=repo_root)
    return committed_sha, push_proc.returncode == 0, push_proc.stdout, push_proc.stderr


def load_state(spec: CampaignSpec, paths: LoopPaths) -> Dict[str, object]:
    migrate_legacy_state_if_needed(spec, paths)
    if not paths.state_path.exists():
        return empty_state(spec.campaign_id)
    try:
        payload = json.loads(paths.state_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return empty_state(spec.campaign_id)
    if not isinstance(payload, dict):
        return empty_state(spec.campaign_id)
    tasks = payload.get("tasks")
    if not isinstance(tasks, dict):
        payload["tasks"] = {}
    payload["campaign_id"] = str(payload.get("campaign_id") or spec.campaign_id)
    if not isinstance(payload.get("updated_at_utc"), str):
        payload["updated_at_utc"] = ""
    if not isinstance(payload.get("run_status"), str) or not str(payload.get("run_status")).strip():
        if payload["tasks"] and all(
            isinstance(task_state, dict) and task_state.get("status") == "completed"
            for task_state in payload["tasks"].values()
        ):
            payload["run_status"] = "completed"
        elif payload.get("active_attempt"):
            payload["run_status"] = "running"
        else:
            payload["run_status"] = "pending"
    return payload


def migrate_legacy_state_if_needed(spec: CampaignSpec, paths: LoopPaths) -> None:
    if paths.state_path.exists():
        return
    if not spec.legacy_state_dirs:
        return
    for legacy_dir_raw in spec.legacy_state_dirs:
        legacy_dir = Path(resolve_command_tokens(spec, [legacy_dir_raw])[0])
        legacy_state_path = legacy_dir / "state.json"
        if not legacy_state_path.exists():
            continue
        try:
            legacy_state = json.loads(legacy_state_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if not isinstance(legacy_state, dict):
            continue
        migrated_state = dict(legacy_state)
        if "issues" in migrated_state and "tasks" not in migrated_state:
            migrated_state["tasks"] = migrated_state.pop("issues")
        active_attempt = migrated_state.get("active_attempt")
        if isinstance(active_attempt, dict) and "issue_id" in active_attempt and "task_id" not in active_attempt:
            active_attempt["task_id"] = active_attempt.pop("issue_id")
        save_state(paths, migrated_state)

        legacy_results_path = legacy_dir / "results.jsonl"
        if legacy_results_path.exists() and not paths.results_path.exists():
            migrated_lines: List[str] = []
            for line in legacy_results_path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if "issue_id" in payload and "task_id" not in payload:
                    payload["task_id"] = payload.pop("issue_id")
                migrated_lines.append(json.dumps(payload, sort_keys=True, ensure_ascii=True))
            if migrated_lines:
                paths.results_path.write_text("\n".join(migrated_lines) + "\n", encoding="utf-8")
        break


def save_state(paths: LoopPaths, state: Dict[str, object]) -> None:
    with open(paths.state_path, "w", encoding="utf-8") as handle:
        json.dump(state, handle, indent=2, sort_keys=True)
        handle.write("\n")


def save_result(paths: LoopPaths, result: AttemptResult) -> None:
    with open(paths.results_path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(asdict(result), sort_keys=True, ensure_ascii=True))
        handle.write("\n")


def install_signal_handlers():
    previous_handlers = {}

    def _handle_interrupt(signum, _frame) -> None:
        global LAST_INTERRUPT_SIGNAL
        LAST_INTERRUPT_SIGNAL = signum
        child = ACTIVE_CHILD_PROCESS
        if child is not None and child.poll() is None:
            try:
                os.killpg(child.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        raise LoopInterrupted(f"received signal {signum}")

    for signum in INTERRUPT_SIGNALS:
        previous = signal.getsignal(signum)
        previous_handlers[signum] = previous
        if previous is signal.SIG_IGN:
            continue
        signal.signal(signum, _handle_interrupt)
    return previous_handlers


def restore_signal_handlers(previous_handlers) -> None:
    for signum, previous in previous_handlers.items():
        signal.signal(signum, previous)


def begin_active_attempt(
    state: Dict[str, object],
    *,
    task: CampaignTask,
    attempt: int,
    git_head_before: str,
) -> None:
    state["active_attempt"] = {
        "task_id": task.task_id,
        "attempt": attempt,
        "git_head_before": git_head_before,
        "started_at_utc": now_utc().isoformat(),
    }


def clear_active_attempt(state: Dict[str, object]) -> None:
    state.pop("active_attempt", None)


def ensure_task_state(state: Dict[str, object], task_id: str) -> Dict[str, object]:
    tasks = state.setdefault("tasks", {})
    if not isinstance(tasks, dict):
        state["tasks"] = {}
        tasks = state["tasks"]
    record = tasks.get(task_id)
    if not isinstance(record, dict):
        record = {"status": "pending", "attempts": 0, "history": []}
        tasks[task_id] = record
    history = record.get("history")
    if not isinstance(history, list):
        record["history"] = []
    return record


def task_map(spec: CampaignSpec) -> Dict[str, CampaignTask]:
    return {task.task_id: task for task in spec.tasks}


def recover_abandoned_attempt(
    spec: CampaignSpec,
    paths: LoopPaths,
    state: Dict[str, object],
    *,
    reason: str,
) -> Optional[AttemptResult]:
    active_attempt = state.get("active_attempt")
    if not isinstance(active_attempt, dict):
        return None
    task_id = str(active_attempt.get("task_id") or "")
    task = task_map(spec).get(task_id)
    if task is None:
        clear_active_attempt(state)
        return None
    changed_files = sorted(git_status_entries(spec, paths))
    reverted_files: List[str] = []
    if changed_files:
        reverted_files = restore_paths(spec, changed_files)
    result = AttemptResult(
        observed_at_utc=now_utc().isoformat(),
        task_id=task.task_id,
        attempt=int(active_attempt.get("attempt") or 1),
        status="interrupted",
        summary=reason,
        codex_returncode=-(LAST_INTERRUPT_SIGNAL or 1),
        codex_stdout="",
        codex_stderr="loop interrupted before attempt completed",
        verification_results=[],
        changed_files=changed_files,
        reverted_files=reverted_files,
        git_head_before=str(active_attempt.get("git_head_before") or ""),
        git_head_after=git_head(spec),
    )
    task_state = ensure_task_state(state, task.task_id)
    save_result(paths, result)
    update_task_state(task_state, result)
    clear_active_attempt(state)
    state["updated_at_utc"] = now_utc().isoformat()
    save_state(paths, state)
    return result


def build_attempt_history_text(task_state: Dict[str, object]) -> str:
    history = task_state.get("history")
    if not isinstance(history, list) or not history:
        return "- none"
    lines: List[str] = []
    for item in history[-3:]:
        if not isinstance(item, dict):
            continue
        status = str(item.get("status") or "-")
        summary = str(item.get("summary") or "").strip()
        changed = item.get("changed_files")
        changed_text = ", ".join(changed) if isinstance(changed, list) and changed else "-"
        lines.append(f"- status={status} changed={changed_text} summary={summary}")
    return "\n".join(lines) if lines else "- none"


def build_prompt(spec: CampaignSpec, task: CampaignTask, task_state: Dict[str, object], attempt: int, index: int) -> str:
    verification_lines = "\n".join(
        f"- {shlex.join(resolve_command_tokens(spec, command))}" for command in task.verification_commands
    )
    target_lines = "\n".join(f"- {path}" for path in task.target_paths) or "- none"
    return (
        "Mavali Loop.\n\n"
        "Goal:\n"
        f"- Campaign: {spec.campaign_id}\n"
        f"- Campaign title: {spec.title}\n"
        f"- Campaign summary: {spec.summary}\n"
        f"- Task: {task.task_id}\n"
        f"- Position: {index}/{len(spec.tasks)}\n"
        f"- Attempt: {attempt}\n"
        f"- Title: {task.title}\n"
        f"- Problem: {task.summary}\n"
        f"- Guidance: {task.guidance}\n\n"
        "Target paths:\n"
        f"{target_lines}\n\n"
        "Recent attempt history:\n"
        f"{build_attempt_history_text(task_state)}\n\n"
        "Execution contract:\n"
        "- Fully resolve this task, not just partially address it.\n"
        "- Make whatever code, test, and documentation changes are required for a solid fix.\n"
        "- Run the required verification yourself before finishing.\n"
        "- If the task is already fixed well enough, leave the tree unchanged and explain why.\n"
        "- Do not commit or push. The loop handles that after verification passes.\n"
        "- Keep the worktree clean on failure; do not leave experimental junk behind.\n\n"
        "Required verification commands:\n"
        f"{verification_lines}\n\n"
        "Final response format:\n"
        "1. Outcome\n"
        "2. Files changed\n"
        "3. Verification run\n"
        "4. Remaining risk\n"
    )


def run_verification_commands(spec: CampaignSpec, commands: Sequence[Sequence[str]]) -> List[VerificationResult]:
    results: List[VerificationResult] = []
    for command in commands:
        resolved_command = resolve_command_tokens(spec, command)
        proc = run_command_capture(resolved_command, cwd=campaign_repo_root(spec))
        results.append(
            VerificationResult(
                command=resolved_command,
                returncode=proc.returncode,
                stdout=proc.stdout,
                stderr=proc.stderr,
            )
        )
        if proc.returncode != 0:
            break
    return results


def build_hook_substitutions(spec: CampaignSpec, task: CampaignTask, status: str) -> Dict[str, str]:
    return {
        "CAMPAIGN_ID": spec.campaign_id,
        "CAMPAIGN_TITLE": spec.title,
        "TASK_ID": task.task_id,
        "TASK_TITLE": task.title,
        "TASK_STATUS": status,
    }


def run_hook_commands(
    spec: CampaignSpec,
    commands: Sequence[Sequence[str]],
    *,
    task: CampaignTask,
    status: str,
) -> List[VerificationResult]:
    substitutions = build_hook_substitutions(spec, task, status)
    results: List[VerificationResult] = []
    for command in commands:
        resolved_command = resolve_command_tokens(spec, command, substitutions)
        proc = run_command_capture(resolved_command, cwd=campaign_repo_root(spec))
        results.append(
            VerificationResult(
                command=resolved_command,
                returncode=proc.returncode,
                stdout=proc.stdout,
                stderr=proc.stderr,
            )
        )
        if proc.returncode != 0:
            break
    return results


def attempt_result(
    *,
    task: CampaignTask,
    attempt: int,
    observed_at: datetime,
    status: str,
    summary: str,
    codex_proc: subprocess.CompletedProcess[str],
    verification_results: List[VerificationResult],
    hook_results: Optional[List[VerificationResult]] = None,
    changed_files: List[str],
    reverted_files: List[str],
    git_head_before: str,
    git_head_after: str,
    commit_message: str = "",
    committed_sha: str = "",
    push_succeeded: bool = False,
    push_stdout: str = "",
    push_stderr: str = "",
) -> AttemptResult:
    return AttemptResult(
        observed_at_utc=observed_at.isoformat(),
        task_id=task.task_id,
        attempt=attempt,
        status=status,
        summary=summary,
        codex_returncode=codex_proc.returncode,
        codex_stdout=codex_proc.stdout,
        codex_stderr=codex_proc.stderr,
        verification_results=[
            {
                "command": result.command,
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }
            for result in verification_results
        ],
        hook_results=[
            {
                "command": result.command,
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }
            for result in (hook_results or [])
        ],
        changed_files=changed_files,
        reverted_files=reverted_files,
        git_head_before=git_head_before,
        git_head_after=git_head_after,
        commit_message=commit_message,
        committed_sha=committed_sha,
        push_succeeded=push_succeeded,
        push_stdout=push_stdout,
        push_stderr=push_stderr,
    )


def run_task_attempt(
    spec: CampaignSpec,
    paths: LoopPaths,
    task: CampaignTask,
    task_state: Dict[str, object],
    attempt: int,
    index: int,
) -> AttemptResult:
    prompt = build_prompt(spec, task, task_state, attempt, index)
    allowed_dirty_prefixes = tuple(spec.allowed_dirty_paths or [])
    worktree_before = git_status_entries(spec, paths)
    allowed_dirty_before, blocked_dirty_before = split_dirty_entries(worktree_before, allowed_dirty_prefixes)
    if blocked_dirty_before:
        raise RuntimeError("mavali loop requires a clean git worktree before each attempt")
    allowed_signatures_before = snapshot_file_signatures(spec, allowed_dirty_before.keys())
    head_before = git_head(spec)
    codex_proc = run_command_capture(executor_command(spec), cwd=campaign_repo_root(spec), input_text=prompt)
    worktree_after = git_status_entries(spec, paths)
    allowed_dirty_after, blocked_dirty_after = split_dirty_entries(worktree_after, allowed_dirty_prefixes)
    changed_files = changed_files_since(blocked_dirty_before, blocked_dirty_after)
    allowed_signatures_after = snapshot_file_signatures(spec, allowed_dirty_after.keys())
    allowlisted_touched = diff_signatures(allowed_signatures_before, allowed_signatures_after)
    verification_results = run_verification_commands(spec, task.verification_commands)
    head_after = git_head(spec)
    reverted_files: List[str] = []

    if allowlisted_touched:
        failure_hooks = run_hook_commands(
            spec,
            task.on_failure_commands,
            task=task,
            status="dirty_allowlist_touched",
        )
        return attempt_result(
            task=task,
            attempt=attempt,
            observed_at=now_utc(),
            status="dirty_allowlist_touched",
            summary="Attempt touched allowlisted dirty paths; manual review is required.",
            codex_proc=codex_proc,
            verification_results=verification_results,
            hook_results=failure_hooks,
            changed_files=changed_files,
            reverted_files=reverted_files,
            git_head_before=head_before,
            git_head_after=git_head(spec),
        )

    if codex_proc.returncode != 0:
        if changed_files:
            reverted_files = restore_paths(spec, changed_files)
        failure_hooks = run_hook_commands(spec, task.on_failure_commands, task=task, status="blocked")
        return attempt_result(
            task=task,
            attempt=attempt,
            observed_at=now_utc(),
            status="blocked",
            summary="Codex execution failed before the task was resolved.",
            codex_proc=codex_proc,
            verification_results=verification_results,
            hook_results=failure_hooks,
            changed_files=changed_files,
            reverted_files=reverted_files,
            git_head_before=head_before,
            git_head_after=git_head(spec),
        )

    if any(result.returncode != 0 for result in verification_results):
        if changed_files:
            reverted_files = restore_paths(spec, changed_files)
        failure_hooks = run_hook_commands(spec, task.on_failure_commands, task=task, status="qa_failed")
        return attempt_result(
            task=task,
            attempt=attempt,
            observed_at=now_utc(),
            status="qa_failed",
            summary="Verification failed after changes; the loop reverted the failed attempt.",
            codex_proc=codex_proc,
            verification_results=verification_results,
            hook_results=failure_hooks,
            changed_files=changed_files,
            reverted_files=reverted_files,
            git_head_before=head_before,
            git_head_after=git_head(spec),
        )

    commit_message = f"{spec.commit_prefix}: {task.title}"
    committed_sha = ""
    push_succeeded = False
    push_stdout = ""
    push_stderr = ""
    success_hooks = run_hook_commands(spec, task.on_success_commands, task=task, status="success")
    if any(result.returncode != 0 for result in success_hooks):
        if changed_files:
            reverted_files = restore_paths(spec, changed_files)
        return attempt_result(
            task=task,
            attempt=attempt,
            observed_at=now_utc(),
            status="hook_failed",
            summary="Verification passed, but a success hook failed before completion.",
            codex_proc=codex_proc,
            verification_results=verification_results,
            hook_results=success_hooks,
            changed_files=changed_files,
            reverted_files=reverted_files,
            git_head_before=head_before,
            git_head_after=git_head(spec),
        )
    status = "no_change"
    summary = "Task appears already resolved; verification passed without code changes."
    if changed_files:
        committed_sha, push_succeeded, push_stdout, push_stderr = commit_and_push(
            spec,
            commit_message,
            changed_files,
        )
        head_after = git_head(spec)
        if not committed_sha:
            return attempt_result(
                task=task,
                attempt=attempt,
                observed_at=now_utc(),
                status="commit_failed",
                summary="Verification passed but commit failed.",
                codex_proc=codex_proc,
                verification_results=verification_results,
                hook_results=success_hooks,
                changed_files=changed_files,
                reverted_files=reverted_files,
                git_head_before=head_before,
                git_head_after=head_after,
                commit_message=commit_message,
                push_stdout=push_stdout,
                push_stderr=push_stderr,
            )
        if not push_succeeded:
            return attempt_result(
                task=task,
                attempt=attempt,
                observed_at=now_utc(),
                status="push_failed",
                summary="Verification passed and commit succeeded, but push failed.",
                codex_proc=codex_proc,
                verification_results=verification_results,
                hook_results=success_hooks,
                changed_files=changed_files,
                reverted_files=reverted_files,
                git_head_before=head_before,
                git_head_after=head_after,
                commit_message=commit_message,
                committed_sha=committed_sha,
                push_succeeded=push_succeeded,
                push_stdout=push_stdout,
                push_stderr=push_stderr,
            )
        status = "applied"
        summary = "Task resolved, verified, committed, and pushed."

    return attempt_result(
        task=task,
        attempt=attempt,
        observed_at=now_utc(),
        status=status,
        summary=summary,
        codex_proc=codex_proc,
        verification_results=verification_results,
        hook_results=success_hooks,
        changed_files=changed_files,
        reverted_files=reverted_files,
        git_head_before=head_before,
        git_head_after=head_after,
        commit_message=commit_message if changed_files else "",
        committed_sha=committed_sha,
        push_succeeded=push_succeeded,
        push_stdout=push_stdout,
        push_stderr=push_stderr,
    )


def update_task_state(task_state: Dict[str, object], result: AttemptResult) -> None:
    attempts = int(task_state.get("attempts") or 0) + 1
    history = task_state.get("history")
    if not isinstance(history, list):
        history = []
        task_state["history"] = history
    history.append(
        {
            "attempt": result.attempt,
            "observed_at_utc": result.observed_at_utc,
            "status": result.status,
            "summary": result.summary,
            "changed_files": list(result.changed_files),
            "reverted_files": list(result.reverted_files),
            "committed_sha": result.committed_sha,
            "push_succeeded": result.push_succeeded,
            "hook_failures": sum(1 for hook in result.hook_results if int(hook.get("returncode") or 0) != 0),
        }
    )
    task_state["attempts"] = attempts
    task_state["last_summary"] = result.summary
    task_state["last_status"] = result.status
    task_state["updated_at_utc"] = result.observed_at_utc
    if result.status in {"applied", "no_change"}:
        task_state["status"] = "completed"
        task_state["completed_at_utc"] = result.observed_at_utc
    else:
        task_state["status"] = "pending"


def pending_tasks(spec: CampaignSpec, state: Dict[str, object]) -> List[CampaignTask]:
    pending: List[CampaignTask] = []
    for task in spec.tasks:
        task_state = ensure_task_state(state, task.task_id)
        if task_state.get("status") != "completed":
            pending.append(task)
    return pending


def render_status(spec: CampaignSpec, state: Dict[str, object]) -> str:
    pending = pending_tasks(spec, state)
    completed = len(spec.tasks) - len(pending)
    lines = [
        f"campaign={spec.campaign_id}",
        f"title={spec.title}",
        f"run_status={state.get('run_status', 'pending')}",
        f"completed={completed}/{len(spec.tasks)}",
    ]
    for task in spec.tasks:
        task_state = ensure_task_state(state, task.task_id)
        lines.append(
            f"{task.task_id} status={task_state.get('status','pending')} attempts={task_state.get('attempts',0)}"
        )
    return "\n".join(lines)


def format_final_report(spec: CampaignSpec, state: Dict[str, object], *, exit_code: int) -> str:
    completed = len(spec.tasks) - len(pending_tasks(spec, state))
    attempt_total = sum(int(ensure_task_state(state, task.task_id).get("attempts") or 0) for task in spec.tasks)
    lines = [
        f"[Mavali Loop] {spec.title}",
        f"campaign={spec.campaign_id}",
        f"status={state.get('run_status', 'unknown')}",
        f"exit_code={exit_code}",
        f"completed={completed}/{len(spec.tasks)}",
        f"attempts={attempt_total}",
        f"started_at_utc={state.get('last_run_started_at_utc', '')}",
        f"finished_at_utc={state.get('last_run_finished_at_utc', '')}",
    ]
    for task in spec.tasks:
        task_state = ensure_task_state(state, task.task_id)
        summary = str(task_state.get("last_summary") or "-")
        committed_sha = str(task_state.get("history", [{}])[-1].get("committed_sha", "")) if task_state.get("history") else ""
        lines.append(
            f"- {task.task_id}: {task_state.get('status','pending')} attempts={task_state.get('attempts',0)} commit={committed_sha or '-'} summary={summary}"
        )
    return "\n".join(lines)


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


def maybe_send_completion_report(spec: CampaignSpec, paths: LoopPaths, state: Dict[str, object], *, exit_code: int) -> None:
    completed = len(pending_tasks(spec, state)) == 0
    if not completed:
        return
    final_report = format_final_report(spec, state, exit_code=exit_code)
    paths.report_path.write_text(final_report + "\n", encoding="utf-8")
    last_status = str(state.get("last_notified_status") or "")
    if last_status == "completed":
        return
    sent = send_telegram_message(final_report, prefix=spec.notify_prefix)
    state["last_notified_status"] = "completed"
    state["last_notified_at_utc"] = now_utc().isoformat()
    state["last_notified_transport"] = "telegram" if sent else "none"
    save_state(paths, state)


def run_loop(spec: CampaignSpec, *, max_attempts_per_task: Optional[int] = None) -> int:
    paths = state_paths_for_campaign(spec)
    state = load_state(spec, paths)
    state["campaign_id"] = spec.campaign_id
    state["run_status"] = "running"
    state["last_run_started_at_utc"] = now_utc().isoformat()
    state["updated_at_utc"] = now_utc().isoformat()
    save_state(paths, state)
    recover_abandoned_attempt(
        spec,
        paths,
        state,
        reason="Previous attempt ended before completion; the loop restored leftover changes.",
    )
    signal_handlers = install_signal_handlers()
    attempt_budget = max_attempts_per_task or spec.default_max_attempts_per_task

    try:
        for index, task in enumerate(spec.tasks, start=1):
            task_state = ensure_task_state(state, task.task_id)
            if task_state.get("status") == "completed":
                continue
            attempts_this_run = 0
            while task_state.get("status") != "completed":
                if attempts_this_run >= attempt_budget:
                    state["run_status"] = "failed"
                    state["last_run_finished_at_utc"] = now_utc().isoformat()
                    save_state(paths, state)
                    print(render_status(spec, state))
                    return 1
                attempt_no = int(task_state.get("attempts") or 0) + 1
                begin_active_attempt(
                    state,
                    task=task,
                    attempt=attempt_no,
                    git_head_before=git_head(spec),
                )
                state["updated_at_utc"] = now_utc().isoformat()
                save_state(paths, state)
                try:
                    result = run_task_attempt(spec, paths, task, task_state, attempt_no, index)
                except LoopInterrupted:
                    recover_abandoned_attempt(
                        spec,
                        paths,
                        state,
                        reason="Attempt interrupted by external termination signal; restored leftover changes.",
                    )
                    state["run_status"] = "paused"
                    state["last_run_finished_at_utc"] = now_utc().isoformat()
                    save_state(paths, state)
                    print(render_status(spec, state))
                    return 1
                except Exception:
                    recover_abandoned_attempt(
                        spec,
                        paths,
                        state,
                        reason="Attempt crashed before completion; restored leftover changes.",
                    )
                    state["run_status"] = "failed"
                    state["last_run_finished_at_utc"] = now_utc().isoformat()
                    save_state(paths, state)
                    raise
                clear_active_attempt(state)
                save_result(paths, result)
                update_task_state(task_state, result)
                state["updated_at_utc"] = now_utc().isoformat()
                save_state(paths, state)
                attempts_this_run += 1
                if task_state.get("status") == "completed":
                    break

        state["run_status"] = "completed"
        state["last_run_finished_at_utc"] = now_utc().isoformat()
        save_state(paths, state)
        print(render_status(spec, state))
        maybe_send_completion_report(spec, paths, state, exit_code=0)
        return 0
    finally:
        restore_signal_handlers(signal_handlers)


def reset_state(spec: CampaignSpec) -> int:
    paths = state_paths_for_campaign(spec)
    if paths.state_path.exists():
        paths.state_path.unlink()
    if paths.results_path.exists():
        paths.results_path.unlink()
    if paths.report_path.exists():
        paths.report_path.unlink()
    if paths.log_path.exists():
        paths.log_path.unlink()
    print("reset")
    return 0


def parse_task_lines(raw_text: str) -> List[str]:
    tasks: List[str] = []
    for line in raw_text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        normalized = re.sub(r"^(?:\d+[\).\s-]+|[-*•]\s+)", "", stripped).strip()
        if normalized:
            tasks.append(normalized)
    return tasks


def create_campaign_spec(
    *,
    output_path: str,
    campaign_id: str,
    title: str,
    summary: str,
    task_lines: Sequence[str],
) -> int:
    tasks = []
    seen_ids = set()
    for index, task_line in enumerate(task_lines, start=1):
        task_id = campaign_slug(task_line)
        if task_id in seen_ids:
            task_id = f"{task_id}-{index}"
        seen_ids.add(task_id)
        tasks.append(
            {
                "task_id": task_id,
                "title": task_line,
                "summary": task_line,
                "guidance": "Fill in the exact scope, target paths, and verification before running this campaign.",
                "target_paths": [],
                "verification_commands": [["true"]],
                "on_success_commands": [],
                "on_failure_commands": [],
            }
        )
    payload = {
        "campaign_id": campaign_id,
        "title": title,
        "summary": summary,
        "default_max_attempts_per_task": DEFAULT_MAX_ATTEMPTS_PER_TASK,
        "commit_prefix": "Mavali Loop",
        "notify_prefix": "MAVALI_LOOP_NOTIFY",
        "allowed_dirty_paths": [],
        "tasks": tasks,
    }
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(payload, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    print(destination)
    return 0


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generic bounded autonomous task runner.")
    parser.add_argument("command", choices=("run", "status", "reset-state", "create-campaign"))
    parser.add_argument("campaign_path", nargs="?")
    parser.add_argument(
        "--max-attempts-per-task",
        type=int,
        default=0,
    )
    parser.add_argument("--output")
    parser.add_argument("--campaign-id")
    parser.add_argument("--title")
    parser.add_argument("--summary", default="")
    parser.add_argument("--tasks-file")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_arg_parser().parse_args(argv)
    if args.command == "create-campaign":
        if not args.output or not args.campaign_id or not args.title or not args.tasks_file:
            raise RuntimeError("create-campaign requires --output, --campaign-id, --title, and --tasks-file")
        task_lines = parse_task_lines(Path(args.tasks_file).read_text(encoding="utf-8"))
        if not task_lines:
            raise RuntimeError("create-campaign requires at least one task line")
        return create_campaign_spec(
            output_path=args.output,
            campaign_id=args.campaign_id,
            title=args.title,
            summary=args.summary,
            task_lines=task_lines,
        )
    if not args.campaign_path:
        raise RuntimeError("campaign_path is required")
    spec = load_campaign_spec(args.campaign_path)
    if args.command == "run":
        override = max(1, args.max_attempts_per_task) if args.max_attempts_per_task else None
        return run_loop(spec, max_attempts_per_task=override)
    if args.command == "status":
        print(render_status(spec, load_state(spec, state_paths_for_campaign(spec))))
        return 0
    if args.command == "reset-state":
        return reset_state(spec)
    raise RuntimeError(f"unsupported command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
