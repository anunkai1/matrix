import json
import logging
import subprocess
import threading
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

try:
    from .stream_buffer import BoundedTextBuffer
except ImportError:
    from stream_buffer import BoundedTextBuffer

OUTPUT_BEGIN_MARKER = "OUTPUT_BEGIN"
EXECUTOR_STREAM_BUFFER_MAX_CHARS = 2 * 1024 * 1024
EXECUTOR_STREAM_BUFFER_HEAD_CHARS = 32 * 1024
EXECUTOR_STREAM_TRUNCATION_MARKER = "\n...[executor stream truncated]...\n"


@dataclass
class ExecutorProgressEvent:
    kind: str
    detail: str = ""
    exit_code: Optional[int] = None


def parse_stream_json_line(raw_line: str) -> Optional[Dict[str, object]]:
    line = (raw_line or "").strip()
    if not line or not line.startswith("{"):
        return None
    try:
        payload = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def extract_executor_progress_event(payload: Dict[str, object]) -> Optional[ExecutorProgressEvent]:
    payload_type = payload.get("type")
    if payload_type == "turn.started":
        return ExecutorProgressEvent("turn_started", "Architect started working.")
    if payload_type == "turn.completed":
        return ExecutorProgressEvent("turn_completed", "Architect finished reasoning.")

    item = payload.get("item")
    if isinstance(item, dict):
        item_type = item.get("type")
        status = item.get("status")
        if item_type == "reasoning" and status == "in_progress":
            summary = item.get("summary")
            detail = ""
            if isinstance(summary, str):
                detail = summary
            return ExecutorProgressEvent("reasoning", detail)
        if item_type == "command_execution":
            command = item.get("command")
            if isinstance(command, str):
                command_text = command
            else:
                command_text = ""
            if status == "in_progress":
                return ExecutorProgressEvent("command_started", command_text)
            if status == "completed":
                exit_code = item.get("exit_code")
                parsed_exit: Optional[int] = exit_code if isinstance(exit_code, int) else None
                return ExecutorProgressEvent("command_completed", command_text, parsed_exit)
        if item_type == "agent_message" and status == "completed":
            text = item.get("text")
            detail = text if isinstance(text, str) else ""
            return ExecutorProgressEvent("agent_message", detail)

    return None


def run_executor(
    config,
    prompt: str,
    thread_id: Optional[str],
    image_path: Optional[str] = None,
    progress_callback: Optional[Callable[[ExecutorProgressEvent], None]] = None,
) -> subprocess.CompletedProcess[str]:
    cmd = list(config.executor_cmd)
    if thread_id:
        cmd.extend(["resume", thread_id])
    else:
        cmd.append("new")
    if image_path:
        cmd.extend(["--image", image_path])
    logging.info("Running executor command: %s", cmd)
    process = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )

    stdout_buffer = BoundedTextBuffer(
        EXECUTOR_STREAM_BUFFER_MAX_CHARS,
        head_chars=EXECUTOR_STREAM_BUFFER_HEAD_CHARS,
        truncation_marker=EXECUTOR_STREAM_TRUNCATION_MARKER,
    )
    stderr_buffer = BoundedTextBuffer(
        EXECUTOR_STREAM_BUFFER_MAX_CHARS,
        head_chars=EXECUTOR_STREAM_BUFFER_HEAD_CHARS,
        truncation_marker=EXECUTOR_STREAM_TRUNCATION_MARKER,
    )

    if process.stdin is None or process.stdout is None or process.stderr is None:
        raise RuntimeError("Failed to initialize executor process pipes")

    def drain_stdout() -> None:
        for raw_line in process.stdout:
            stdout_buffer.append(raw_line)
            payload = parse_stream_json_line(raw_line)
            if payload is None:
                continue
            event = extract_executor_progress_event(payload)
            if event and progress_callback:
                try:
                    progress_callback(event)
                except Exception:
                    logging.exception("Progress callback failure")

    def drain_stderr() -> None:
        for raw_line in process.stderr:
            stderr_buffer.append(raw_line)

    stdout_worker = threading.Thread(target=drain_stdout, daemon=True)
    stderr_worker = threading.Thread(target=drain_stderr, daemon=True)
    stdout_worker.start()
    stderr_worker.start()

    try:
        process.stdin.write(prompt)
        if not prompt.endswith("\n"):
            process.stdin.write("\n")
        process.stdin.close()
    except Exception:
        process.kill()
        process.wait(timeout=5)
        raise

    try:
        return_code = process.wait(timeout=config.exec_timeout_seconds)
    except subprocess.TimeoutExpired as exc:
        process.kill()
        process.wait(timeout=5)
        stdout_worker.join(timeout=1.5)
        stderr_worker.join(timeout=1.5)
        raise subprocess.TimeoutExpired(cmd, config.exec_timeout_seconds) from exc

    stdout_worker.join(timeout=1.5)
    stderr_worker.join(timeout=1.5)

    return subprocess.CompletedProcess(
        args=cmd,
        returncode=return_code,
        stdout=stdout_buffer.render(),
        stderr=stderr_buffer.render(),
    )


def parse_executor_output(stdout: str) -> tuple[Optional[str], str]:
    lines = (stdout or "").splitlines()
    thread_id: Optional[str] = None
    last_agent_message: Optional[str] = None
    output_lines: List[str] = []
    seen_output = False
    seen_json_events = False
    for line in lines:
        payload = parse_stream_json_line(line)
        if payload is not None:
            seen_json_events = True
            payload_type = payload.get("type")
            if payload_type == "thread.started":
                payload_thread_id = payload.get("thread_id")
                if isinstance(payload_thread_id, str) and payload_thread_id.strip():
                    thread_id = payload_thread_id.strip()
            elif payload_type == "item.completed":
                item = payload.get("item")
                if isinstance(item, dict) and item.get("type") == "agent_message":
                    text = item.get("text")
                    if isinstance(text, str):
                        last_agent_message = text

        if not seen_output:
            if line.startswith("THREAD_ID="):
                thread_id = line[len("THREAD_ID="):].strip()
                continue
            if line.strip() == OUTPUT_BEGIN_MARKER:
                seen_output = True
                continue
        else:
            output_lines.append(line)

    if seen_output:
        output = "\n".join(output_lines).strip()
    elif seen_json_events and last_agent_message is not None:
        output = last_agent_message.strip()
    else:
        output = (stdout or "").strip()
    return thread_id, output


def should_reset_thread_after_resume_failure(
    stderr: str,
    stdout: str,
) -> bool:
    combined = f"{stderr}\n{stdout}".lower()
    reset_markers = (
        "thread not found",
        "unknown thread",
        "invalid thread",
        "thread id not found",
        "conversation not found",
        "session not found",
        "no such thread",
        "could not find thread",
    )
    return any(marker in combined for marker in reset_markers)
