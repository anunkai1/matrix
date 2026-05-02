import copy
import json
import os
import shlex
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

if __package__:
    from .channel_adapter import ChannelAdapter
    from .engine_adapter import EngineAdapter
    from . import engine_health
    from .plugin_registry import build_default_plugin_registry
    from .state_store import State, StateRepository
else:
    from channel_adapter import ChannelAdapter
    from engine_adapter import EngineAdapter
    import engine_health
    from plugin_registry import build_default_plugin_registry
    from state_store import State, StateRepository


GEMMA_HEALTH_TIMEOUT_SECONDS = 6
GEMMA_HEALTH_CURL_TIMEOUT_SECONDS = 5

ENGINE_NAME_ALIASES = {
    "chatgpt": "chatgptweb",
}
PI_PROVIDER_ALIASES = {
    "ollama_http": "ollama",
    "ollama_ssh": "ollama",
}
PI_PROVIDER_CHOICES = (
    ("ollama", "local Ollama or SSH-tunneled Ollama"),
    ("venice", "Venice API models"),
    ("deepseek", "DeepSeek API models"),
)
PI_MODEL_PICKER_PAGE_SIZE = 16
_brief_health_error = engine_health._brief_health_error


def normalize_engine_name(engine_name: str) -> str:
    normalized = str(engine_name or "").strip().lower()
    return ENGINE_NAME_ALIASES.get(normalized, normalized)


def configured_default_engine(config) -> str:
    return normalize_engine_name(getattr(config, "engine_plugin", "codex") or "codex")


def selectable_engine_plugins(config) -> List[str]:
    configured: List[str] = []
    for value in getattr(config, "selectable_engine_plugins", ["codex", "gemma", "pi"]):
        normalized = normalize_engine_name(str(value))
        if normalized and normalized not in configured:
            configured.append(normalized)
    default_engine = configured_default_engine(config)
    if default_engine not in configured:
        configured.insert(0, default_engine)
    return configured


def configured_pi_provider(config) -> str:
    provider = str(getattr(config, "pi_provider", "ollama") or "ollama").strip().lower()
    return PI_PROVIDER_ALIASES.get(provider, provider) or "ollama"


def normalize_pi_provider_name(provider_name: str) -> str:
    provider = str(provider_name or "").strip().lower()
    return PI_PROVIDER_ALIASES.get(provider, provider)


def configured_pi_model(config) -> str:
    return str(getattr(config, "pi_model", "qwen3-coder:30b") or "qwen3-coder:30b").strip() or "qwen3-coder:30b"


def pi_provider_uses_ollama_tunnel(config) -> bool:
    return configured_pi_provider(config) == "ollama"


def configured_codex_model(config) -> str:
    return str(getattr(config, "codex_model", "") or "").strip()


def configured_codex_reasoning_effort(config) -> str:
    return str(getattr(config, "codex_reasoning_effort", "") or "").strip().lower()


def _codex_models_cache_path() -> Path:
    codex_home = str(os.getenv("CODEX_HOME", "") or "").strip()
    if codex_home:
        return Path(codex_home).expanduser() / "models_cache.json"
    return Path.home() / ".codex" / "models_cache.json"


def _load_codex_model_catalog() -> List[Dict[str, object]]:
    cache_path = _codex_models_cache_path()
    if not cache_path.exists():
        return []
    data = json.loads(cache_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return []
    models = data.get("models")
    if not isinstance(models, list):
        return []
    catalog: List[Dict[str, object]] = []
    seen: Set[str] = set()
    for item in models:
        if not isinstance(item, dict):
            continue
        slug = str(item.get("slug", "") or "").strip()
        if not slug:
            continue
        visibility = str(item.get("visibility", "") or "").strip().lower()
        if visibility and visibility != "list":
            continue
        key = slug.casefold()
        if key in seen:
            continue
        seen.add(key)
        display_name = str(item.get("display_name", "") or "").strip() or slug
        efforts: List[str] = []
        raw_efforts = item.get("supported_reasoning_levels")
        if isinstance(raw_efforts, list):
            for raw_effort in raw_efforts:
                if not isinstance(raw_effort, dict):
                    continue
                effort = str(raw_effort.get("effort", "") or "").strip().lower()
                if effort and effort not in efforts:
                    efforts.append(effort)
        catalog.append(
            {
                "slug": slug,
                "display_name": display_name,
                "supported_efforts": efforts,
            }
        )
    return catalog


def _load_codex_model_choices() -> List[Tuple[str, str]]:
    choices: List[Tuple[str, str]] = []
    for item in _load_codex_model_catalog():
        slug = str(item.get("slug", "") or "").strip()
        if not slug:
            continue
        display_name = str(item.get("display_name", "") or "").strip() or slug
        choices.append((slug, display_name))
    return choices


def _supported_codex_efforts_for_model(model_name: str) -> List[str]:
    normalized_model = str(model_name or "").strip()
    default_efforts = ["low", "medium", "high", "xhigh"]
    if not normalized_model:
        return default_efforts
    folded = normalized_model.casefold()
    for item in _load_codex_model_catalog():
        slug = str(item.get("slug", "") or "").strip()
        display_name = str(item.get("display_name", "") or "").strip()
        if slug.casefold() != folded and display_name.casefold() != folded:
            continue
        efforts = [
            str(value).strip().lower()
            for value in item.get("supported_efforts", [])
            if str(value).strip()
        ]
        return efforts or default_efforts
    return default_efforts


def _resolve_codex_effort_candidate(model_name: str, requested_effort: str) -> Optional[str]:
    normalized_effort = str(requested_effort or "").strip().lower()
    if not normalized_effort:
        return None
    for effort in _supported_codex_efforts_for_model(model_name):
        if effort == normalized_effort:
            return effort
    return None


def _resolve_codex_model_candidate(requested_model: str) -> str:
    requested = str(requested_model or "").strip()
    if not requested:
        return ""
    folded = requested.casefold()
    for slug, display_name in _load_codex_model_choices():
        if slug.casefold() == folded or display_name.casefold() == folded:
            return slug
    return requested


def build_engine_runtime_config(state, config, scope_key: str, engine_name: str):
    runtime_config = copy.copy(config)
    normalized_engine = normalize_engine_name(engine_name)
    if normalized_engine == "codex":
        override_model = StateRepository(state).get_chat_codex_model(scope_key)
        override_effort = StateRepository(state).get_chat_codex_effort(scope_key)
        if not override_model and not override_effort:
            return config
        if override_model:
            runtime_config.codex_model = override_model
        if override_effort:
            runtime_config.codex_reasoning_effort = override_effort
        return runtime_config
    if normalized_engine != "pi":
        return config
    override_provider = StateRepository(state).get_chat_pi_provider(scope_key)
    override_model = StateRepository(state).get_chat_pi_model(scope_key)
    if not override_provider and not override_model:
        return config
    if override_provider:
        runtime_config.pi_provider = override_provider
    if override_model:
        runtime_config.pi_model = override_model
    return runtime_config


def _build_codex_model_source_text(state: State, scope_key: str) -> str:
    if StateRepository(state).get_chat_codex_model(scope_key):
        return "chat override"
    return "global default"


def _build_codex_effort_source_text(state: State, scope_key: str) -> str:
    if StateRepository(state).get_chat_codex_effort(scope_key):
        return "chat override"
    return "global default"


def _build_pi_provider_source_text(state: State, scope_key: str) -> str:
    if StateRepository(state).get_chat_pi_provider(scope_key):
        return "chat override"
    return "global default"


def _build_pi_model_source_text(state: State, scope_key: str) -> str:
    if StateRepository(state).get_chat_pi_model(scope_key):
        return "chat override"
    return "global default"


def _pi_provider_choice_lines(current_provider: str) -> List[str]:
    lines: List[str] = []
    for provider, description in PI_PROVIDER_CHOICES:
        marker = " (current)" if provider == current_provider else ""
        lines.append(f"- {provider}{marker} - {description}")
    return lines


def _pi_provider_description(provider_name: str) -> str:
    normalized = normalize_pi_provider_name(provider_name)
    for provider, description in PI_PROVIDER_CHOICES:
        if provider == normalized:
            return description
    return "custom Pi provider"


def _pi_provider_sort_key(provider_name: str) -> Tuple[int, str]:
    normalized = normalize_pi_provider_name(provider_name)
    for index, (provider, _description) in enumerate(PI_PROVIDER_CHOICES):
        if provider == normalized:
            return (index, normalized)
    return (len(PI_PROVIDER_CHOICES), normalized)


def _pi_available_provider_names(config) -> List[str]:
    names = {
        normalize_pi_provider_name(row_provider)
        for row_provider, row_model in _pi_model_rows(config)
        if str(row_provider).strip() and str(row_model).strip()
    }
    if not names:
        return []
    return sorted(names, key=_pi_provider_sort_key)


def build_pi_providers_text(state: State, config, scope_key: str) -> str:
    display_config = build_engine_runtime_config(state, config, scope_key, "pi")
    provider = configured_pi_provider(display_config)
    try:
        available_providers = _pi_available_provider_names(display_config)
    except (OSError, RuntimeError, subprocess.TimeoutExpired):
        available_providers = []
    lines = [
        f"Pi provider: {provider}",
        f"Pi provider source: {_build_pi_provider_source_text(state, scope_key)}",
        "Available Pi providers:",
    ]
    if available_providers:
        for provider_name in available_providers:
            marker = " (current)" if provider_name == provider else ""
            lines.append(f"- {provider_name}{marker} - {_pi_provider_description(provider_name)}")
    else:
        lines.extend(_pi_provider_choice_lines(provider))
    lines.append("Use /pi provider <name> to switch this chat.")
    return "\n".join(lines)


def _run_pi_command(config, command: str) -> subprocess.CompletedProcess[str]:
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
            env.setdefault("OLLAMA_HOST", f"http://127.0.0.1:{tunnel_port}")
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


def _parse_pi_model_rows(payload: str) -> List[Tuple[str, str]]:
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


def _pi_model_rows(config) -> List[Tuple[str, str]]:
    completed = _run_pi_command(config, "pi --list-models")
    if completed.returncode != 0:
        raise RuntimeError(
            completed.stderr.strip()
            or completed.stdout.strip()
            or f"ssh exited {completed.returncode}"
        )
    payload = completed.stdout.strip() or completed.stderr.strip()
    return _parse_pi_model_rows(payload)


def _pi_provider_model_names(config) -> List[str]:
    provider = configured_pi_provider(config)
    model_names = [
        row_model
        for row_provider, row_model in _pi_model_rows(config)
        if row_provider.strip().lower() == provider
    ]
    return sorted(dict.fromkeys(model_names), key=str.casefold)


def _resolve_pi_model_candidate(available_models: List[str], requested_model: str) -> Optional[str]:
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


def build_pi_models_text(state: State, config, scope_key: str) -> str:
    display_config = build_engine_runtime_config(state, config, scope_key, "pi")
    provider = configured_pi_provider(display_config)
    current_model = configured_pi_model(display_config)
    provider_source = _build_pi_provider_source_text(state, scope_key)
    source_text = _build_pi_model_source_text(state, scope_key)
    model_names = _pi_provider_model_names(display_config)
    if not model_names:
        return "\n".join(
            [
                f"Pi provider: {provider}",
                f"Pi provider source: {provider_source}",
                "No Pi models were reported for this provider.",
                "Use /engine status to check Pi health.",
            ]
        )
    lines = [
        f"Pi provider: {provider}",
        f"Pi provider source: {provider_source}",
        f"Current Pi model: {current_model} ({source_text})",
        "Available Pi models:",
    ]
    lines.extend(f"- {model_name}" for model_name in model_names)
    return "\n".join(lines)


def build_pi_status_text(state: State, config, scope_key: str) -> str:
    display_config = build_engine_runtime_config(state, config, scope_key, "pi")
    provider = configured_pi_provider(display_config)
    runner = str(getattr(display_config, "pi_runner", "ssh") or "ssh").strip().lower()
    lines = [
        f"Pi provider: {provider}",
        f"Pi provider source: {_build_pi_provider_source_text(state, scope_key)}",
        f"Pi model: {configured_pi_model(display_config)}",
        f"Pi model source: {_build_pi_model_source_text(state, scope_key)}",
        f"Pi runner: {getattr(display_config, 'pi_runner', 'ssh')}",
        f"Pi session mode: {getattr(display_config, 'pi_session_mode', 'none')}",
        f"Pi tools mode: {getattr(display_config, 'pi_tools_mode', 'default')}",
        "Use /engine status to check health and availability.",
    ]
    if runner in {"local", "server3"}:
        lines.insert(4, f"Pi local cwd: {getattr(display_config, 'pi_local_cwd', '')}")
    else:
        lines.insert(4, f"Pi host: {getattr(display_config, 'pi_ssh_host', 'server4-beast')}")
    lines.append("Use /pi providers or /pi provider <name> to manage Pi providers.")
    lines.append("Use /model list and /model <name> to view or change the Pi model.")
    return "\n".join(lines)


def check_gemma_health(config) -> Dict[str, object]:
    return engine_health.check_gemma_health(
        config,
        health_timeout_seconds=GEMMA_HEALTH_TIMEOUT_SECONDS,
        curl_timeout_seconds=GEMMA_HEALTH_CURL_TIMEOUT_SECONDS,
    )


def check_venice_health(config) -> Dict[str, object]:
    return engine_health.check_venice_health(
        config,
        health_timeout_seconds=GEMMA_HEALTH_TIMEOUT_SECONDS,
    )


def check_pi_health(config) -> Dict[str, object]:
    return engine_health.check_pi_health(
        config,
        provider=configured_pi_provider(config),
        run_pi_command_fn=_run_pi_command,
        parse_pi_model_rows_fn=_parse_pi_model_rows,
    )


def check_chatgpt_web_health(config) -> Dict[str, object]:
    return engine_health.check_chatgpt_web_health(config)


def build_engine_status_text(state: State, config, scope_key: str) -> str:
    selected = StateRepository(state).get_chat_engine(scope_key)
    effective = normalize_engine_name(selected or configured_default_engine(config))
    display_config = build_engine_runtime_config(state, config, scope_key, effective)
    lines = [
        f"Default engine: {configured_default_engine(config)}",
        f"This chat engine: {effective}",
        f"Selectable engines: {', '.join(selectable_engine_plugins(config))}",
        "Use /engine <name> or tap the buttons below to switch this chat.",
        "Use /engine reset to clear the chat override.",
    ]
    if effective == "codex":
        codex_model = str(getattr(display_config, "codex_model", "") or "").strip()
        lines.append(f"Codex model: {codex_model or '(default)'}")
        lines.append(
            f"Codex effort: {configured_codex_reasoning_effort(display_config) or '(default)'}"
        )
    if effective == "gemma":
        lines.append(f"Gemma provider: {getattr(config, 'gemma_provider', 'ollama_ssh')}")
        lines.append(f"Gemma model: {getattr(config, 'gemma_model', 'gemma4:26b')}")
        lines.append(f"Gemma host: {getattr(config, 'gemma_ssh_host', 'server4-beast')}")
        health = check_gemma_health(config)
        lines.append(f"Gemma health: {'ok' if health['ok'] else 'error'}")
        lines.append(f"Gemma response time: {health['response_ms']}ms")
        lines.append(f"Gemma model available: {'yes' if health['model_available'] else 'no'}")
        lines.append(f"Gemma last check error: {health['error'] or '(none)'}")
    if effective == "venice":
        lines.append(f"Venice base URL: {getattr(display_config, 'venice_base_url', 'https://api.venice.ai/api/v1')}")
        lines.append(f"Venice model: {getattr(display_config, 'venice_model', 'mistral-31-24b')}")
        lines.append(f"Venice temperature: {getattr(display_config, 'venice_temperature', 0.2)}")
        health = check_venice_health(config)
        lines.append(f"Venice health: {'ok' if health['ok'] else 'error'}")
        lines.append(f"Venice response time: {health['response_ms']}ms")
        lines.append(f"Venice model available: {'yes' if health['model_available'] else 'no'}")
        lines.append(f"Venice last check error: {health['error'] or '(none)'}")
    if effective == "pi":
        lines.append(f"Pi provider: {getattr(display_config, 'pi_provider', 'ollama')}")
        lines.append(f"Pi provider source: {_build_pi_provider_source_text(state, scope_key)}")
        lines.append(f"Pi model: {getattr(display_config, 'pi_model', 'qwen3-coder:30b')}")
        lines.append(f"Pi model source: {_build_pi_model_source_text(state, scope_key)}")
        lines.append(f"Pi runner: {getattr(display_config, 'pi_runner', 'ssh')}")
        if str(getattr(display_config, "pi_runner", "ssh") or "ssh").strip().lower() in {"local", "server3"}:
            lines.append(f"Pi local cwd: {getattr(display_config, 'pi_local_cwd', '')}")
            if pi_provider_uses_ollama_tunnel(display_config):
                if bool(getattr(display_config, "pi_ollama_tunnel_enabled", True)):
                    lines.append(
                        f"Pi Ollama tunnel: 127.0.0.1:{getattr(display_config, 'pi_ollama_tunnel_local_port', 11435)}"
                    )
                else:
                    lines.append("Pi Ollama tunnel: disabled")
            else:
                lines.append("Pi Ollama tunnel: not used for this provider")
        else:
            lines.append(f"Pi host: {getattr(display_config, 'pi_ssh_host', 'server4-beast')}")
        lines.append(f"Pi session mode: {getattr(display_config, 'pi_session_mode', 'none')}")
        lines.append(f"Pi tools mode: {getattr(display_config, 'pi_tools_mode', 'default')}")
        health = check_pi_health(display_config)
        lines.append(f"Pi health: {'ok' if health['ok'] else 'error'}")
        lines.append(f"Pi response time: {health['response_ms']}ms")
        lines.append(f"Pi version: {health['version'] or '(unknown)'}")
        lines.append(f"Pi model available: {'yes' if health['model_available'] else 'no'}")
        lines.append(f"Pi last check error: {health['error'] or '(none)'}")
        lines.append("Pi selectability: /pi providers, /pi provider <name>, /model list, /model <name>")
    if effective == "chatgptweb":
        lines.append(f"ChatGPT web URL: {getattr(display_config, 'chatgpt_web_url', 'https://chatgpt.com/')}")
        lines.append(f"ChatGPT web bridge: {getattr(display_config, 'chatgpt_web_bridge_script', '')}")
        lines.append(f"ChatGPT web Browser Brain: {getattr(display_config, 'chatgpt_web_browser_brain_url', 'http://127.0.0.1:47831')}")
        lines.append("ChatGPT web mode: experimental brittle browser bridge")
        health = check_chatgpt_web_health(display_config)
        lines.append(f"ChatGPT web health: {'ok' if health['ok'] else 'error'}")
        lines.append(f"ChatGPT web response time: {health['response_ms']}ms")
        lines.append(f"ChatGPT web Browser Brain running: {'yes' if health['running'] else 'no'}")
        lines.append(f"ChatGPT web tab visible: {'yes' if health['chatgpt_tab'] else 'no'}")
        lines.append(f"ChatGPT web last check error: {health['error'] or '(none)'}")
    return "\n".join(lines)


def _engine_callback_data(engine_name: str, action: str) -> str:
    return f"cfg|engine|{engine_name}|{action}"


def _model_active_engine_name(state: State, config, scope_key: str) -> str:
    selected = StateRepository(state).get_chat_engine(scope_key)
    return normalize_engine_name(selected or configured_default_engine(config))


def _compact_inline_keyboard(
    buttons: List[Tuple[str, str]],
    *,
    columns: int = 2,
) -> Dict[str, object]:
    rows: List[List[Dict[str, str]]] = []
    current_row: List[Dict[str, str]] = []
    for label, callback_data in buttons:
        if len(callback_data.encode("utf-8")) > 64:
            continue
        current_row.append({"text": label, "callback_data": callback_data})
        if len(current_row) >= max(columns, 1):
            rows.append(current_row)
            current_row = []
    if current_row:
        rows.append(current_row)
    return {"inline_keyboard": rows}


def _model_callback_data(engine_name: str, action: str, value: str = "") -> str:
    if action == "reset":
        return f"cfg|model|{engine_name}|reset"
    if action == "menu":
        return f"cfg|model|{engine_name}|menu|{value}" if value else f"cfg|model|{engine_name}|menu"
    if action == "page":
        return f"cfg|model|{engine_name}|page|{value}"
    return f"cfg|model|{engine_name}|set|{value}"


def _provider_callback_data(action: str, value: str = "") -> str:
    if action == "menu":
        return "cfg|provider|pi|menu"
    if action == "set":
        return f"cfg|provider|pi|set|{value}"
    return f"cfg|provider|pi|{action}"


def _effort_callback_data(action: str, value: str = "") -> str:
    if action == "reset":
        return "cfg|effort|codex|reset"
    if action == "menu":
        return "cfg|effort|codex|menu"
    return f"cfg|effort|codex|set|{value}"


def _pi_model_page_for_selection(model_names: List[str], current_model: str, page_size: int) -> int:
    if not model_names or page_size <= 0:
        return 0
    try:
        index = model_names.index(current_model)
    except ValueError:
        return 0
    return max(index // page_size, 0)


def _clamp_page_index(page_index: Optional[int], total_items: int, page_size: int) -> int:
    if total_items <= 0 or page_size <= 0:
        return 0
    last_page = max(((total_items - 1) // page_size), 0)
    if page_index is None:
        return 0
    return min(max(page_index, 0), last_page)


def _build_engine_picker_markup(state: State, config, scope_key: str) -> Optional[Dict[str, object]]:
    current_engine = _model_active_engine_name(state, config, scope_key)
    buttons: List[Tuple[str, str]] = []
    for engine_name in selectable_engine_plugins(config):
        label = f"{engine_name} *" if engine_name == current_engine else engine_name
        buttons.append((label, _engine_callback_data(engine_name, "set")))
    if current_engine == "codex":
        buttons.append(("Model", _model_callback_data(current_engine, "menu")))
    elif current_engine == "pi":
        buttons.append(("Provider", _provider_callback_data("menu")))
        buttons.append(("Model", _model_callback_data(current_engine, "menu")))
    buttons.append(("Reset", _engine_callback_data("default", "reset")))
    markup = _compact_inline_keyboard(buttons, columns=2)
    return markup if markup.get("inline_keyboard") else None


def _set_engine_for_scope(state: State, config, scope_key: str, engine_name: str) -> str:
    normalized_engine = normalize_engine_name(engine_name)
    if normalized_engine == "venice" and not str(getattr(config, "venice_api_key", "") or "").strip():
        return "Venice engine is configured in the bridge, but VENICE_API_KEY is missing."
    allowed = selectable_engine_plugins(config)
    if normalized_engine not in allowed:
        return f"Unknown or unavailable engine: {normalized_engine}\nSelectable engines: {', '.join(allowed)}"
    StateRepository(state).set_chat_engine(scope_key, normalized_engine)
    return f"This chat now uses engine: {normalized_engine}"


def _reset_engine_for_scope(state: State, config, scope_key: str) -> str:
    removed = StateRepository(state).clear_chat_engine(scope_key)
    suffix = "removed" if removed else "already using default"
    return f"Engine override {suffix}. This chat now uses {configured_default_engine(config)}."


def handle_engine_command(
    state: State,
    config,
    client: ChannelAdapter,
    scope_key: str,
    chat_id: int,
    message_thread_id: Optional[int],
    message_id: Optional[int],
    raw_text: str,
) -> bool:
    pieces = raw_text.strip().split(maxsplit=1)
    tail = pieces[1].strip().lower() if len(pieces) > 1 else "status"
    tail = normalize_engine_name(tail)
    reply_markup: Optional[Dict[str, object]] = None
    if tail in {"", "status"}:
        text = build_engine_status_text(state, config, scope_key)
        reply_markup = _build_engine_picker_markup(state, config, scope_key)
    elif tail == "reset":
        text = _reset_engine_for_scope(state, config, scope_key)
        reply_markup = _build_engine_picker_markup(state, config, scope_key)
    else:
        text = _set_engine_for_scope(state, config, scope_key, tail)
        reply_markup = _build_engine_picker_markup(state, config, scope_key)
    client.send_message(
        chat_id,
        text,
        reply_to_message_id=message_id,
        message_thread_id=message_thread_id,
        reply_markup=reply_markup,
    )
    return True


def handle_pi_command(
    state: State,
    config,
    client: ChannelAdapter,
    scope_key: str,
    chat_id: int,
    message_thread_id: Optional[int],
    message_id: Optional[int],
    raw_text: str,
) -> bool:
    pieces = raw_text.strip().split(maxsplit=1)
    raw_tail = pieces[1].strip() if len(pieces) > 1 else "status"
    tail = raw_tail.lower()
    state_repo = StateRepository(state)
    display_config = build_engine_runtime_config(state, config, scope_key, "pi")

    if tail in {"", "status"}:
        client.send_message(
            chat_id,
            build_pi_status_text(state, config, scope_key),
            reply_to_message_id=message_id,
            message_thread_id=message_thread_id,
        )
        return True
    if tail == "providers":
        client.send_message(
            chat_id,
            build_pi_providers_text(state, config, scope_key),
            reply_to_message_id=message_id,
            message_thread_id=message_thread_id,
            reply_markup=_build_provider_picker_markup(state, config, scope_key),
        )
        return True
    if tail == "models":
        try:
            text = build_pi_models_text(state, config, scope_key)
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
            text = "Failed to list Pi models.\n" f"Error: {_brief_health_error(exc)}"
        else:
            text += (
                "\n\nDeprecated alias: `/pi models` still works for compatibility, "
                "but `/model list` is the canonical command."
            )
        client.send_message(
            chat_id,
            text,
            reply_to_message_id=message_id,
            message_thread_id=message_thread_id,
        )
        return True
    if tail == "reset":
        removed_provider = state_repo.clear_chat_pi_provider(scope_key)
        removed_model = state_repo.clear_chat_pi_model(scope_key)
        effective_config = build_engine_runtime_config(state, config, scope_key, "pi")
        source_text = "chat overrides cleared" if (removed_provider or removed_model) else "no chat overrides were set"
        client.send_message(
            chat_id,
            (
                f"{source_text}. "
                f"Pi provider is now {configured_pi_provider(effective_config)} "
                f"({_build_pi_provider_source_text(state, scope_key)}). "
                f"Pi model is now {configured_pi_model(effective_config)} "
                f"({_build_pi_model_source_text(state, scope_key)})."
            ),
            reply_to_message_id=message_id,
            message_thread_id=message_thread_id,
        )
        return True
    if tail.startswith("provider"):
        provider_name = raw_tail[8:].strip() if len(raw_tail) >= 8 else ""
        if not provider_name:
            client.send_message(
                chat_id,
                "Usage: /pi provider <name>\nUse /pi providers to list available Pi providers.",
                reply_to_message_id=message_id,
                message_thread_id=message_thread_id,
            )
            return True
        try:
            text = _set_pi_provider_for_scope(state, config, scope_key, provider_name)
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
            client.send_message(
                chat_id,
                "Failed to validate Pi provider.\n"
                f"Error: {_brief_health_error(exc)}",
                reply_to_message_id=message_id,
                message_thread_id=message_thread_id,
            )
            return True
        client.send_message(
            chat_id,
            text,
            reply_to_message_id=message_id,
            message_thread_id=message_thread_id,
        )
        return True
    if tail.startswith("model"):
        model_name = raw_tail[5:].strip() if len(raw_tail) >= 5 else ""
        if not model_name:
            client.send_message(
                chat_id,
                "Usage: /model <name>\nUse /model list to list available models for the current Pi provider.",
                reply_to_message_id=message_id,
                message_thread_id=message_thread_id,
            )
            return True
        try:
            available_models = _pi_provider_model_names(display_config)
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
            client.send_message(
                chat_id,
                "Failed to validate Pi models.\n"
                f"Error: {_brief_health_error(exc)}",
                reply_to_message_id=message_id,
                message_thread_id=message_thread_id,
            )
            return True
        resolved_model = _resolve_pi_model_candidate(available_models, model_name)
        if resolved_model is None:
            provider = configured_pi_provider(display_config)
            client.send_message(
                chat_id,
                (
                    f"Model not available for Pi provider `{provider}`: `{model_name}`\n"
                    "Use /model list to see the allowed model names."
                ),
                reply_to_message_id=message_id,
                message_thread_id=message_thread_id,
            )
            return True
        state_repo.set_chat_pi_model(scope_key, resolved_model)
        updated_config = build_engine_runtime_config(state, config, scope_key, "pi")
        client.send_message(
            chat_id,
            (
                f"Pi model for this chat is now {configured_pi_model(updated_config)} "
                f"({_build_pi_model_source_text(state, scope_key)}).\n"
                "Deprecated alias: `/pi model` still works for compatibility, "
                "but `/model <name>` is the canonical command."
            ),
            reply_to_message_id=message_id,
            message_thread_id=message_thread_id,
        )
        return True
    client.send_message(
        chat_id,
        "Unknown /pi command. Use /pi, /pi providers, /pi provider <name>, or /pi reset. Use /model list and /model <name> for Pi model selection.",
        reply_to_message_id=message_id,
        message_thread_id=message_thread_id,
    )
    return True


def _build_model_picker_markup(
    state: State,
    config,
    scope_key: str,
    *,
    page_index: Optional[int] = None,
) -> Optional[Dict[str, object]]:
    active_engine = _model_active_engine_name(state, config, scope_key)
    display_config = build_engine_runtime_config(state, config, scope_key, active_engine)
    buttons: List[Tuple[str, str]] = []
    if active_engine == "codex":
        current_model = configured_codex_model(display_config) or "(default)"
        for slug, display_name in _load_codex_model_choices():
            label = slug
            if slug == current_model:
                label = f"{slug} *"
            elif display_name != slug:
                label = display_name
            buttons.append((label, _model_callback_data("codex", "set", slug)))
        buttons.append(("Reset", _model_callback_data("codex", "reset")))
        buttons.append(("Effort", "cfg|effort|codex|menu"))
        buttons.append(("Back to Engine", _engine_callback_data("codex", "menu")))
    elif active_engine == "pi":
        try:
            model_names = _pi_provider_model_names(display_config)
        except (OSError, RuntimeError, subprocess.TimeoutExpired):
            return None
        current_model = configured_pi_model(display_config)
        current_page = _clamp_page_index(
            page_index if page_index is not None else _pi_model_page_for_selection(
                model_names,
                current_model,
                PI_MODEL_PICKER_PAGE_SIZE,
            ),
            len(model_names),
            PI_MODEL_PICKER_PAGE_SIZE,
        )
        start = current_page * PI_MODEL_PICKER_PAGE_SIZE
        end = start + PI_MODEL_PICKER_PAGE_SIZE
        for model_name in model_names[start:end]:
            label = f"{model_name} *" if model_name == current_model else model_name
            buttons.append((label, _model_callback_data("pi", "set", model_name)))
        rows = _compact_inline_keyboard(buttons, columns=2).get("inline_keyboard", [])
        total_pages = max(((len(model_names) - 1) // PI_MODEL_PICKER_PAGE_SIZE) + 1, 1) if model_names else 1
        if total_pages > 1:
            nav_row: List[Dict[str, str]] = []
            if current_page > 0:
                nav_row.append({"text": "Prev", "callback_data": _model_callback_data("pi", "page", str(current_page - 1))})
            nav_row.append(
                {
                    "text": f"{current_page + 1}/{total_pages}",
                    "callback_data": _model_callback_data("pi", "page", str(current_page)),
                }
            )
            if current_page < total_pages - 1:
                nav_row.append({"text": "Next", "callback_data": _model_callback_data("pi", "page", str(current_page + 1))})
            rows.append(nav_row)
        rows.append(
            [
                {"text": "Reset", "callback_data": _model_callback_data("pi", "reset")},
                {"text": "Back to Engine", "callback_data": _engine_callback_data("pi", "menu")},
            ]
        )
        return {"inline_keyboard": rows} if rows else None
    else:
        return None
    markup = _compact_inline_keyboard(buttons, columns=2)
    return markup if markup.get("inline_keyboard") else None


def _build_provider_picker_markup(state: State, config, scope_key: str) -> Optional[Dict[str, object]]:
    display_config = build_engine_runtime_config(state, config, scope_key, "pi")
    current_provider = configured_pi_provider(display_config)
    try:
        provider_names = _pi_available_provider_names(display_config)
    except (OSError, RuntimeError, subprocess.TimeoutExpired):
        provider_names = []
    if not provider_names:
        provider_names = [provider for provider, _description in PI_PROVIDER_CHOICES]
    buttons: List[Tuple[str, str]] = []
    for provider_name in provider_names:
        label = f"{provider_name} *" if provider_name == current_provider else provider_name
        buttons.append((label, _provider_callback_data("set", provider_name)))
    rows = _compact_inline_keyboard(buttons, columns=2).get("inline_keyboard", [])
    rows.append(
        [
            {"text": "Back to Engine", "callback_data": _engine_callback_data("pi", "menu")},
        ]
    )
    return {"inline_keyboard": rows} if rows else None


def _build_effort_picker_markup(state: State, config, scope_key: str) -> Optional[Dict[str, object]]:
    active_engine = _model_active_engine_name(state, config, scope_key)
    if active_engine != "codex":
        return None
    display_config = build_engine_runtime_config(state, config, scope_key, "codex")
    current_model = configured_codex_model(display_config)
    current_effort = configured_codex_reasoning_effort(display_config) or "(default)"
    buttons: List[Tuple[str, str]] = []
    for effort in _supported_codex_efforts_for_model(current_model):
        label = f"{effort} *" if effort == current_effort else effort
        buttons.append((label, _effort_callback_data("set", effort)))
    buttons.append(("Reset", _effort_callback_data("reset")))
    buttons.append(("Back to Models", "cfg|model|codex|menu"))
    markup = _compact_inline_keyboard(buttons, columns=2)
    return markup if markup.get("inline_keyboard") else None


def build_model_status_text(state: State, config, scope_key: str) -> str:
    active_engine = _model_active_engine_name(state, config, scope_key)
    display_config = build_engine_runtime_config(state, config, scope_key, active_engine)
    if active_engine == "codex":
        lines = [
            "Active engine: codex",
            f"Codex model: {configured_codex_model(display_config) or '(default)'}",
            f"Codex model source: {_build_codex_model_source_text(state, scope_key)}",
            f"Codex effort: {configured_codex_reasoning_effort(display_config) or '(default)'}",
            f"Codex effort source: {_build_codex_effort_source_text(state, scope_key)}",
            "Use /model <name> to set this chat's Codex model or tap the buttons below.",
            "Use /model reset to clear the chat override.",
        ]
        return "\n".join(lines)
    if active_engine == "pi":
        lines = [
            "Active engine: pi",
            f"Pi provider: {configured_pi_provider(display_config)}",
            f"Pi model: {configured_pi_model(display_config)}",
            f"Pi model source: {_build_pi_model_source_text(state, scope_key)}",
            "Use /model list to see available Pi models for the current provider.",
            "Use /pi provider <name> to switch Pi provider for this chat.",
        ]
        return "\n".join(lines)
    return (
        f"Active engine: {active_engine}\n"
        "Model switching is currently supported for `codex` and `pi`.\n"
        "Use `/engine codex` or `/engine pi` first."
    )


def build_effort_status_text(state: State, config, scope_key: str) -> str:
    active_engine = _model_active_engine_name(state, config, scope_key)
    if active_engine != "codex":
        return (
            f"Active engine: {active_engine}\n"
            "Reasoning effort switching is currently supported for `codex`.\n"
            "Use `/engine codex` first."
        )
    display_config = build_engine_runtime_config(state, config, scope_key, "codex")
    current_model = configured_codex_model(display_config) or "(default)"
    current_effort = configured_codex_reasoning_effort(display_config) or "(default)"
    return "\n".join(
        [
            "Active engine: codex",
            f"Codex model: {current_model}",
            f"Codex effort: {current_effort}",
            f"Codex effort source: {_build_codex_effort_source_text(state, scope_key)}",
            "Use /effort <low|medium|high|xhigh> or tap the buttons below.",
            "Use /effort reset to clear the chat override.",
        ]
    )


def build_effort_list_text(state: State, config, scope_key: str) -> str:
    active_engine = _model_active_engine_name(state, config, scope_key)
    if active_engine != "codex":
        return (
            f"Active engine: {active_engine}\n"
            "Reasoning effort listing is currently supported for `codex`.\n"
            "Use `/engine codex` first."
        )
    display_config = build_engine_runtime_config(state, config, scope_key, "codex")
    current_model = configured_codex_model(display_config) or "(default)"
    current_effort = configured_codex_reasoning_effort(display_config) or "(default)"
    lines = [
        "Active engine: codex",
        f"Current Codex model: {current_model}",
        f"Current Codex effort: {current_effort}",
        "Available Codex reasoning efforts for this model:",
    ]
    for effort in _supported_codex_efforts_for_model(current_model):
        marker = " (current)" if effort == current_effort else ""
        lines.append(f"- {effort}{marker}")
    return "\n".join(lines)


def _set_codex_model_for_scope(state: State, config, scope_key: str, model_name: str) -> str:
    state_repo = StateRepository(state)
    resolved_model = _resolve_codex_model_candidate(model_name)
    state_repo.set_chat_codex_model(scope_key, resolved_model)
    updated_config = build_engine_runtime_config(state, config, scope_key, "codex")
    current_effort = configured_codex_reasoning_effort(updated_config)
    if current_effort and _resolve_codex_effort_candidate(resolved_model, current_effort) is None:
        supported_efforts = _supported_codex_efforts_for_model(resolved_model)
        if supported_efforts:
            state_repo.set_chat_codex_effort(scope_key, supported_efforts[0])
            updated_config = build_engine_runtime_config(state, config, scope_key, "codex")
    return (
        f"Codex model for this chat is now {configured_codex_model(updated_config) or '(default)'} "
        f"({_build_codex_model_source_text(state, scope_key)})."
    )


def _reset_model_for_scope(state: State, config, scope_key: str, active_engine: str) -> str:
    state_repo = StateRepository(state)
    if active_engine == "codex":
        removed = state_repo.clear_chat_codex_model(scope_key)
        updated_config = build_engine_runtime_config(state, config, scope_key, "codex")
        source = "chat override cleared" if removed else "no chat override was set"
        return (
            f"{source}. Codex model is now {configured_codex_model(updated_config) or '(default)'} "
            f"({_build_codex_model_source_text(state, scope_key)})."
        )
    if active_engine == "pi":
        removed = state_repo.clear_chat_pi_model(scope_key)
        updated_config = build_engine_runtime_config(state, config, scope_key, "pi")
        source = "chat override cleared" if removed else "no chat override was set"
        return (
            f"{source}. Pi model is now {configured_pi_model(updated_config)} "
            f"({_build_pi_model_source_text(state, scope_key)})."
        )
    return build_model_status_text(state, config, scope_key)


def _set_pi_provider_for_scope(state: State, config, scope_key: str, provider_name: str) -> str:
    normalized_provider = normalize_pi_provider_name(provider_name)
    temp_config = copy.copy(config)
    temp_config.pi_provider = normalized_provider
    available_models = _pi_provider_model_names(temp_config)
    if not available_models:
        return (
            f"Provider `{normalized_provider}` did not report any models.\n"
            "Pi provider was not changed."
        )
    state_repo = StateRepository(state)
    current_model = state_repo.get_chat_pi_model(scope_key)
    resolved_model = _resolve_pi_model_candidate(available_models, current_model or "")
    if resolved_model is None:
        resolved_model = available_models[0]
    state_repo.set_chat_pi_provider(scope_key, normalized_provider)
    state_repo.set_chat_pi_model(scope_key, resolved_model)
    return (
        f"Pi provider for this chat is now {normalized_provider}. "
        f"Pi model is now {resolved_model}."
    )


def _set_pi_model_for_scope(state: State, config, scope_key: str, model_name: str) -> str:
    display_config = build_engine_runtime_config(state, config, scope_key, "pi")
    available_models = _pi_provider_model_names(display_config)
    resolved_model = _resolve_pi_model_candidate(available_models, model_name)
    if resolved_model is None:
        provider = configured_pi_provider(display_config)
        return (
            f"Model not available for Pi provider `{provider}`: `{model_name}`\n"
            "Use /model list to see the allowed model names."
        )
    StateRepository(state).set_chat_pi_model(scope_key, resolved_model)
    updated_config = build_engine_runtime_config(state, config, scope_key, "pi")
    return (
        f"Pi model for this chat is now {configured_pi_model(updated_config)} "
        f"({_build_pi_model_source_text(state, scope_key)})."
    )


def _set_codex_effort_for_scope(state: State, config, scope_key: str, effort_name: str) -> str:
    display_config = build_engine_runtime_config(state, config, scope_key, "codex")
    current_model = configured_codex_model(display_config)
    resolved_effort = _resolve_codex_effort_candidate(current_model, effort_name)
    if resolved_effort is None:
        return (
            f"Reasoning effort not supported for Codex model `{current_model or '(default)'}`: "
            f"`{effort_name}`\nUse /effort list to see the allowed effort names."
        )
    StateRepository(state).set_chat_codex_effort(scope_key, resolved_effort)
    updated_config = build_engine_runtime_config(state, config, scope_key, "codex")
    return (
        f"Codex reasoning effort for this chat is now "
        f"{configured_codex_reasoning_effort(updated_config) or '(default)'} "
        f"({_build_codex_effort_source_text(state, scope_key)})."
    )


def _reset_codex_effort_for_scope(state: State, config, scope_key: str) -> str:
    removed = StateRepository(state).clear_chat_codex_effort(scope_key)
    updated_config = build_engine_runtime_config(state, config, scope_key, "codex")
    source = "chat override cleared" if removed else "no chat override was set"
    return (
        f"{source}. Codex reasoning effort is now "
        f"{configured_codex_reasoning_effort(updated_config) or '(default)'} "
        f"({_build_codex_effort_source_text(state, scope_key)})."
    )


def _parse_page_index(raw_value: str) -> Optional[int]:
    value = str(raw_value or "").strip()
    if not value:
        return None
    try:
        page_index = int(value)
    except ValueError:
        return None
    return page_index if page_index >= 0 else None


def build_model_list_text(state: State, config, scope_key: str) -> str:
    active_engine = _model_active_engine_name(state, config, scope_key)
    display_config = build_engine_runtime_config(state, config, scope_key, active_engine)
    if active_engine == "codex":
        current_model = configured_codex_model(display_config) or "(default)"
        default_model = configured_codex_model(config) or "(default)"
        lines = [
            "Active engine: codex",
            f"Current Codex model: {current_model}",
            f"Bridge default Codex model: {default_model}",
        ]
        choices = _load_codex_model_choices()
        if choices:
            lines.append("Available Codex models:")
            for slug, display_name in choices:
                marker = " (current)" if slug == current_model else ""
                if display_name != slug:
                    lines.append(f"- {slug}{marker} - {display_name}")
                else:
                    lines.append(f"- {slug}{marker}")
            lines.append("Use /model <name> with either the slug or display name.")
        else:
            lines.append("No local Codex model cache was found for a fuller list.")
            lines.append("Set any Codex model name with /model <name>.")
        return "\n".join(lines)
    if active_engine == "pi":
        return build_pi_models_text(state, config, scope_key)
    return (
        f"Active engine: {active_engine}\n"
        "Model listing is currently supported for `codex` and `pi`.\n"
        "Use `/engine codex` or `/engine pi` first."
    )


def handle_model_command(
    state: State,
    config,
    client: ChannelAdapter,
    scope_key: str,
    chat_id: int,
    message_thread_id: Optional[int],
    message_id: Optional[int],
    raw_text: str,
) -> bool:
    pieces = raw_text.strip().split(maxsplit=1)
    raw_tail = pieces[1].strip() if len(pieces) > 1 else "status"
    tail = raw_tail.lower()
    active_engine = _model_active_engine_name(state, config, scope_key)
    reply_markup: Optional[Dict[str, object]] = None

    if tail in {"", "status"}:
        text = build_model_status_text(state, config, scope_key)
        reply_markup = _build_model_picker_markup(state, config, scope_key)
    elif tail == "list":
        try:
            text = build_model_list_text(state, config, scope_key)
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
            text = "Failed to list models.\n" f"Error: {_brief_health_error(exc)}"
    elif tail == "reset":
        text = _reset_model_for_scope(state, config, scope_key, active_engine)
        reply_markup = _build_model_picker_markup(state, config, scope_key)
    else:
        if active_engine == "codex":
            text = _set_codex_model_for_scope(state, config, scope_key, raw_tail)
            reply_markup = _build_model_picker_markup(state, config, scope_key)
        elif active_engine == "pi":
            try:
                text = _set_pi_model_for_scope(state, config, scope_key, raw_tail)
            except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
                text = "Failed to validate Pi models.\n" f"Error: {_brief_health_error(exc)}"
            reply_markup = _build_model_picker_markup(state, config, scope_key)
        else:
            text = build_model_status_text(state, config, scope_key)

    client.send_message(
        chat_id,
        text,
        reply_to_message_id=message_id,
        message_thread_id=message_thread_id,
        reply_markup=reply_markup,
    )
    return True


def handle_effort_command(
    state: State,
    config,
    client: ChannelAdapter,
    scope_key: str,
    chat_id: int,
    message_thread_id: Optional[int],
    message_id: Optional[int],
    raw_text: str,
) -> bool:
    pieces = raw_text.strip().split(maxsplit=1)
    raw_tail = pieces[1].strip() if len(pieces) > 1 else "status"
    tail = raw_tail.lower()
    active_engine = _model_active_engine_name(state, config, scope_key)
    reply_markup: Optional[Dict[str, object]] = None

    if tail in {"", "status"}:
        text = build_effort_status_text(state, config, scope_key)
        reply_markup = _build_effort_picker_markup(state, config, scope_key)
    elif tail == "list":
        text = build_effort_list_text(state, config, scope_key)
    elif tail == "reset":
        text = _reset_codex_effort_for_scope(state, config, scope_key)
        reply_markup = _build_effort_picker_markup(state, config, scope_key)
    elif active_engine != "codex":
        text = build_effort_status_text(state, config, scope_key)
    else:
        text = _set_codex_effort_for_scope(state, config, scope_key, raw_tail)
        reply_markup = _build_effort_picker_markup(state, config, scope_key)

    client.send_message(
        chat_id,
        text,
        reply_to_message_id=message_id,
        message_thread_id=message_thread_id,
        reply_markup=reply_markup,
    )
    return True


def resolve_engine_for_scope(
    state: State,
    config,
    scope_key: str,
    default_engine: Optional[EngineAdapter],
) -> EngineAdapter:
    selected = StateRepository(state).get_chat_engine(scope_key)
    if not selected:
        if default_engine is not None:
            return default_engine
        return build_default_plugin_registry().build_engine(configured_default_engine(config))
    engine_name = normalize_engine_name(selected)
    if default_engine is not None and getattr(default_engine, "engine_name", "") == engine_name:
        return default_engine
    registry = build_default_plugin_registry()
    return registry.build_engine(engine_name)
