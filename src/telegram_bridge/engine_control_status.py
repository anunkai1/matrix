import copy
import subprocess
from urllib import error as urllib_error
from urllib import request as urllib_request
from typing import Dict, List, Optional, Tuple

from telegram_bridge import engine_control_views
from telegram_bridge import engine_health
from telegram_bridge import engine_pi_catalog
from telegram_bridge.engine_catalog import (
    configured_codex_reasoning_effort,
    configured_default_engine,
    configured_gemma_model,
    configured_pi_model,
    configured_pi_provider,
    normalize_engine_name,
    pi_provider_uses_ollama_tunnel,
    selectable_engine_plugins,
)
from telegram_bridge.state_store import (
    State,
    get_chat_codex_effort,
    get_chat_codex_model,
    get_chat_engine,
    get_chat_gemma_model,
    get_chat_pi_model,
    get_chat_pi_provider,
)

GEMMA_HEALTH_TIMEOUT_SECONDS = 6
GEMMA_HEALTH_CURL_TIMEOUT_SECONDS = 5

brief_health_error = engine_health._brief_health_error


def build_engine_runtime_config(state, config, scope_key: str, engine_name: str):
    runtime_config = copy.deepcopy(config)
    normalized_engine = normalize_engine_name(engine_name)
    if normalized_engine == "gemma":
        override_model = get_chat_gemma_model(state, scope_key)
        if not override_model:
            return config
        runtime_config.gemma_model = override_model
        return runtime_config
    if normalized_engine == "codex":
        override_model = get_chat_codex_model(state, scope_key)
        override_effort = get_chat_codex_effort(state, scope_key)
        if not override_model and not override_effort:
            return config
        if override_model:
            runtime_config.codex_model = override_model
        if override_effort:
            runtime_config.codex_reasoning_effort = override_effort
        return runtime_config
    if normalized_engine == "venice":
        override_provider = get_chat_pi_provider(state, scope_key)
        override_model = get_chat_pi_model(state, scope_key)
        if str(override_provider or "").strip().lower() != "venice" or not override_model:
            return config
        runtime_config.venice_model = override_model
        return runtime_config
    if normalized_engine != "pi":
        return config
    override_provider = get_chat_pi_provider(state, scope_key)
    override_model = get_chat_pi_model(state, scope_key)
    if not override_provider and not override_model:
        return config
    if override_provider:
        runtime_config.pi_provider = override_provider
    if override_model:
        runtime_config.pi_model = override_model
    return runtime_config


def build_codex_model_source_text(state: State, scope_key: str) -> str:
    if get_chat_codex_model(state, scope_key):
        return "chat override"
    return "global default"


def build_gemma_model_source_text(state: State, scope_key: str) -> str:
    if get_chat_gemma_model(state, scope_key):
        return "chat override"
    return "global default"


def build_codex_effort_source_text(state: State, scope_key: str) -> str:
    if get_chat_codex_effort(state, scope_key):
        return "chat override"
    return "global default"


def build_pi_provider_source_text(state: State, scope_key: str) -> str:
    if get_chat_pi_provider(state, scope_key):
        return "chat override"
    return "global default"


def build_pi_model_source_text(state: State, scope_key: str) -> str:
    if get_chat_pi_model(state, scope_key):
        return "chat override"
    return "global default"


def pi_provider_choice_lines(current_provider: str) -> List[str]:
    return engine_pi_catalog.pi_provider_choice_lines(current_provider)


def pi_provider_description(provider_name: str) -> str:
    return engine_pi_catalog.pi_provider_description(provider_name)


def gemma_model_names(config) -> List[str]:
    provider = str(getattr(config, "gemma_provider", "ollama_ssh") or "ollama_ssh").strip().lower()
    if provider == "ollama_http":
        base_url = str(getattr(config, "gemma_base_url", "http://127.0.0.1:11434") or "").rstrip("/")
        if not base_url:
            raise RuntimeError("GEMMA_BASE_URL is empty")
        try:
            with urllib_request.urlopen(
                f"{base_url}/api/tags",
                timeout=GEMMA_HEALTH_TIMEOUT_SECONDS,
            ) as response:
                payload = response.read().decode("utf-8", errors="replace")
        except urllib_error.URLError as exc:
            raise RuntimeError(str(exc).strip() or "Ollama HTTP transport failed") from exc
        return list(dict.fromkeys(engine_pi_catalog.parse_ollama_tags(payload)))
    if provider == "ollama_ssh":
        host = str(getattr(config, "gemma_ssh_host", "server4-beast") or "").strip()
        if not host:
            raise RuntimeError("GEMMA_SSH_HOST is empty")
        completed = subprocess.run(
            [
                "ssh",
                "-o",
                "BatchMode=yes",
                "-o",
                f"ConnectTimeout={GEMMA_HEALTH_TIMEOUT_SECONDS}",
                host,
                (
                    "curl -sS "
                    f"--max-time {GEMMA_HEALTH_CURL_TIMEOUT_SECONDS} "
                    "http://127.0.0.1:11434/api/tags"
                ),
            ],
            capture_output=True,
            text=True,
            timeout=GEMMA_HEALTH_TIMEOUT_SECONDS + 4,
        )
        if completed.returncode != 0:
            raise RuntimeError(
                completed.stderr.strip()
                or completed.stdout.strip()
                or f"ssh exited {completed.returncode}"
            )
        return list(dict.fromkeys(engine_pi_catalog.parse_ollama_tags(completed.stdout)))
    raise RuntimeError(f"unsupported provider {provider!r}")


def resolve_gemma_model_candidate(available_models: List[str], requested_model: str) -> Optional[str]:
    requested = str(requested_model or "").strip()
    if not requested:
        return None
    if requested.startswith("idx:"):
        try:
            index = int(requested[4:])
        except ValueError:
            return None
        if 0 <= index < len(available_models):
            return available_models[index]
        return None
    for available in available_models:
        if available == requested:
            return available
    folded = requested.casefold()
    matches = [available for available in available_models if available.casefold() == folded]
    if len(matches) == 1:
        return matches[0]
    return None


def pi_available_provider_names(config) -> List[str]:
    return engine_pi_catalog.pi_available_provider_names(config)


def run_pi_command(config, command: str) -> subprocess.CompletedProcess[str]:
    return engine_pi_catalog.run_pi_command(config, command)


def parse_pi_model_rows(payload: str) -> List[Tuple[str, str]]:
    return engine_pi_catalog.parse_pi_model_rows(payload)


def pi_model_rows(config) -> List[Tuple[str, str]]:
    return engine_pi_catalog.pi_model_rows(config)


def pi_provider_model_names(config) -> List[str]:
    return engine_pi_catalog.pi_provider_model_names(config)


def resolve_pi_model_candidate(available_models: List[str], requested_model: str) -> Optional[str]:
    return engine_pi_catalog.resolve_pi_model_candidate(available_models, requested_model)


def build_pi_providers_text(state: State, config, scope_key: str) -> str:
    try:
        return engine_control_views.build_pi_providers_text(
            state,
            config,
            scope_key,
            build_engine_runtime_config=build_engine_runtime_config,
            configured_pi_provider=configured_pi_provider,
            build_pi_provider_source_text=build_pi_provider_source_text,
            pi_available_provider_names=pi_available_provider_names,
            pi_provider_description=pi_provider_description,
            pi_provider_choice_lines=pi_provider_choice_lines,
        )
    except (OSError, RuntimeError, subprocess.TimeoutExpired):
        display_config = build_engine_runtime_config(state, config, scope_key, "pi")
        provider = configured_pi_provider(display_config)
        lines = [
            f"Pi provider: {provider}",
            f"Pi provider source: {build_pi_provider_source_text(state, scope_key)}",
            "Available Pi providers:",
        ]
        lines.extend(pi_provider_choice_lines(provider))
        lines.append("Use /pi provider <name> to switch this chat.")
        return "\n".join(lines)


def build_pi_models_text(state: State, config, scope_key: str) -> str:
    return engine_control_views.build_pi_models_text(
        state,
        config,
        scope_key,
        build_engine_runtime_config=build_engine_runtime_config,
        configured_pi_provider=configured_pi_provider,
        configured_pi_model=configured_pi_model,
        build_pi_provider_source_text=build_pi_provider_source_text,
        build_pi_model_source_text=build_pi_model_source_text,
        pi_provider_model_names=pi_provider_model_names,
    )


def build_pi_status_text(state: State, config, scope_key: str) -> str:
    return engine_control_views.build_pi_status_text(
        state,
        config,
        scope_key,
        build_engine_runtime_config=build_engine_runtime_config,
        configured_pi_provider=configured_pi_provider,
        configured_pi_model=configured_pi_model,
        build_pi_provider_source_text=build_pi_provider_source_text,
        build_pi_model_source_text=build_pi_model_source_text,
    )


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
    provider = configured_pi_provider(config)
    health = engine_health.check_pi_health(
        config,
        provider=provider,
        run_pi_command_fn=run_pi_command,
        parse_pi_model_rows_fn=parse_pi_model_rows,
    )
    if provider != "ollama":
        return health
    if health.get("model_available"):
        return health
    try:
        available_models = pi_provider_model_names(config)
    except (OSError, RuntimeError, subprocess.TimeoutExpired):
        return health
    model = configured_pi_model(config)
    if model in available_models:
        health["model_available"] = True
        if health.get("ok") is False and not health.get("error"):
            health["ok"] = True
    return health


def build_engine_status_text(state: State, config, scope_key: str) -> str:
    return engine_control_views.build_engine_status_text(
        state,
        config,
        scope_key,
        get_chat_engine=get_chat_engine,
        normalize_engine_name=normalize_engine_name,
        configured_default_engine=configured_default_engine,
        selectable_engine_plugins=selectable_engine_plugins,
        build_engine_runtime_config=build_engine_runtime_config,
        configured_codex_reasoning_effort=configured_codex_reasoning_effort,
        build_pi_provider_source_text=build_pi_provider_source_text,
        build_pi_model_source_text=build_pi_model_source_text,
        pi_provider_uses_ollama_tunnel=pi_provider_uses_ollama_tunnel,
        check_gemma_health=check_gemma_health,
        check_venice_health=check_venice_health,
        check_pi_health=check_pi_health,
    )


def model_active_engine_name(state: State, config, scope_key: str) -> str:
    selected = get_chat_engine(state, scope_key)
    return normalize_engine_name(selected or configured_default_engine(config))
