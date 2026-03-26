"""Conservative task orchestration with read-only worker scouts."""

from __future__ import annotations

import os
import shlex
import subprocess
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

try:
    from .executor import parse_executor_output
    from .runtime_paths import build_runtime_root
    from .structured_logging import emit_event
except ImportError:
    from executor import parse_executor_output
    from runtime_paths import build_runtime_root
    from structured_logging import emit_event


ORCHESTRATOR_HEADER = "Architect worker findings"
MAX_WORKER_OUTPUT_CHARS = 3000

RUNTIME_KEYWORDS = (
    "log",
    "logs",
    "journal",
    "systemctl",
    "service",
    "runtime",
    "incident",
    "error",
    "failed",
    "restart",
    "status",
    "bridge",
)
DOCS_KEYWORDS = (
    "doc",
    "docs",
    "documentation",
    "readme",
    "runbook",
    "spec",
    "specs",
    "policy",
)
CODE_KEYWORDS = (
    "code",
    "file",
    "files",
    "function",
    "class",
    "module",
    "implement",
    "patch",
    "refactor",
    "edit",
    "change",
    "bug",
    "fix",
)
VERIFY_KEYWORDS = (
    "verify",
    "verification",
    "test",
    "tests",
    "check",
    "confirm",
    "validate",
    "proof",
)


@dataclass(frozen=True)
class WorkerSpec:
    role: str
    objective: str


@dataclass
class WorkerResult:
    role: str
    success: bool
    summary: str


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in text for keyword in keywords)


def analyze_task_shape(prompt_text: str) -> Dict[str, object]:
    text = (prompt_text or "").strip()
    lowered = text.lower()
    signals = {
        "runtime": _contains_any(lowered, RUNTIME_KEYWORDS),
        "docs": _contains_any(lowered, DOCS_KEYWORDS),
        "code": _contains_any(lowered, CODE_KEYWORDS),
        "verify": _contains_any(lowered, VERIFY_KEYWORDS),
    }
    return {"signals": signals}


def build_worker_plan(config, prompt_text: str) -> List[WorkerSpec]:
    if not bool(getattr(config, "agent_orchestrator_enabled", False)):
        return []
    signals = analyze_task_shape(prompt_text)["signals"]
    workers: List[WorkerSpec] = []
    if signals["runtime"]:
        workers.append(
            WorkerSpec(
                role="runtime-investigator",
                objective=(
                    "Inspect runtime, service, and log context relevant to the request. "
                    "Focus on concrete evidence, likely failure points, and the most relevant commands or files."
                ),
            )
        )
    if signals["docs"]:
        workers.append(
            WorkerSpec(
                role="docs-researcher",
                objective=(
                    "Read the relevant repo docs, runbooks, and policy files. "
                    "Extract only the constraints and facts that materially affect the task."
                ),
            )
        )
    if signals["code"]:
        workers.append(
            WorkerSpec(
                role="codebase-mapper",
                objective=(
                    "Inspect the codebase and identify the most likely files, modules, and functions involved. "
                    "Do not edit anything; return the probable change surface and key observations."
                ),
            )
        )
    if signals["verify"]:
        workers.append(
            WorkerSpec(
                role="verification-planner",
                objective=(
                    "Determine what evidence would prove the task is complete and safe. "
                    "Focus on exact checks, tests, service health commands, or logs to inspect."
                ),
            )
        )

    max_workers = max(1, int(getattr(config, "agent_orchestrator_max_workers", 3)))
    if len(workers) < 2:
        return []
    return workers[:max_workers]


def build_worker_prompt(worker: WorkerSpec, user_prompt: str) -> str:
    return (
        "You are a temporary specialist worker supporting Architect on Server3.\n"
        "You do not own the final answer.\n"
        "Operate read-only. Do not edit files, apply patches, restart services, or make destructive changes.\n"
        "Inspect only what is needed for your objective and return concise factual findings.\n\n"
        f"Worker role: {worker.role}\n"
        f"Objective: {worker.objective}\n\n"
        "Return exactly these sections:\n"
        "Summary:\n"
        "Evidence:\n"
        "Next:\n\n"
        "User request:\n"
        f"{user_prompt.strip()}\n"
    )


def _build_worker_command(output_path: str) -> List[str]:
    code_bin = os.getenv("CODEX_BIN", "codex").strip() or "codex"
    cmd = [
        code_bin,
        "exec",
        "--skip-git-repo-check",
        "--sandbox",
        "read-only",
        "--color",
        "never",
        "--output-last-message",
        output_path,
    ]
    extra_args = os.getenv("ARCHITECT_EXEC_ARGS", "").strip()
    if extra_args:
        cmd.extend(shlex.split(extra_args))
    cmd.append("-")
    return cmd


def _run_worker_prompt(
    config,
    worker: WorkerSpec,
    prompt_text: str,
    cancel_event: Optional[threading.Event] = None,
) -> WorkerResult:
    worker_prompt = build_worker_prompt(worker, prompt_text)
    runtime_root = build_runtime_root()
    output_handle = tempfile.NamedTemporaryFile(
        prefix="architect-worker-",
        suffix=".txt",
        delete=False,
    )
    output_path = output_handle.name
    output_handle.close()
    cmd = _build_worker_command(output_path)

    emit_event(
        "bridge.orchestrator_worker_started",
        fields={"role": worker.role},
    )

    process = subprocess.Popen(
        cmd,
        cwd=runtime_root,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        if process.stdin is not None:
            process.stdin.write(worker_prompt)
            if not worker_prompt.endswith("\n"):
                process.stdin.write("\n")
            process.stdin.close()
    except Exception:
        process.kill()
        process.wait(timeout=5)
        raise

    try:
        while True:
            if cancel_event is not None and cancel_event.is_set():
                process.kill()
                _stdout, stderr = process.communicate(timeout=5)
                emit_event(
                    "bridge.orchestrator_worker_finished",
                    fields={"role": worker.role, "success": False, "reason": "cancelled"},
                )
                return WorkerResult(
                    role=worker.role,
                    success=False,
                    summary=f"Worker cancelled. stderr={str(stderr or '').strip()[:400]}",
                )
            return_code = process.poll()
            if return_code is not None:
                stdout, stderr = process.communicate(timeout=5)
                output = ""
                try:
                    output = Path(output_path).read_text(encoding="utf-8").strip()
                except OSError:
                    output = ""
                if not output:
                    _, output = parse_executor_output(stdout or "")
                summary = (output or str(stderr or "")).strip()
                summary = summary[:MAX_WORKER_OUTPUT_CHARS].strip()
                success = return_code == 0 and bool(summary)
                emit_event(
                    "bridge.orchestrator_worker_finished",
                    fields={"role": worker.role, "success": success, "returncode": return_code},
                )
                return WorkerResult(role=worker.role, success=success, summary=summary)
            time.sleep(0.2)
    finally:
        try:
            os.remove(output_path)
        except OSError:
            pass


def maybe_augment_prompt_with_worker_findings(
    config,
    prompt_text: str,
    cancel_event: Optional[threading.Event] = None,
) -> str:
    workers = build_worker_plan(config, prompt_text)
    if not workers:
        emit_event(
            "bridge.orchestrator_decision",
            fields={"enabled": False, "reason": "not_usefully_split", "worker_count": 0},
        )
        return prompt_text

    emit_event(
        "bridge.orchestrator_decision",
        fields={
            "enabled": True,
            "reason": "multi_role_split",
            "worker_count": len(workers),
            "worker_roles": [worker.role for worker in workers],
        },
    )

    results: List[WorkerResult] = []
    with ThreadPoolExecutor(max_workers=len(workers)) as pool:
        future_map = {
            pool.submit(_run_worker_prompt, config, worker, prompt_text, cancel_event): worker
            for worker in workers
        }
        for future in as_completed(future_map):
            worker = future_map[future]
            try:
                results.append(future.result())
            except Exception as exc:
                results.append(
                    WorkerResult(
                        role=worker.role,
                        success=False,
                        summary=f"Worker failed before returning findings: {exc}",
                    )
                )

    successful = [result for result in results if result.success and result.summary.strip()]
    if not successful:
        return prompt_text

    findings_blocks = []
    for result in successful:
        findings_blocks.append(f"[{result.role}]\n{result.summary.strip()}")
    findings_text = "\n\n".join(findings_blocks)
    return (
        f"{ORCHESTRATOR_HEADER}:\n"
        "Use these worker findings as advisory context only. "
        "You remain responsible for the final answer, commands, edits, and verification.\n\n"
        f"{findings_text}\n\n"
        "Original user request:\n"
        f"{prompt_text}"
    )
