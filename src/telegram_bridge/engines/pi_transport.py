import json
import os
import shlex
from typing import Callable, Optional


def _pi_request_timeout(config) -> int:
    return int(getattr(config, "pi_request_timeout_seconds", 180))


def _pi_local_cwd(config) -> Optional[str]:
    return str(getattr(config, "pi_local_cwd", "") or "").strip() or None


def _pi_remote_cwd(config) -> str:
    return str(getattr(config, "pi_remote_cwd", "/tmp") or "/tmp").strip()


def _pi_ssh_host(config) -> str:
    return str(getattr(config, "pi_ssh_host", "server4-beast")).strip() or "server4-beast"


def _pi_ollama_local_port(config) -> int:
    return int(getattr(config, "pi_ollama_tunnel_local_port", 11435))


def _pi_ollama_remote_host(config) -> str:
    return str(getattr(config, "pi_ollama_tunnel_remote_host", "127.0.0.1") or "127.0.0.1").strip()


def _pi_ollama_remote_port(config) -> int:
    return int(getattr(config, "pi_ollama_tunnel_remote_port", 11434))


def pi_provider_uses_ollama_tunnel(config) -> bool:
    provider = (
        str(getattr(config, "pi_provider", "ollama") or "ollama")
        .strip()
        .lower()
    )
    return provider in {"ollama", "ollama_ssh", "ssh"}


def run_pi_text_local(
    config,
    prompt: str,
    session_key: Optional[str],
    *,
    build_pi_text_args,
    subprocess_module,
) -> str:
    cmd = build_pi_text_args(
        config,
        include_no_context_files=False,
        session_key=session_key,
    )
    env = os.environ.copy()
    env["OLLAMA_HOST"] = f"http://127.0.0.1:{_pi_ollama_local_port(config)}"
    completed = subprocess_module.run(
        cmd + [prompt],
        cwd=_pi_local_cwd(config),
        env=env,
        capture_output=True,
        text=True,
        timeout=_pi_request_timeout(config),
    )
    if completed.returncode != 0:
        raise RuntimeError(
            completed.stderr.strip()
            or completed.stdout.strip()
            or "Pi text-mode local runner failed."
        )
    output = (completed.stdout or "").strip()
    if not output:
        raise RuntimeError("Pi text-mode local runner produced no output.")
    return output


def run_pi_text_ssh(
    config,
    prompt: str,
    *,
    build_pi_text_args,
    subprocess_module,
) -> str:
    timeout = _pi_request_timeout(config)
    args = ["timeout", str(timeout)] + build_pi_text_args(
        config,
        include_no_context_files=True,
        session_key=None,
    )
    quoted = " ".join(shlex.quote(part) for part in args + [prompt])
    remote_cwd = _pi_remote_cwd(config)
    remote_command = f"cd {shlex.quote(remote_cwd)} && {quoted}" if remote_cwd else quoted
    completed = subprocess_module.run(
        ["ssh", "-o", "BatchMode=yes", _pi_ssh_host(config), remote_command],
        capture_output=True,
        text=True,
        timeout=timeout + 5,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            completed.stderr.strip()
            or completed.stdout.strip()
            or "Pi text-mode SSH runner failed."
        )
    output = (completed.stdout or "").strip()
    if not output:
        raise RuntimeError("Pi text-mode SSH runner produced no output.")
    return output


def read_rpc_stdout(
    process,
    cancel_event,
    timeout: int,
    *,
    time_module,
    executor_cancelled_error_cls,
    on_text_delta: Optional[Callable[[str], None]] = None,
) -> list[str]:
    """Drain the Pi RPC stdout stream line-by-line.

    When ``on_text_delta`` is provided, fires it with each
    ``message_update`` / ``text_delta`` event's ``delta`` field as
    soon as the line is read. The callback is invoked from the same
    thread that reads stdout (typically a worker thread spawned by
    the bridge request worker), so it must be thread-safe and
    non-blocking — the standard use is to push into a thread-safe
    queue (the bridge's ``StreamConsumer.on_delta`` is exactly that).
    """
    lines: list[str] = []
    start = time_module.monotonic()
    while time_module.monotonic() - start < timeout:
        if cancel_event is not None and cancel_event.is_set():
            process.kill()
            raise executor_cancelled_error_cls("Pi request canceled by user.")
        line = process.stdout.readline() if process.stdout else ""
        if not line:
            if process.poll() is not None:
                break
            time_module.sleep(0.05)
            continue
        lines.append(line)
        if on_text_delta is not None:
            try:
                _maybe_emit_text_delta(line, on_text_delta)
            except Exception:
                # The callback must never break the read loop — if it
                # raised, the streaming preview would freeze for the
                # user. Errors are swallowed.
                pass
        if '"type":"agent_end"' in line or '"type": "agent_end"' in line:
            break
    return lines


def _maybe_emit_text_delta(line: str, on_text_delta: Callable[[str], None]) -> None:
    """Parse one Pi RPC stdout line and emit its ``text_delta`` if any.

    The Pi RPC protocol uses a JSON line stream. Token deltas arrive
    as::

        {"type":"message_update","assistantMessageEvent":{"type":"text_delta","delta":"hello"}}

    This helper does a tiny string scan first (avoids the JSON parse
    cost on every non-delta line) and only decodes lines that look
    like a ``message_update`` carrying a ``text_delta`` event.
    """
    if '"message_update"' not in line or '"text_delta"' not in line:
        return
    try:
        event = json.loads(line)
    except (ValueError, TypeError):
        return
    if not isinstance(event, dict) or event.get("type") != "message_update":
        return
    sub = event.get("assistantMessageEvent")
    if not isinstance(sub, dict) or sub.get("type") != "text_delta":
        return
    delta = sub.get("delta")
    if isinstance(delta, str) and delta:
        on_text_delta(delta)


def build_remote_command(
    config,
    *,
    build_pi_rpc_args,
) -> str:
    timeout = _pi_request_timeout(config)
    args = ["timeout", str(timeout)] + build_pi_rpc_args(
        config,
        include_no_context_files=True,
        session_key=None,
    )
    quoted = " ".join(shlex.quote(part) for part in args)
    remote_cwd = _pi_remote_cwd(config)
    if remote_cwd:
        return f"cd {shlex.quote(remote_cwd)} && {quoted}"
    return quoted


def local_ollama_tunnel_healthy(
    port: int,
    *,
    socket_module,
) -> bool:
    try:
        with socket_module.create_connection(("127.0.0.1", port), timeout=1.0):
            return True
    except OSError:
        return False


def ensure_local_ollama_tunnel(
    config,
    *,
    local_ollama_tunnel_healthy_fn,
    subprocess_module,
    time_module,
) -> None:
    enabled = bool(getattr(config, "pi_ollama_tunnel_enabled", True))
    if not enabled:
        return
    port = _pi_ollama_local_port(config)
    if local_ollama_tunnel_healthy_fn(port):
        return
    tunnel_spec = f"127.0.0.1:{port}:{_pi_ollama_remote_host(config)}:{_pi_ollama_remote_port(config)}"
    completed = subprocess_module.run(
        [
            "ssh",
            "-fN",
            "-o",
            "ExitOnForwardFailure=yes",
            "-o",
            "BatchMode=yes",
            "-L",
            tunnel_spec,
            _pi_ssh_host(config),
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if completed.returncode != 0 and not local_ollama_tunnel_healthy_fn(port):
        raise RuntimeError(
            completed.stderr.strip()
            or completed.stdout.strip()
            or f"failed to start Pi Ollama tunnel on port {port}"
        )
    deadline = time_module.monotonic() + 5
    while time_module.monotonic() < deadline:
        if local_ollama_tunnel_healthy_fn(port):
            return
        time_module.sleep(0.1)
    raise RuntimeError(f"Pi Ollama tunnel did not become ready on port {port}")


def run_pi_ssh(
    config,
    prompt: str,
    cancel_event,
    *,
    image_path,
    image_paths,
    build_rpc_prompt_json,
    build_remote_command_fn,
    read_rpc_stdout_fn,
    extract_rpc_response,
    should_retry_pi_text_mode,
    run_pi_text_ssh_fn,
    subprocess_module,
    executor_cancelled_error_cls,
    on_text_delta=None,
) -> str:
    timeout = _pi_request_timeout(config)
    prompt_json = build_rpc_prompt_json(
        prompt,
        image_path=image_path,
        image_paths=image_paths,
    )
    process = subprocess_module.Popen(
        [
            "ssh",
            "-o",
            "BatchMode=yes",
            _pi_ssh_host(config),
            build_remote_command_fn(config),
        ],
        stdin=subprocess_module.PIPE,
        stdout=subprocess_module.PIPE,
        stderr=subprocess_module.PIPE,
        text=True,
    )
    try:
        process.stdin.write(prompt_json + "\n")
        process.stdin.flush()
        stdout_lines = read_rpc_stdout_fn(
            process,
            cancel_event,
            timeout + 10,
            on_text_delta=on_text_delta,
        )
        process.stdin.close()
        process.stdin = None
        _, stderr = process.communicate(timeout=5)
    except BaseException:
        process.kill()
        raise
    if cancel_event is not None and cancel_event.is_set():
        raise executor_cancelled_error_cls("Pi request canceled by user.")
    if process.returncode != 0:
        raise RuntimeError(((stderr or "") + "\nstdout_lines=%d" % len(stdout_lines) or "".join(stdout_lines) or "Pi SSH transport failed.").strip())
    try:
        return extract_rpc_response(stdout_lines)
    except RuntimeError as exc:
        if not should_retry_pi_text_mode(
            exc,
            image_path=image_path,
            image_paths=image_paths,
        ):
            raise
        return run_pi_text_ssh_fn(config, prompt)


def run_pi_local(
    config,
    prompt: str,
    session_key: Optional[str],
    cancel_event,
    *,
    image_path,
    image_paths,
    pi_provider_uses_ollama_tunnel_fn,
    ensure_local_ollama_tunnel_fn,
    build_rpc_prompt_json,
    build_pi_rpc_args,
    read_rpc_stdout_fn,
    extract_rpc_response,
    should_retry_pi_text_mode,
    run_pi_text_local_fn,
    subprocess_module,
    executor_cancelled_error_cls,
    on_text_delta=None,
) -> str:
    timeout = _pi_request_timeout(config)
    if pi_provider_uses_ollama_tunnel_fn(config):
        ensure_local_ollama_tunnel_fn(config)
    prompt_json = build_rpc_prompt_json(
        prompt,
        image_path=image_path,
        image_paths=image_paths,
    )
    cmd = build_pi_rpc_args(
        config,
        include_no_context_files=False,
        session_key=session_key,
    )
    env = os.environ.copy()
    env["OLLAMA_HOST"] = f"http://127.0.0.1:{_pi_ollama_local_port(config)}"
    process = subprocess_module.Popen(
        cmd,
        cwd=_pi_local_cwd(config),
        stdin=subprocess_module.PIPE,
        stdout=subprocess_module.PIPE,
        stderr=subprocess_module.PIPE,
        text=True,
        env=env,
    )
    try:
        process.stdin.write(prompt_json + "\n")
        process.stdin.flush()
        stdout_lines = read_rpc_stdout_fn(
            process,
            cancel_event,
            timeout + 10,
            on_text_delta=on_text_delta,
        )
        process.stdin.close()
        process.stdin = None
        _, stderr = process.communicate(timeout=5)
    except BaseException:
        process.kill()
        raise
    if cancel_event is not None and cancel_event.is_set():
        raise executor_cancelled_error_cls("Pi request canceled by user.")
    if process.returncode != 0:
        raise RuntimeError(((stderr or "") + "\nstdout_lines=%d" % len(stdout_lines) or "".join(stdout_lines) or "Pi local runner failed.").strip())
    try:
        return extract_rpc_response(stdout_lines)
    except RuntimeError as exc:
        if not should_retry_pi_text_mode(
            exc,
            image_path=image_path,
            image_paths=image_paths,
        ):
            raise
        return run_pi_text_local_fn(config, prompt, session_key)
