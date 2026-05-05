import json
import subprocess
import time
from pathlib import Path
from typing import Callable, Dict, List, Tuple
from urllib import error as urllib_error
from urllib import request as urllib_request

def _brief_health_error(error: object, limit: int = 180) -> str:
    text = str(error).strip().replace("\n", " ")
    if not text:
        return "unknown error"
    if len(text) > limit:
        return text[: limit - 3].rstrip() + "..."
    return text

def _parse_ollama_tags(payload: str) -> List[str]:
    data = json.loads(payload)
    models = data.get("models", [])
    if not isinstance(models, list):
        return []
    names: List[str] = []
    for item in models:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        if name:
            names.append(name)
    return names

def _parse_venice_model_ids(payload: str) -> List[str]:
    data = json.loads(payload)
    models = data.get("data", [])
    if not isinstance(models, list):
        return []
    names: List[str] = []
    for item in models:
        if not isinstance(item, dict):
            continue
        model_id = str(item.get("id", "")).strip()
        if model_id:
            names.append(model_id)
    return names

def check_gemma_health(
    config,
    *,
    health_timeout_seconds: int = 6,
    curl_timeout_seconds: int = 5,
) -> Dict[str, object]:
    provider = (
        str(getattr(config, "gemma_provider", "ollama_ssh") or "ollama_ssh")
        .strip()
        .lower()
    )
    model = str(getattr(config, "gemma_model", "gemma4:26b") or "gemma4:26b").strip()
    started = time.monotonic()
    try:
        if provider == "ollama_http":
            base_url = str(
                getattr(config, "gemma_base_url", "http://127.0.0.1:11434") or ""
            ).rstrip("/")
            if not base_url:
                raise ValueError("GEMMA_BASE_URL is empty")
            with urllib_request.urlopen(
                f"{base_url}/api/tags",
                timeout=health_timeout_seconds,
            ) as response:
                payload = response.read().decode("utf-8", errors="replace")
        elif provider == "ollama_ssh":
            host = str(getattr(config, "gemma_ssh_host", "server4-beast") or "").strip()
            if not host:
                raise ValueError("GEMMA_SSH_HOST is empty")
            remote_cmd = (
                "curl -sS "
                f"--max-time {curl_timeout_seconds} "
                "http://127.0.0.1:11434/api/tags"
            )
            completed = subprocess.run(
                [
                    "ssh",
                    "-o",
                    "BatchMode=yes",
                    "-o",
                    f"ConnectTimeout={health_timeout_seconds}",
                    host,
                    remote_cmd,
                ],
                capture_output=True,
                text=True,
                timeout=health_timeout_seconds + 2,
            )
            if completed.returncode != 0:
                raise RuntimeError(
                    completed.stderr.strip()
                    or completed.stdout.strip()
                    or f"ssh exited {completed.returncode}"
                )
            payload = completed.stdout
        else:
            raise ValueError(f"unsupported provider {provider!r}")
        elapsed_ms = int((time.monotonic() - started) * 1000)
        model_names = _parse_ollama_tags(payload)
        return {
            "ok": True,
            "response_ms": elapsed_ms,
            "model_available": model in model_names,
            "error": "",
        }
    except (
        OSError,
        RuntimeError,
        ValueError,
        json.JSONDecodeError,
        subprocess.TimeoutExpired,
        urllib_error.URLError,
    ) as exc:
        elapsed_ms = int((time.monotonic() - started) * 1000)
        return {
            "ok": False,
            "response_ms": elapsed_ms,
            "model_available": False,
            "error": _brief_health_error(exc),
        }

def check_venice_health(config, *, health_timeout_seconds: int = 6) -> Dict[str, object]:
    api_key = str(getattr(config, "venice_api_key", "") or "").strip()
    base_url = str(getattr(config, "venice_base_url", "https://api.venice.ai/api/v1") or "").strip().rstrip("/")
    model = str(getattr(config, "venice_model", "mistral-31-24b") or "mistral-31-24b").strip()
    if not api_key:
        return {
            "ok": False,
            "response_ms": 0,
            "model_available": False,
            "error": "VENICE_API_KEY is missing",
        }
    if not base_url:
        return {
            "ok": False,
            "response_ms": 0,
            "model_available": False,
            "error": "VENICE_BASE_URL is empty",
        }
    started = time.monotonic()
    try:
        request = urllib_request.Request(
            f"{base_url}/models",
            headers={"Authorization": f"Bearer {api_key}"},
            method="GET",
        )
        with urllib_request.urlopen(request, timeout=health_timeout_seconds) as response:
            payload = response.read().decode("utf-8")
        elapsed_ms = int((time.monotonic() - started) * 1000)
        model_names = _parse_venice_model_ids(payload)
        return {
            "ok": True,
            "response_ms": elapsed_ms,
            "model_available": model in model_names,
            "error": "",
        }
    except (OSError, RuntimeError, json.JSONDecodeError, subprocess.TimeoutExpired, urllib_error.URLError) as exc:
        elapsed_ms = int((time.monotonic() - started) * 1000)
        return {
            "ok": False,
            "response_ms": elapsed_ms,
            "model_available": False,
            "error": _brief_health_error(exc),
        }

def check_pi_health(
    config,
    *,
    provider: str,
    run_pi_command_fn: Callable[[object, str], subprocess.CompletedProcess[str]],
    parse_pi_model_rows_fn: Callable[[str], List[Tuple[str, str]]],
) -> Dict[str, object]:
    model = str(getattr(config, "pi_model", "qwen3-coder:30b") or "qwen3-coder:30b").strip()
    runner = str(getattr(config, "pi_runner", "ssh") or "ssh").strip().lower()
    host = str(getattr(config, "pi_ssh_host", "server4-beast") or "").strip()
    if runner not in {"local", "server3"} and not host:
        return {
            "ok": False,
            "response_ms": 0,
            "version": "",
            "model_available": False,
            "error": "PI_SSH_HOST is empty",
        }
    started = time.monotonic()
    try:
        version_completed = run_pi_command_fn(config, "pi --version")
        models_completed = run_pi_command_fn(config, "pi --list-models")
        elapsed_ms = int((time.monotonic() - started) * 1000)
        if version_completed.returncode != 0:
            raise RuntimeError(
                version_completed.stderr.strip()
                or version_completed.stdout.strip()
                or f"ssh exited {version_completed.returncode}"
            )
        if models_completed.returncode != 0:
            raise RuntimeError(
                models_completed.stderr.strip()
                or models_completed.stdout.strip()
                or f"ssh exited {models_completed.returncode}"
            )
        version_output = (version_completed.stdout.strip() or version_completed.stderr.strip()).strip()
        version_lines = version_output.splitlines()
        version = version_lines[0].strip() if version_lines else ""
        models_stdout = models_completed.stdout.strip() or models_completed.stderr.strip()
        model_available = any(
            row_provider == provider and row_model == model
            for row_provider, row_model in parse_pi_model_rows_fn(models_stdout)
        )
        return {
            "ok": True,
            "response_ms": elapsed_ms,
            "version": version,
            "model_available": model_available if model else False,
            "error": "",
        }
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
        elapsed_ms = int((time.monotonic() - started) * 1000)
        return {
            "ok": False,
            "response_ms": elapsed_ms,
            "version": "",
            "model_available": False,
            "error": _brief_health_error(exc),
        }

def check_chatgpt_web_health(config) -> Dict[str, object]:
    script = str(
        getattr(
            config,
            "chatgpt_web_bridge_script",
            str(Path(__file__).resolve().parents[2] / "ops" / "chatgpt_web_bridge.py"),
        )
        or ""
    ).strip()
    if not script:
        return {
            "ok": False,
            "response_ms": 0,
            "running": False,
            "chatgpt_tab": False,
            "error": "CHATGPT_WEB_BRIDGE_SCRIPT is empty",
        }
    cmd = [
        str(getattr(config, "chatgpt_web_python_bin", "python3") or "python3"),
        script,
        "--base-url",
        str(getattr(config, "chatgpt_web_browser_brain_url", "http://127.0.0.1:47831") or "http://127.0.0.1:47831"),
        "--service-name",
        str(getattr(config, "chatgpt_web_browser_brain_service", "server3-browser-brain.service") or "server3-browser-brain.service"),
        "--request-timeout",
        str(int(getattr(config, "chatgpt_web_request_timeout_seconds", 30) or 30)),
        "status",
    ]
    started = time.monotonic()
    try:
        completed = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=int(getattr(config, "chatgpt_web_request_timeout_seconds", 30) or 30) + 5,
        )
        elapsed_ms = int((time.monotonic() - started) * 1000)
        if completed.returncode != 0:
            raise RuntimeError(
                completed.stderr.strip()
                or completed.stdout.strip()
                or f"chatgpt web status exited {completed.returncode}"
            )
        payload = json.loads(completed.stdout or "{}")
        tabs = payload.get("tabs", [])
        if not isinstance(tabs, list):
            tabs = []
        chatgpt_tab = any(
            isinstance(tab, dict) and "chatgpt.com" in str(tab.get("url") or "")
            for tab in tabs
        )
        return {
            "ok": True,
            "response_ms": elapsed_ms,
            "running": bool(payload.get("running")),
            "chatgpt_tab": chatgpt_tab,
            "error": "",
        }
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError, subprocess.TimeoutExpired) as exc:
        elapsed_ms = int((time.monotonic() - started) * 1000)
        return {
            "ok": False,
            "response_ms": elapsed_ms,
            "running": False,
            "chatgpt_tab": False,
            "error": _brief_health_error(exc),
        }
