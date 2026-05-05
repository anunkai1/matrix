import os
import subprocess
import time
from pathlib import Path
from typing import List, Optional

from telegram_bridge.executor import ExecutorCancelledError

DISHFRAMED_REPO_ROOT = Path(
    os.getenv("DISHFRAMED_REPO_ROOT", "/home/architect/dishframed")
).expanduser()
DISHFRAMED_PYTHON_BIN = Path(
    os.getenv("DISHFRAMED_PYTHON_BIN", str(DISHFRAMED_REPO_ROOT / ".venv/bin/python"))
).expanduser()
DISHFRAMED_USAGE_MESSAGE = (
    "Send `/dishframed` with a menu photo, or reply `/dishframed` to a menu photo."
)

def build_dishframed_command(image_paths: List[str], output_dir: str) -> List[str]:
    cmd = [
        str(DISHFRAMED_PYTHON_BIN),
        "-m",
        "dishframed",
        "frame",
        "--extractor",
        "auto",
        "--output-dir",
        output_dir,
    ]
    for image_path in image_paths:
        cmd.extend(["--image", image_path])
    return cmd

def parse_dishframed_cli_output(stdout: str) -> tuple[Optional[str], str]:
    output_path: Optional[str] = None
    preview_text = ""
    for raw_line in (stdout or "").splitlines():
        line = raw_line.strip()
        if line.startswith("Output:"):
            candidate = line.split(":", 1)[1].strip()
            if candidate:
                output_path = candidate
            continue
        if line:
            preview_text = line
    return output_path, preview_text

def run_dishframed_cli(
    *,
    image_paths: List[str],
    output_dir: str,
    timeout_seconds: int,
    cancel_event=None,
) -> tuple[str, str]:
    if not DISHFRAMED_REPO_ROOT.is_dir():
        raise RuntimeError(f"DishFramed repo not found: {DISHFRAMED_REPO_ROOT}")
    if not DISHFRAMED_PYTHON_BIN.is_file():
        raise RuntimeError(f"DishFramed Python not found: {DISHFRAMED_PYTHON_BIN}")

    cmd = build_dishframed_command(image_paths, output_dir)
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=str(DISHFRAMED_REPO_ROOT),
    )
    stdout = ""
    stderr = ""
    started_at = time.monotonic()
    while True:
        if cancel_event is not None and cancel_event.is_set():
            process.kill()
            process.wait(timeout=5)
            raise ExecutorCancelledError("DishFramed request canceled by user.")
        if (time.monotonic() - started_at) >= float(timeout_seconds):
            process.kill()
            process.wait(timeout=5)
            raise subprocess.TimeoutExpired(cmd, timeout_seconds)
        try:
            stdout, stderr = process.communicate(timeout=0.2)
            break
        except subprocess.TimeoutExpired:
            continue

    if process.returncode != 0:
        raise RuntimeError((stderr or stdout or "DishFramed command failed.").strip())

    output_path, preview_text = parse_dishframed_cli_output(stdout)
    if not output_path:
        raise RuntimeError("DishFramed command did not report an output path.")
    return output_path, preview_text
