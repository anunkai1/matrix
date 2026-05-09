#!/usr/bin/env python3
"""Temporary autonomous review-fix loop for the seven architecture issues.

This loop is separate from Ralph. It is intended to be launched manually,
work through a fixed ordered backlog, and be removed once the backlog is done.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import shutil
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence

ROOT = Path(__file__).resolve().parents[2]
STATE_DIR = Path(
    os.getenv(
        "SERVER3_REVIEW_FIX_LOOP_STATE_DIR",
        "/var/lib/server3-review-fix-loop",
    )
)
FALLBACK_STATE_DIR = Path(
    os.getenv(
        "SERVER3_REVIEW_FIX_LOOP_FALLBACK_STATE_DIR",
        str(ROOT / ".state" / "server3-review-fix-loop"),
    )
)
STATE_PATH = STATE_DIR / "state.json"
RESULTS_PATH = STATE_DIR / "results.jsonl"
DEFAULT_EXECUTOR_CMD = [str(ROOT / "src" / "telegram_bridge" / "executor.sh"), "new"]
DEFAULT_QA_PYTHON = ROOT / ".venv" / "server3-qa" / "bin" / "python"
DEFAULT_MAX_ATTEMPTS_PER_ISSUE = max(
    1,
    int(os.getenv("SERVER3_REVIEW_FIX_LOOP_MAX_ATTEMPTS_PER_ISSUE", "5") or "5"),
)
CAMPAIGN_ID = "server3_code_review_may_2026"


@dataclass(frozen=True)
class ReviewIssue:
    issue_id: str
    title: str
    summary: str
    guidance: str
    target_paths: List[str]
    verification_commands: List[List[str]]


@dataclass(frozen=True)
class VerificationResult:
    command: List[str]
    returncode: int
    stdout: str
    stderr: str


@dataclass(frozen=True)
class AttemptResult:
    observed_at_utc: str
    issue_id: str
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


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def ensure_state_dir() -> None:
    global STATE_DIR, STATE_PATH, RESULTS_PATH
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
    except PermissionError:
        STATE_DIR = FALLBACK_STATE_DIR
        STATE_PATH = STATE_DIR / "state.json"
        RESULTS_PATH = STATE_DIR / "results.jsonl"
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        return
    if os.access(STATE_DIR, os.W_OK | os.X_OK):
        return
    STATE_DIR = FALLBACK_STATE_DIR
    STATE_PATH = STATE_DIR / "state.json"
    RESULTS_PATH = STATE_DIR / "results.jsonl"
    STATE_DIR.mkdir(parents=True, exist_ok=True)


def qa_python_command() -> List[str]:
    override = os.getenv("SERVER3_REVIEW_FIX_LOOP_QA_PYTHON", "").strip()
    if override:
        return shlex.split(override)
    if DEFAULT_QA_PYTHON.exists():
        return [str(DEFAULT_QA_PYTHON)]
    return ["python3"]


def pytest_command(*args: str) -> List[str]:
    return qa_python_command() + ["-m", "pytest", *args]


ISSUES: List[ReviewIssue] = [
    ReviewIssue(
        issue_id="split_request_orchestration",
        title="Split monolithic request orchestration",
        summary="Break up the long Telegram bridge orchestration functions into smaller staged helpers or handlers so change risk stops accumulating in one branch-heavy flow.",
        guidance="Prioritize the request entry path, prompt preparation, response delivery, and other long orchestration functions. Prefer typed intermediate results and small helper stages over moving code around without reducing branching.",
        target_paths=[
            "src/telegram_bridge/prompt_preparation.py",
            "src/telegram_bridge/response_delivery.py",
            "src/telegram_bridge/update_flow.py",
        ],
        verification_commands=[
            pytest_command("tests/telegram_bridge/test_handlers.py", "-q"),
            pytest_command("tests/telegram_bridge/test_special_request_processing.py", "-q"),
        ],
    ),
    ReviewIssue(
        issue_id="group_runtime_config",
        title="Group runtime configuration into submodels",
        summary="Replace the flat bridge config shape with grouped sub-configs or another declarative schema so env loading and test setup stop spreading across one giant config object.",
        guidance="Keep compatibility with existing env names. The goal is to reduce manual wiring and constructor churn, not change runtime semantics.",
        target_paths=[
            "src/telegram_bridge/runtime_config.py",
            "tests/telegram_bridge/test_config.py",
        ],
        verification_commands=[
            pytest_command("tests/telegram_bridge/test_config.py", "-q"),
            pytest_command("tests/telegram_bridge/test_handlers.py", "-q"),
        ],
    ),
    ReviewIssue(
        issue_id="dedupe_attachment_resolution",
        title="Deduplicate attachment resolution flow",
        summary="Unify the repeated resolve-download-archive-fallback flow for photos and documents into a reusable attachment-resolution service or helper with typed outcomes.",
        guidance="Reduce real duplication instead of just extracting tiny helpers. Preserve archived-summary fallback behavior and user-visible rejection messages.",
        target_paths=[
            "src/telegram_bridge/prompt_preparation.py",
            "src/telegram_bridge/attachment_processing.py",
        ],
        verification_commands=[
            pytest_command("tests/telegram_bridge/test_handlers.py", "-q"),
            pytest_command("tests/telegram_bridge/test_special_request_processing.py", "-q"),
        ],
    ),
    ReviewIssue(
        issue_id="dispatch_outbound_media",
        title="Dispatch outbound media by strategy",
        summary="Refactor outbound media delivery to use per-media handlers or a dispatch table instead of one central branch-heavy function.",
        guidance="Preserve current fallback semantics, especially sendVoice to sendAudio downgrade and text fallback on media send failure.",
        target_paths=[
            "src/telegram_bridge/response_delivery.py",
            "tests/telegram_bridge/test_executor.py",
        ],
        verification_commands=[
            pytest_command("tests/telegram_bridge/test_executor.py", "-q"),
            pytest_command("tests/telegram_bridge/test_handlers.py", "-q"),
        ],
    ),
    ReviewIssue(
        issue_id="remove_lazy_handler_imports",
        title="Replace lazy handler import indirection",
        summary="Reduce cyclic-import workarounds by introducing cleaner dependency boundaries so update flow and related modules do not need runtime import helpers.",
        guidance="Prefer explicit dependency passing or a small service container at bootstrap. Keep the change scoped and avoid broad rewrites.",
        target_paths=[
            "src/telegram_bridge/update_flow.py",
            "src/telegram_bridge/handlers.py",
            "src/telegram_bridge/bridge_runtime_setup.py",
        ],
        verification_commands=[
            pytest_command("tests/telegram_bridge/test_handlers.py", "-q"),
            pytest_command("tests/telegram_bridge/test_command_callback_routing.py", "-q"),
        ],
    ),
    ReviewIssue(
        issue_id="dedupe_browser_brain_js",
        title="Deduplicate Browser Brain DOM helper JS",
        summary="Move duplicated Browser Brain DOM helper logic into a shared source so collect and find flows cannot drift independently.",
        guidance="Keep the external API stable. The win is reducing duplicated locator logic, not changing Browser Brain behavior for users.",
        target_paths=[
            "src/browser_brain/service.py",
            "tests/browser_brain/test_service.py",
        ],
        verification_commands=[
            pytest_command("tests/browser_brain/test_service.py", "-q"),
            pytest_command("tests/browser_brain/test_server.py", "-q"),
        ],
    ),
    ReviewIssue(
        issue_id="tighten_python_qa",
        title="Tighten Python QA guardrails",
        summary="Raise the repo baseline with stricter lint/static checks or stronger QA wiring that fits the current bridge size and complexity.",
        guidance="Prefer practical guardrails that the repo can keep passing. Do not add aspirational checks that immediately create permanent noise.",
        target_paths=[
            "pyproject.toml",
            "ops/dev/run_python_checks.sh",
            "tests/review_fix_loop/test_review_fix_loop.py",
        ],
        verification_commands=[
            ["bash", "ops/dev/run_python_checks.sh", "--skip-smoke"],
        ],
    ),
]


def issue_map() -> Dict[str, ReviewIssue]:
    return {issue.issue_id: issue for issue in ISSUES}


def run_command_capture(
    args: Sequence[str],
    *,
    cwd: Optional[Path] = None,
    input_text: Optional[str] = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(args),
        cwd=str(cwd) if cwd else None,
        input=input_text,
        capture_output=True,
        text=True,
        check=False,
    )


def executor_command() -> List[str]:
    override = os.getenv("SERVER3_REVIEW_FIX_LOOP_EXECUTOR_CMD", "").strip()
    if override:
        return shlex.split(override)
    return list(DEFAULT_EXECUTOR_CMD)


def git_head() -> str:
    proc = run_command_capture(["git", "rev-parse", "HEAD"], cwd=ROOT)
    return proc.stdout.strip() if proc.returncode == 0 else ""


def current_branch() -> str:
    proc = run_command_capture(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=ROOT)
    return proc.stdout.strip() if proc.returncode == 0 else ""


def state_paths_within_repo() -> List[str]:
    try:
        state_dir_relative = STATE_DIR.resolve().relative_to(ROOT.resolve())
    except ValueError:
        return []
    return [str(state_dir_relative)]


def git_status_entries() -> Dict[str, str]:
    proc = run_command_capture(["git", "status", "--short"], cwd=ROOT)
    if proc.returncode != 0:
        return {}
    entries: Dict[str, str] = {}
    ignored_prefixes = tuple(state_paths_within_repo())
    for line in proc.stdout.splitlines():
        if len(line) < 4:
            continue
        path = line[3:].strip()
        if ignored_prefixes and any(path == prefix or path.startswith(f"{prefix}/") for prefix in ignored_prefixes):
            continue
        entries[path] = line[:2]
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


def file_tracked_by_git(path: str) -> bool:
    proc = run_command_capture(["git", "ls-files", "--error-unmatch", "--", path], cwd=ROOT)
    return proc.returncode == 0


def restore_paths(paths: Sequence[str]) -> List[str]:
    restored: List[str] = []
    tracked = [path for path in paths if file_tracked_by_git(path)]
    untracked = [path for path in paths if path not in tracked]
    if tracked:
        proc = run_command_capture(
            ["git", "restore", "--worktree", "--staged", "--source=HEAD", "--", *tracked],
            cwd=ROOT,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"failed to restore tracked paths: {proc.stderr.strip()}")
        restored.extend(tracked)
    for path in untracked:
        target = ROOT / path
        if target.is_dir():
            shutil.rmtree(target, ignore_errors=True)
        elif target.exists():
            target.unlink()
        restored.append(path)
    return sorted(restored)


def commit_and_push(commit_message: str, paths: Sequence[str]) -> tuple[str, bool, str, str]:
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


def load_state() -> Dict[str, object]:
    ensure_state_dir()
    if not STATE_PATH.exists():
        return {"campaign_id": CAMPAIGN_ID, "issues": {}, "updated_at_utc": ""}
    try:
        payload = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"campaign_id": CAMPAIGN_ID, "issues": {}, "updated_at_utc": ""}
    if not isinstance(payload, dict):
        return {"campaign_id": CAMPAIGN_ID, "issues": {}, "updated_at_utc": ""}
    issues = payload.get("issues")
    if not isinstance(issues, dict):
        payload["issues"] = {}
    return payload


def save_state(state: Dict[str, object]) -> None:
    ensure_state_dir()
    with open(STATE_PATH, "w", encoding="utf-8") as handle:
        json.dump(state, handle, indent=2, sort_keys=True)
        handle.write("\n")


def save_result(result: AttemptResult) -> None:
    ensure_state_dir()
    with open(RESULTS_PATH, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(asdict(result), sort_keys=True, ensure_ascii=True))
        handle.write("\n")


def ensure_issue_state(state: Dict[str, object], issue_id: str) -> Dict[str, object]:
    issues = state.setdefault("issues", {})
    if not isinstance(issues, dict):
        state["issues"] = {}
        issues = state["issues"]
    record = issues.get(issue_id)
    if not isinstance(record, dict):
        record = {"status": "pending", "attempts": 0, "history": []}
        issues[issue_id] = record
    history = record.get("history")
    if not isinstance(history, list):
        record["history"] = []
    return record


def build_attempt_history_text(issue_state: Dict[str, object]) -> str:
    history = issue_state.get("history")
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


def build_prompt(issue: ReviewIssue, issue_state: Dict[str, object], attempt: int, index: int, total: int) -> str:
    verification_lines = "\n".join(
        f"- {shlex.join(command)}" for command in issue.verification_commands
    )
    target_lines = "\n".join(f"- {path}" for path in issue.target_paths)
    return (
        "Server3 Review Fix Loop.\n\n"
        "Goal:\n"
        f"- Campaign: {CAMPAIGN_ID}\n"
        f"- Issue: {issue.issue_id}\n"
        f"- Position: {index}/{total}\n"
        f"- Attempt: {attempt}\n"
        f"- Title: {issue.title}\n"
        f"- Problem: {issue.summary}\n"
        f"- Guidance: {issue.guidance}\n\n"
        "Target paths:\n"
        f"{target_lines}\n\n"
        "Recent attempt history:\n"
        f"{build_attempt_history_text(issue_state)}\n\n"
        "Execution contract:\n"
        "- Fully resolve this issue, not just partially refactor it.\n"
        "- Make whatever code, test, and documentation changes are required for a solid fix.\n"
        "- Run the required verification yourself before finishing.\n"
        "- If the issue is already fixed well enough, leave the tree unchanged and explain why.\n"
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


def attempt_result(
    *,
    issue: ReviewIssue,
    attempt: int,
    observed_at: datetime,
    status: str,
    summary: str,
    codex_proc: subprocess.CompletedProcess[str],
    verification_results: List[VerificationResult],
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
        issue_id=issue.issue_id,
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


def run_issue_attempt(issue: ReviewIssue, issue_state: Dict[str, object], attempt: int, index: int, total: int) -> AttemptResult:
    prompt = build_prompt(issue, issue_state, attempt, index, total)
    worktree_before = git_status_entries()
    if worktree_before:
        raise RuntimeError("review loop requires a clean git worktree before each attempt")
    head_before = git_head()
    codex_proc = run_command_capture(executor_command(), cwd=ROOT, input_text=prompt)
    worktree_after = git_status_entries()
    changed_files = changed_files_since(worktree_before, worktree_after)
    verification_results = run_verification_commands(issue.verification_commands)
    head_after = git_head()
    reverted_files: List[str] = []

    if codex_proc.returncode != 0:
        if changed_files:
            reverted_files = restore_paths(changed_files)
        return attempt_result(
            issue=issue,
            attempt=attempt,
            observed_at=now_utc(),
            status="blocked",
            summary="Codex execution failed before the issue was resolved.",
            codex_proc=codex_proc,
            verification_results=verification_results,
            changed_files=changed_files,
            reverted_files=reverted_files,
            git_head_before=head_before,
            git_head_after=git_head(),
        )

    if any(result.returncode != 0 for result in verification_results):
        if changed_files:
            reverted_files = restore_paths(changed_files)
        return attempt_result(
            issue=issue,
            attempt=attempt,
            observed_at=now_utc(),
            status="qa_failed",
            summary="Verification failed after changes; the loop reverted the failed attempt.",
            codex_proc=codex_proc,
            verification_results=verification_results,
            changed_files=changed_files,
            reverted_files=reverted_files,
            git_head_before=head_before,
            git_head_after=git_head(),
        )

    commit_message = f"Review Loop: {issue.title}"
    committed_sha = ""
    push_succeeded = False
    push_stdout = ""
    push_stderr = ""
    status = "no_change"
    summary = "Issue appears already resolved; verification passed without code changes."
    if changed_files:
        committed_sha, push_succeeded, push_stdout, push_stderr = commit_and_push(
            commit_message,
            changed_files,
        )
        head_after = git_head()
        if not committed_sha:
            return attempt_result(
                issue=issue,
                attempt=attempt,
                observed_at=now_utc(),
                status="commit_failed",
                summary="Verification passed but commit failed.",
                codex_proc=codex_proc,
                verification_results=verification_results,
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
                issue=issue,
                attempt=attempt,
                observed_at=now_utc(),
                status="push_failed",
                summary="Verification passed and commit succeeded, but push failed.",
                codex_proc=codex_proc,
                verification_results=verification_results,
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
        summary = "Issue resolved, verified, committed, and pushed."

    return attempt_result(
        issue=issue,
        attempt=attempt,
        observed_at=now_utc(),
        status=status,
        summary=summary,
        codex_proc=codex_proc,
        verification_results=verification_results,
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


def update_issue_state(issue_state: Dict[str, object], result: AttemptResult) -> None:
    attempts = int(issue_state.get("attempts") or 0) + 1
    history = issue_state.get("history")
    if not isinstance(history, list):
        history = []
        issue_state["history"] = history
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
        }
    )
    issue_state["attempts"] = attempts
    issue_state["last_summary"] = result.summary
    issue_state["last_status"] = result.status
    issue_state["updated_at_utc"] = result.observed_at_utc
    if result.status in {"applied", "no_change"}:
        issue_state["status"] = "completed"
        issue_state["completed_at_utc"] = result.observed_at_utc
    else:
        issue_state["status"] = "pending"


def pending_issues(state: Dict[str, object]) -> List[ReviewIssue]:
    pending: List[ReviewIssue] = []
    for issue in ISSUES:
        issue_state = ensure_issue_state(state, issue.issue_id)
        if issue_state.get("status") != "completed":
            pending.append(issue)
    return pending


def render_status(state: Dict[str, object]) -> str:
    pending = pending_issues(state)
    completed = len(ISSUES) - len(pending)
    lines = [
        f"campaign={CAMPAIGN_ID}",
        f"completed={completed}/{len(ISSUES)}",
    ]
    for issue in ISSUES:
        issue_state = ensure_issue_state(state, issue.issue_id)
        lines.append(
            f"{issue.issue_id} status={issue_state.get('status','pending')} attempts={issue_state.get('attempts',0)}"
        )
    return "\n".join(lines)


def run_loop(*, max_attempts_per_issue: int) -> int:
    state = load_state()
    state["campaign_id"] = CAMPAIGN_ID
    state["updated_at_utc"] = now_utc().isoformat()
    save_state(state)

    for index, issue in enumerate(ISSUES, start=1):
        issue_state = ensure_issue_state(state, issue.issue_id)
        if issue_state.get("status") == "completed":
            continue
        attempts_this_run = 0
        while issue_state.get("status") != "completed":
            if attempts_this_run >= max_attempts_per_issue:
                save_state(state)
                print(render_status(state))
                return 1
            attempt_no = int(issue_state.get("attempts") or 0) + 1
            result = run_issue_attempt(issue, issue_state, attempt_no, index, len(ISSUES))
            save_result(result)
            update_issue_state(issue_state, result)
            state["updated_at_utc"] = now_utc().isoformat()
            save_state(state)
            attempts_this_run += 1
            if issue_state.get("status") == "completed":
                break

    print(render_status(state))
    return 0


def reset_state() -> int:
    ensure_state_dir()
    if STATE_PATH.exists():
        STATE_PATH.unlink()
    if RESULTS_PATH.exists():
        RESULTS_PATH.unlink()
    print("reset")
    return 0


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Temporary autonomous review-fix loop.")
    parser.add_argument("command", choices=("run", "status", "reset-state"))
    parser.add_argument(
        "--max-attempts-per-issue",
        type=int,
        default=DEFAULT_MAX_ATTEMPTS_PER_ISSUE,
    )
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_arg_parser().parse_args(argv)
    if args.command == "run":
        return run_loop(max_attempts_per_issue=max(1, args.max_attempts_per_issue))
    if args.command == "status":
        print(render_status(load_state()))
        return 0
    if args.command == "reset-state":
        return reset_state()
    raise RuntimeError(f"unsupported command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
