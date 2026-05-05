import os
import shlex
import subprocess
from typing import Dict, List, Optional, Tuple

from telegram_bridge import engine_health
from telegram_bridge.engine_catalog import (
    PI_PROVIDER_CHOICES,
    configured_pi_provider,
    normalize_pi_provider_name,
    pi_provider_uses_ollama_tunnel,
)

GEMMA_HEALTH_TIMEOUT_SECONDS = 6


def brief_health_error(exc: Exception) -> str:
    return engine_health._brief_health_error(exc)


def pi_provider_description(provider_name: str) -> str:
    normalized = normalize_pi_provider_name(provider_name)
    for provider, description in PI_PROVIDER_CHOICES:
        if provider == normalized:
            return description
    return "custom Pi provider"


def pi_provider_sort_key(provider_name: str) -> Tuple[int, str]:
    normalized = normalize_pi_provider_name(provider_name)
    for index, (provider, _description) in enumerate(PI_PROVIDER_CHOICES):
        if provider == normalized:
            return (index, normalized)
    return (len(PI_PROVIDER_CHOICES), normalized)


def pi_provider_choice_lines(current_provider: str) -> List[str]:
    lines: List[str] = []
    for provider, description in PI_PROVIDER_CHOICES:
        marker = " (current)" if provider == current_provider else ""
        lines.append(f"- {provider}{marker} - {description}")
    return lines


def run_pi_command(config, command: str) -> subprocess.CompletedProcess[str]:
    pi_bin = str(getattr(config, "pi_bin", "pi") or "pi").strip() or "pi"
    argv = shlex.split(command)
    if argv and argv[0] == "pi":
        argv[0] = pi_bin
    command_text = shlex.join(argv) if argv else shlex.quote(pi_bin)
    runner = str(getattr(config, "pi_runner", "ssh") or "ssh").strip().lower()
    timeout = GEMMA_HEALTH_TIMEOUT_SECONDS + 4
    if runner in {"local", "server3"}:
        env = None
        if pi_provider_uses_ollama_tunnel(config):
            tunnel_port = int(getattr(config, "pi_ollama_tunnel_local_port", 11435))
            env = os.environ.copy()
            env["OLLAMA_HOST"] = f"http://127.0.0.1:{tunnel_port}"
        return subprocess.run(
            argv or [pi_bin],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(getattr(config, "pi_local_cwd", "") or "").strip() or None,
            env=env,
        )
    host = str(getattr(config, "pi_ssh_host", "server4-beast") or "").strip() or "server4-beast"
    return subprocess.run(
        [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            f"ConnectTimeout={GEMMA_HEALTH_TIMEOUT_SECONDS}",
            host,
            f"command -v {shlex.quote(pi_bin)} >/dev/null && {command_text}",
        ],
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def parse_pi_model_rows(payload: str) -> List[Tuple[str, str]]:
    rows: List[Tuple[str, str]] = []
    for raw_line in str(payload or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.lower().startswith("provider"):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        rows.append((parts[0], parts[1]))
    return rows


def pi_model_rows(config) -> List[Tuple[str, str]]:
    completed = run_pi_command(config, "pi --list-models")
    if completed.returncode != 0:
        raise RuntimeError(
            completed.stderr.strip()
            or completed.stdout.strip()
            or f"ssh exited {completed.returncode}"
        )
    payload = completed.stdout.strip() or completed.stderr.strip()
    return parse_pi_model_rows(payload)


def pi_available_provider_names(config) -> List[str]:
    names = {
        normalize_pi_provider_name(row_provider)
        for row_provider, row_model in pi_model_rows(config)
        if str(row_provider).strip() and str(row_model).strip()
    }
    if not names:
        return []
    return sorted(names, key=pi_provider_sort_key)


def pi_provider_model_names(config) -> List[str]:
    provider = configured_pi_provider(config)
    model_names = [
        row_model
        for row_provider, row_model in pi_model_rows(config)
        if row_provider.strip().lower() == provider
    ]
    return sorted(dict.fromkeys(model_names), key=str.casefold)


def resolve_pi_model_candidate(available_models: List[str], requested_model: str) -> Optional[str]:
    requested = requested_model.strip()
    if not requested:
        return None
    for available in available_models:
        if available == requested:
            return available
    folded = requested.casefold()
    matches = [available for available in available_models if available.casefold() == folded]
    if len(matches) == 1:
        return matches[0]
    return None
