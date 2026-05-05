import base64
import json
import mimetypes
import hashlib
import os
import re
import shlex
import socket
import subprocess
import threading
import sys
import time
from pathlib import Path
from typing import Callable, Optional, Protocol
from urllib import error as urllib_error
from urllib import request as urllib_request

from telegram_bridge.background_tasks import start_daemon_thread
from telegram_bridge.executor import (
    ExecutorCancelledError,
    ExecutorProgressEvent,
    OUTPUT_BEGIN_MARKER,
    parse_executor_output,
    run_executor,
)

ProgressCallback = Callable[[ExecutorProgressEvent], None]

def _completed_process_with_output(
    engine_name: str,
    output: str,
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=[engine_name],
        returncode=0,
        stdout=f"{OUTPUT_BEGIN_MARKER}\n{str(output or '').strip()}",
        stderr="",
    )

def _communicate_process_with_cancel(
    process: subprocess.Popen[str],
    *,
    timeout: int,
    cancel_event: Optional[threading.Event],
    cancel_message: str,
    input_text: Optional[str] = None,
) -> tuple[str, str]:
    result: dict[str, object] = {}
    done = threading.Event()

    def _worker() -> None:
        try:
            stdout, stderr = process.communicate(input=input_text, timeout=timeout)
            result["stdout"] = stdout
            result["stderr"] = stderr
        except BaseException as exc:
            result["exception"] = exc
        finally:
            done.set()

    start_daemon_thread(_worker)
    while not done.wait(0.1):
        if cancel_event is not None and cancel_event.is_set():
            process.kill()
            done.wait(5)
            raise ExecutorCancelledError(cancel_message)

    exc = result.get("exception")
    if isinstance(exc, BaseException):
        raise exc
    stdout = result.get("stdout")
    stderr = result.get("stderr")
    return str(stdout or ""), str(stderr or "")

def _run_blocking_with_cancel(
    func: Callable[[], str],
    *,
    cancel_event: Optional[threading.Event],
    cancel_message: str,
) -> str:
    result: dict[str, object] = {}
    done = threading.Event()

    def _worker() -> None:
        try:
            result["value"] = func()
        except BaseException as exc:
            result["exception"] = exc
        finally:
            done.set()

    start_daemon_thread(_worker)
    while not done.wait(0.1):
        if cancel_event is not None and cancel_event.is_set():
            raise ExecutorCancelledError(cancel_message)

    exc = result.get("exception")
    if isinstance(exc, BaseException):
        raise exc
    return str(result.get("value") or "")

class EngineAdapter(Protocol):
    engine_name: str

    def run(
        self,
        config,
        prompt: str,
        thread_id: Optional[str],
        session_key: Optional[str] = None,
        channel_name: Optional[str] = None,
        actor_chat_id: Optional[int] = None,
        actor_user_id: Optional[int] = None,
        image_path: Optional[str] = None,
        image_paths: Optional[list[str]] = None,
        progress_callback: Optional[ProgressCallback] = None,
        cancel_event: Optional[threading.Event] = None,
        ) -> subprocess.CompletedProcess[str]:
        ...

class CompletedProcessOutputMixin:
    engine_name: str

    def _completed_process_with_output(self, output: str) -> subprocess.CompletedProcess[str]:
        return _completed_process_with_output(self.engine_name, output)

