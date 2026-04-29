"""Runtime configuration loading for the shared bridge core."""

from __future__ import annotations

import os
import shlex
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

try:
    from .runtime_paths import (
        build_shared_core_root,
        build_runtime_root,
        dedupe_paths,
        runtime_path,
        shared_core_path,
    )
    from .transport import TELEGRAM_LIMIT
except ImportError:
    from runtime_paths import (
        build_shared_core_root,
        build_runtime_root,
        dedupe_paths,
        runtime_path,
        shared_core_path,
    )
    from transport import TELEGRAM_LIMIT


@dataclass
class Config:
    token: str
    allowed_chat_ids: Set[int]
    api_base: str
    poll_timeout_seconds: int
    retry_sleep_seconds: float
    exec_timeout_seconds: int
    max_input_chars: int
    max_output_chars: int
    max_image_bytes: int
    max_voice_bytes: int
    max_document_bytes: int
    attachment_retention_seconds: int
    attachment_max_total_bytes: int
    rate_limit_per_minute: int
    executor_cmd: List[str]
    voice_transcribe_cmd: List[str]
    voice_transcribe_timeout_seconds: int
    voice_alias_replacements: List[Tuple[str, str]]
    voice_alias_learning_enabled: bool
    voice_alias_learning_path: str
    voice_alias_learning_min_examples: int
    voice_alias_learning_confirmation_window_seconds: int
    voice_low_confidence_confirmation_enabled: bool
    voice_low_confidence_threshold: float
    voice_low_confidence_message: str
    state_dir: str
    persistent_workers_enabled: bool
    persistent_workers_max: int
    persistent_workers_idle_timeout_seconds: int
    persistent_workers_policy_files: List[str]
    canonical_sessions_enabled: bool
    canonical_legacy_mirror_enabled: bool
    canonical_sqlite_enabled: bool
    canonical_sqlite_path: str
    canonical_json_mirror_enabled: bool
    memory_sqlite_path: str
    memory_max_messages_per_key: int
    memory_max_summaries_per_key: int
    memory_prune_interval_seconds: int
    required_prefixes: List[str]
    required_prefix_ignore_case: bool
    require_prefix_in_private: bool
    allow_private_chats_unlisted: bool
    allow_group_chats_unlisted: bool
    assistant_name: str
    shared_memory_key: str
    channel_plugin: str
    engine_plugin: str
    selectable_engine_plugins: List[str]
    codex_model: str
    codex_reasoning_effort: str
    gemma_provider: str
    gemma_model: str
    gemma_base_url: str
    gemma_ssh_host: str
    gemma_request_timeout_seconds: int
    venice_api_key: str
    venice_base_url: str
    venice_model: str
    venice_temperature: float
    venice_request_timeout_seconds: int
    chatgpt_web_bridge_script: str
    chatgpt_web_python_bin: str
    chatgpt_web_browser_brain_url: str
    chatgpt_web_browser_brain_service: str
    chatgpt_web_url: str
    chatgpt_web_start_service: bool
    chatgpt_web_request_timeout_seconds: int
    chatgpt_web_ready_timeout_seconds: int
    chatgpt_web_response_timeout_seconds: int
    chatgpt_web_poll_seconds: float
    pi_provider: str
    pi_model: str
    pi_runner: str
    pi_bin: str
    pi_ssh_host: str
    pi_local_cwd: str
    pi_remote_cwd: str
    pi_session_mode: str
    pi_session_dir: str
    pi_session_max_bytes: int
    pi_session_max_age_seconds: int
    pi_session_archive_retention_seconds: int
    pi_session_archive_dir: str
    pi_tools_mode: str
    pi_tools_allowlist: str
    pi_extra_args: str
    pi_ollama_tunnel_enabled: bool
    pi_ollama_tunnel_local_port: int
    pi_ollama_tunnel_remote_host: str
    pi_ollama_tunnel_remote_port: int
    pi_request_timeout_seconds: int
    whatsapp_plugin_enabled: bool
    whatsapp_bridge_api_base: str
    whatsapp_bridge_auth_token: str
    whatsapp_poll_timeout_seconds: int
    signal_plugin_enabled: bool
    signal_bridge_api_base: str
    signal_bridge_auth_token: str
    signal_poll_timeout_seconds: int
    keyword_routing_enabled: bool
    diary_mode_enabled: bool = False
    diary_capture_quiet_window_seconds: int = 75
    diary_timezone: str = "Australia/Brisbane"
    diary_local_root: str = ""
    diary_nextcloud_enabled: bool = False
    diary_nextcloud_base_url: str = ""
    diary_nextcloud_username: str = ""
    diary_nextcloud_app_password: str = ""
    diary_nextcloud_remote_root: str = "/Diary"
    affective_runtime_enabled: bool = False
    affective_runtime_db_path: str = ""
    affective_runtime_ping_target: str = "1.1.1.1"
    policy_reset_memory_on_change: bool = False
    progress_label: str = ""
    progress_elapsed_prefix: str = "Already"
    progress_elapsed_suffix: str = "s"
    busy_message: str = "Another request is still running. Please wait."
    denied_message: str = "Access denied for this chat."
    timeout_message: str = "Request timed out. Please try a shorter prompt."
    generic_error_message: str = "Execution failed. Please try again later."
    image_download_error_message: str = "Image download failed. Please send another image."
    voice_download_error_message: str = "Voice download failed. Please send another voice message."
    document_download_error_message: str = "File download failed. Please send another file."
    voice_not_configured_message: str = (
        "Voice transcription is not configured. Please ask admin to set TELEGRAM_VOICE_TRANSCRIBE_CMD."
    )
    voice_transcribe_error_message: str = "Voice transcription failed. Please send clearer audio."
    voice_transcribe_empty_message: str = (
        "Voice transcription was empty. Please send clearer audio."
    )
    empty_output_message: str = "(No output from assistant)"


def parse_int_env(name: str, default: int, minimum: int = 1) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if parsed < minimum:
        raise ValueError(f"{name} must be >= {minimum}")
    return parsed

def parse_bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in ("1", "true", "yes", "on"):
        return True
    if normalized in ("0", "false", "no", "off"):
        return False
    raise ValueError(f"{name} must be a boolean value")


def parse_float_env(
    name: str,
    default: float,
    *,
    minimum: Optional[float] = None,
    maximum: Optional[float] = None,
) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        parsed = float(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a float") from exc
    if minimum is not None and parsed < minimum:
        raise ValueError(f"{name} must be >= {minimum}")
    if maximum is not None and parsed > maximum:
        raise ValueError(f"{name} must be <= {maximum}")
    return parsed


def parse_allowed_chat_ids(raw: str) -> Set[int]:
    values = [item.strip() for item in raw.split(",") if item.strip()]
    if not values:
        raise ValueError("TELEGRAM_ALLOWED_CHAT_IDS is empty")
    parsed: Set[int] = set()
    for value in values:
        try:
            parsed.add(int(value))
        except ValueError as exc:
            raise ValueError(
                f"Invalid TELEGRAM_ALLOWED_CHAT_IDS value: {value!r}"
            ) from exc
    return parsed


def parse_prefixes_env(name: str) -> List[str]:
    raw = os.getenv(name, "").strip()
    if not raw:
        return []
    values = [item.strip() for item in raw.split(",") if item.strip()]
    seen: Set[str] = set()
    parsed: List[str] = []
    for value in values:
        key = value.casefold()
        if key in seen:
            continue
        seen.add(key)
        parsed.append(value)
    return parsed


def parse_string_list_env(name: str) -> List[str]:
    raw = os.getenv(name, "").strip()
    if not raw:
        return []
    values = [item.strip() for item in raw.split(",") if item.strip()]
    seen: Set[str] = set()
    parsed: List[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        parsed.append(value)
    return parsed


def parse_plugin_name_env(name: str, default: str) -> str:
    raw = os.getenv(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if not value:
        return default
    return value


def parse_plugin_list_env(name: str, default: List[str]) -> List[str]:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return list(default)
    values = [item.strip().lower() for item in raw.split(",") if item.strip()]
    seen: Set[str] = set()
    parsed: List[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        parsed.append(value)
    return parsed or list(default)


def default_voice_alias_replacements() -> List[Tuple[str, str]]:
    return [
        ("master broom", "master bedroom"),
        ("master room", "master bedroom"),
        ("air con", "aircon"),
        ("air conditioner", "aircon"),
        ("clode code", "claude code"),
        ("hall way", "hallway"),
    ]


def parse_voice_alias_replacements_env(name: str) -> List[Tuple[str, str]]:
    raw = os.getenv(name, "").strip()
    if not raw:
        return []
    parsed: List[Tuple[str, str]] = []
    entries = [item.strip() for item in raw.split(";") if item.strip()]
    for entry in entries:
        if "=>" not in entry:
            raise ValueError(
                f"{name} entry must use 'source=>target' format: {entry!r}"
            )
        source, target = entry.split("=>", 1)
        source = source.strip()
        target = target.strip()
        if not source or not target:
            raise ValueError(
                f"{name} entry must include non-empty source and target: {entry!r}"
            )
        parsed.append((source, target))
    return parsed


def build_voice_alias_replacements() -> List[Tuple[str, str]]:
    merged: Dict[str, Tuple[str, str]] = {}
    for source, target in default_voice_alias_replacements():
        merged[source.casefold()] = (source, target)
    for source, target in parse_voice_alias_replacements_env(
        "TELEGRAM_VOICE_ALIAS_REPLACEMENTS"
    ):
        merged[source.casefold()] = (source, target)
    return list(merged.values())


def build_repo_root() -> str:
    return build_shared_core_root()


def build_policy_watch_files() -> List[str]:
    raw_override = os.getenv("TELEGRAM_POLICY_WATCH_FILES")
    if raw_override is not None:
        return [item.strip() for item in raw_override.split(",") if item.strip()]

    mode = os.getenv("TELEGRAM_POLICY_WATCH_MODE", "").strip().lower()
    if mode in ("none", "off", "disabled", "empty"):
        return []

    return dedupe_paths(
        [
            runtime_path("AGENTS.md"),
            shared_core_path("ARCHITECT_INSTRUCTION.md"),
            shared_core_path("SERVER3_ARCHIVE.md"),
        ]
    )


def build_default_executor() -> str:
    return shared_core_path("src", "telegram_bridge", "executor.sh")


def parse_executor_cmd() -> List[str]:
    raw = os.getenv("TELEGRAM_EXECUTOR_CMD", "").strip()
    if raw:
        cmd = shlex.split(raw)
        if not cmd:
            raise ValueError("TELEGRAM_EXECUTOR_CMD cannot be blank")
        return cmd
    return [build_default_executor()]


def parse_optional_cmd_env(name: str) -> List[str]:
    raw = os.getenv(name, "").strip()
    if not raw:
        return []
    cmd = shlex.split(raw)
    if not cmd:
        raise ValueError(f"{name} cannot be blank")
    return cmd


def load_codex_model() -> str:
    # Resolution order:
    # 1) explicit CODEX_MODEL
    # 2) model from CODEX_CONFIG_PATH or ~/.codex/config.toml
    env_model = os.getenv("CODEX_MODEL", "").strip()
    if env_model:
        return env_model

    config_path = Path(os.getenv("CODEX_CONFIG_PATH", Path.home() / ".codex" / "config.toml")).expanduser()
    try:
        with config_path.open("rb") as fh:
            payload = tomllib.load(fh)
    except (FileNotFoundError, IsADirectoryError, PermissionError, tomllib.TOMLDecodeError):
        return ""

    model = payload.get("model", "")
    return str(model).strip() if isinstance(model, str) else ""


def load_codex_reasoning_effort() -> str:
    env_effort = os.getenv("CODEX_REASONING_EFFORT", "").strip().lower()
    if env_effort:
        return env_effort

    config_path = Path(os.getenv("CODEX_CONFIG_PATH", Path.home() / ".codex" / "config.toml")).expanduser()
    try:
        with config_path.open("rb") as fh:
            payload = tomllib.load(fh)
    except (FileNotFoundError, IsADirectoryError, PermissionError, tomllib.TOMLDecodeError):
        return ""

    effort = payload.get("model_reasoning_effort", "")
    return str(effort).strip().lower() if isinstance(effort, str) else ""


def load_config() -> Config:
    channel_plugin = parse_plugin_name_env("TELEGRAM_CHANNEL_PLUGIN", "telegram")
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if channel_plugin == "telegram" and not token:
        raise ValueError("TELEGRAM_BOT_TOKEN is required")

    raw_chat_ids = os.getenv("TELEGRAM_ALLOWED_CHAT_IDS", "").strip()
    if channel_plugin == "telegram" and not raw_chat_ids:
        raise ValueError("TELEGRAM_ALLOWED_CHAT_IDS is required")
    state_dir = os.getenv(
        "TELEGRAM_BRIDGE_STATE_DIR",
        "/home/architect/.local/state/telegram-architect-bridge",
    ).strip()
    if not state_dir:
        raise ValueError("TELEGRAM_BRIDGE_STATE_DIR cannot be empty")
    canonical_sqlite_path = os.getenv("TELEGRAM_CANONICAL_SQLITE_PATH", "").strip()
    if not canonical_sqlite_path:
        canonical_sqlite_path = os.path.join(state_dir, "chat_sessions.sqlite3")
    memory_sqlite_path = os.getenv("TELEGRAM_MEMORY_SQLITE_PATH", "").strip()
    if not memory_sqlite_path:
        memory_sqlite_path = os.path.join(state_dir, "memory.sqlite3")
    affective_runtime_db_path = os.getenv(
        "TELEGRAM_AFFECTIVE_RUNTIME_DB_PATH",
        os.path.join(state_dir, "affective_state.sqlite3"),
    ).strip() or os.path.join(state_dir, "affective_state.sqlite3")
    affective_runtime_ping_target = os.getenv(
        "TELEGRAM_AFFECTIVE_RUNTIME_PING_TARGET",
        "1.1.1.1",
    )

    allowed_chat_ids = parse_allowed_chat_ids(raw_chat_ids) if raw_chat_ids else set()
    assistant_name = os.getenv("TELEGRAM_ASSISTANT_NAME", "Architect").strip() or "Architect"
    shared_memory_key = os.getenv("TELEGRAM_SHARED_MEMORY_KEY", "").strip()
    progress_label = os.getenv("TELEGRAM_PROGRESS_LABEL", "").strip()
    raw_progress_elapsed_prefix = os.getenv("TELEGRAM_PROGRESS_ELAPSED_PREFIX")
    if raw_progress_elapsed_prefix is None:
        progress_elapsed_prefix = "Already"
    else:
        progress_elapsed_prefix = raw_progress_elapsed_prefix.strip()
    raw_progress_elapsed_suffix = os.getenv("TELEGRAM_PROGRESS_ELAPSED_SUFFIX")
    if raw_progress_elapsed_suffix is None:
        progress_elapsed_suffix = "s"
    else:
        progress_elapsed_suffix = raw_progress_elapsed_suffix
    busy_message = (
        os.getenv(
            "TELEGRAM_BUSY_MESSAGE",
            "Another request is still running. Please wait.",
        ).strip()
        or "Another request is still running. Please wait."
    )
    exec_timeout_seconds = parse_int_env("TELEGRAM_EXEC_TIMEOUT_SECONDS", 36000)
    return Config(
        token=token,
        allowed_chat_ids=allowed_chat_ids,
        api_base=os.getenv("TELEGRAM_API_BASE", "https://api.telegram.org").rstrip("/"),
        poll_timeout_seconds=parse_int_env("TELEGRAM_POLL_TIMEOUT_SECONDS", 30),
        retry_sleep_seconds=float(os.getenv("TELEGRAM_RETRY_SLEEP_SECONDS", "3")),
        exec_timeout_seconds=exec_timeout_seconds,
        max_input_chars=parse_int_env("TELEGRAM_MAX_INPUT_CHARS", TELEGRAM_LIMIT),
        max_output_chars=parse_int_env("TELEGRAM_MAX_OUTPUT_CHARS", 20000),
        max_image_bytes=parse_int_env("TELEGRAM_MAX_IMAGE_BYTES", 10 * 1024 * 1024, minimum=1024),
        max_voice_bytes=parse_int_env("TELEGRAM_MAX_VOICE_BYTES", 20 * 1024 * 1024, minimum=1024),
        max_document_bytes=parse_int_env("TELEGRAM_MAX_DOCUMENT_BYTES", 50 * 1024 * 1024, minimum=1024),
        attachment_retention_seconds=parse_int_env(
            "TELEGRAM_ATTACHMENT_RETENTION_SECONDS",
            14 * 24 * 60 * 60,
            minimum=0,
        ),
        attachment_max_total_bytes=parse_int_env(
            "TELEGRAM_ATTACHMENT_MAX_TOTAL_BYTES",
            10 * 1024 * 1024 * 1024,
            minimum=1024 * 1024,
        ),
        rate_limit_per_minute=parse_int_env("TELEGRAM_RATE_LIMIT_PER_MINUTE", 12),
        executor_cmd=parse_executor_cmd(),
        voice_transcribe_cmd=parse_optional_cmd_env("TELEGRAM_VOICE_TRANSCRIBE_CMD"),
        voice_transcribe_timeout_seconds=parse_int_env(
            "TELEGRAM_VOICE_TRANSCRIBE_TIMEOUT_SECONDS",
            120,
        ),
        voice_alias_replacements=build_voice_alias_replacements(),
        voice_alias_learning_enabled=parse_bool_env(
            "TELEGRAM_VOICE_ALIAS_LEARNING_ENABLED",
            True,
        ),
        voice_alias_learning_path=os.getenv(
            "TELEGRAM_VOICE_ALIAS_LEARNING_PATH",
            os.path.join(state_dir, "voice_alias_learning.json"),
        ).strip()
        or os.path.join(state_dir, "voice_alias_learning.json"),
        voice_alias_learning_min_examples=parse_int_env(
            "TELEGRAM_VOICE_ALIAS_LEARNING_MIN_EXAMPLES",
            2,
            minimum=1,
        ),
        voice_alias_learning_confirmation_window_seconds=parse_int_env(
            "TELEGRAM_VOICE_ALIAS_LEARNING_CONFIRMATION_WINDOW_SECONDS",
            900,
            minimum=30,
        ),
        voice_low_confidence_confirmation_enabled=parse_bool_env(
            "TELEGRAM_VOICE_LOW_CONFIDENCE_CONFIRMATION_ENABLED",
            True,
        ),
        voice_low_confidence_threshold=parse_float_env(
            "TELEGRAM_VOICE_LOW_CONFIDENCE_THRESHOLD",
            0.45,
            minimum=0.0,
            maximum=1.0,
        ),
        voice_low_confidence_message=(
            os.getenv(
                "TELEGRAM_VOICE_LOW_CONFIDENCE_MESSAGE",
                "Voice transcript confidence is low, resend",
            ).strip()
            or "Voice transcript confidence is low, resend"
        ),
        state_dir=state_dir,
        persistent_workers_enabled=parse_bool_env(
            "TELEGRAM_PERSISTENT_WORKERS_ENABLED",
            False,
        ),
        persistent_workers_max=parse_int_env(
            "TELEGRAM_PERSISTENT_WORKERS_MAX",
            4,
            minimum=1,
        ),
        persistent_workers_idle_timeout_seconds=parse_int_env(
            "TELEGRAM_PERSISTENT_WORKERS_IDLE_TIMEOUT_SECONDS",
            45 * 60,
            minimum=60,
        ),
        persistent_workers_policy_files=build_policy_watch_files(),
        canonical_sessions_enabled=parse_bool_env(
            "TELEGRAM_CANONICAL_SESSIONS_ENABLED",
            False,
        ),
        canonical_legacy_mirror_enabled=parse_bool_env(
            "TELEGRAM_CANONICAL_LEGACY_MIRROR_ENABLED",
            False,
        ),
        canonical_sqlite_enabled=parse_bool_env(
            "TELEGRAM_CANONICAL_SQLITE_ENABLED",
            False,
        ),
        canonical_sqlite_path=canonical_sqlite_path,
        canonical_json_mirror_enabled=parse_bool_env(
            "TELEGRAM_CANONICAL_JSON_MIRROR_ENABLED",
            False,
        ),
        memory_sqlite_path=memory_sqlite_path,
        memory_max_messages_per_key=parse_int_env(
            "TELEGRAM_MEMORY_MAX_MESSAGES_PER_KEY",
            4000,
            minimum=0,
        ),
        memory_max_summaries_per_key=parse_int_env(
            "TELEGRAM_MEMORY_MAX_SUMMARIES_PER_KEY",
            80,
            minimum=0,
        ),
        memory_prune_interval_seconds=parse_int_env(
            "TELEGRAM_MEMORY_PRUNE_INTERVAL_SECONDS",
            300,
            minimum=0,
        ),
        required_prefixes=parse_prefixes_env("TELEGRAM_REQUIRED_PREFIXES"),
        required_prefix_ignore_case=parse_bool_env(
            "TELEGRAM_REQUIRED_PREFIX_IGNORE_CASE",
            True,
        ),
        require_prefix_in_private=parse_bool_env(
            "TELEGRAM_REQUIRE_PREFIX_IN_PRIVATE",
            True,
        ),
        allow_private_chats_unlisted=parse_bool_env(
            "TELEGRAM_ALLOW_PRIVATE_CHATS_UNLISTED",
            False,
        ),
        allow_group_chats_unlisted=parse_bool_env(
            "TELEGRAM_ALLOW_GROUP_CHATS_UNLISTED",
            False,
        ),
        assistant_name=assistant_name,
        shared_memory_key=shared_memory_key,
        progress_label=progress_label,
        progress_elapsed_prefix=progress_elapsed_prefix,
        progress_elapsed_suffix=progress_elapsed_suffix,
        busy_message=busy_message,
        channel_plugin=channel_plugin,
        engine_plugin=parse_plugin_name_env("TELEGRAM_ENGINE_PLUGIN", "codex"),
        selectable_engine_plugins=parse_plugin_list_env(
            "TELEGRAM_SELECTABLE_ENGINE_PLUGINS",
            ["codex", "gemma", "pi"],
        ),
        codex_model=load_codex_model(),
        codex_reasoning_effort=load_codex_reasoning_effort(),
        gemma_provider=parse_plugin_name_env("GEMMA_PROVIDER", "ollama_ssh"),
        gemma_model=os.getenv("GEMMA_MODEL", "gemma4:26b").strip() or "gemma4:26b",
        gemma_base_url=os.getenv("GEMMA_BASE_URL", "http://127.0.0.1:11434").strip()
        or "http://127.0.0.1:11434",
        gemma_ssh_host=os.getenv("GEMMA_SSH_HOST", "server4-beast").strip() or "server4-beast",
        gemma_request_timeout_seconds=parse_int_env(
            "GEMMA_REQUEST_TIMEOUT_SECONDS",
            180,
            minimum=1,
        ),
        venice_api_key=os.getenv("VENICE_API_KEY", "").strip(),
        venice_base_url=os.getenv("VENICE_BASE_URL", "https://api.venice.ai/api/v1").strip()
        or "https://api.venice.ai/api/v1",
        venice_model=os.getenv("VENICE_MODEL", "mistral-31-24b").strip() or "mistral-31-24b",
        venice_temperature=parse_float_env(
            "VENICE_TEMPERATURE",
            0.2,
            minimum=0.0,
            maximum=2.0,
        ),
        venice_request_timeout_seconds=parse_int_env(
            "VENICE_REQUEST_TIMEOUT_SECONDS",
            180,
            minimum=1,
        ),
        chatgpt_web_bridge_script=os.getenv(
            "CHATGPT_WEB_BRIDGE_SCRIPT",
            shared_core_path("ops", "chatgpt_web_bridge.py"),
        ).strip()
        or shared_core_path("ops", "chatgpt_web_bridge.py"),
        chatgpt_web_python_bin=os.getenv("CHATGPT_WEB_PYTHON_BIN", "python3").strip()
        or "python3",
        chatgpt_web_browser_brain_url=os.getenv(
            "CHATGPT_WEB_BROWSER_BRAIN_URL",
            "http://127.0.0.1:47831",
        ).strip()
        or "http://127.0.0.1:47831",
        chatgpt_web_browser_brain_service=os.getenv(
            "CHATGPT_WEB_BROWSER_BRAIN_SERVICE",
            "server3-browser-brain.service",
        ).strip()
        or "server3-browser-brain.service",
        chatgpt_web_url=os.getenv("CHATGPT_WEB_URL", "https://chatgpt.com/").strip()
        or "https://chatgpt.com/",
        chatgpt_web_start_service=parse_bool_env("CHATGPT_WEB_START_SERVICE", False),
        chatgpt_web_request_timeout_seconds=parse_int_env(
            "CHATGPT_WEB_REQUEST_TIMEOUT_SECONDS",
            30,
            minimum=1,
        ),
        chatgpt_web_ready_timeout_seconds=parse_int_env(
            "CHATGPT_WEB_READY_TIMEOUT_SECONDS",
            45,
            minimum=1,
        ),
        chatgpt_web_response_timeout_seconds=parse_int_env(
            "CHATGPT_WEB_RESPONSE_TIMEOUT_SECONDS",
            180,
            minimum=1,
        ),
        chatgpt_web_poll_seconds=parse_float_env(
            "CHATGPT_WEB_POLL_SECONDS",
            3.0,
            minimum=0.1,
            maximum=30.0,
        ),
        pi_provider=parse_plugin_name_env("PI_PROVIDER", "ollama"),
        pi_model=os.getenv("PI_MODEL", "qwen3-coder:30b").strip() or "qwen3-coder:30b",
        pi_runner=parse_plugin_name_env("PI_RUNNER", "ssh"),
        pi_bin=os.getenv("PI_BIN", "pi").strip() or "pi",
        pi_ssh_host=os.getenv("PI_SSH_HOST", "server4-beast").strip() or "server4-beast",
        pi_local_cwd=os.getenv("PI_LOCAL_CWD", build_runtime_root()).strip()
        or build_runtime_root(),
        pi_remote_cwd=os.getenv("PI_REMOTE_CWD", "/tmp").strip() or "/tmp",
        pi_session_mode=parse_plugin_name_env("PI_SESSION_MODE", "none"),
        pi_session_dir=os.getenv("PI_SESSION_DIR", "").strip(),
        pi_session_max_bytes=parse_int_env(
            "PI_SESSION_MAX_BYTES",
            2 * 1024 * 1024,
            minimum=1,
        ),
        pi_session_max_age_seconds=parse_int_env(
            "PI_SESSION_MAX_AGE_SECONDS",
            7 * 24 * 60 * 60,
            minimum=1,
        ),
        pi_session_archive_retention_seconds=parse_int_env(
            "PI_SESSION_ARCHIVE_RETENTION_SECONDS",
            14 * 24 * 60 * 60,
            minimum=1,
        ),
        pi_session_archive_dir=os.getenv("PI_SESSION_ARCHIVE_DIR", "").strip(),
        pi_tools_mode=parse_plugin_name_env("PI_TOOLS_MODE", "default"),
        pi_tools_allowlist=os.getenv("PI_TOOLS_ALLOWLIST", "").strip(),
        pi_extra_args=os.getenv("PI_EXTRA_ARGS", "").strip(),
        pi_ollama_tunnel_enabled=parse_bool_env("PI_OLLAMA_TUNNEL_ENABLED", True),
        pi_ollama_tunnel_local_port=parse_int_env(
            "PI_OLLAMA_TUNNEL_LOCAL_PORT",
            11435,
            minimum=1,
        ),
        pi_ollama_tunnel_remote_host=os.getenv(
            "PI_OLLAMA_TUNNEL_REMOTE_HOST",
            "127.0.0.1",
        ).strip()
        or "127.0.0.1",
        pi_ollama_tunnel_remote_port=parse_int_env(
            "PI_OLLAMA_TUNNEL_REMOTE_PORT",
            11434,
            minimum=1,
        ),
        pi_request_timeout_seconds=parse_int_env(
            "PI_REQUEST_TIMEOUT_SECONDS",
            180,
            minimum=1,
        ),
        whatsapp_plugin_enabled=parse_bool_env("WHATSAPP_PLUGIN_ENABLED", False),
        whatsapp_bridge_api_base=os.getenv(
            "WHATSAPP_BRIDGE_API_BASE",
            "http://127.0.0.1:8787",
        ).strip(),
        whatsapp_bridge_auth_token=os.getenv("WHATSAPP_BRIDGE_AUTH_TOKEN", "").strip(),
        whatsapp_poll_timeout_seconds=parse_int_env(
            "WHATSAPP_POLL_TIMEOUT_SECONDS",
            20,
            minimum=1,
        ),
        signal_plugin_enabled=parse_bool_env("SIGNAL_PLUGIN_ENABLED", False),
        signal_bridge_api_base=os.getenv(
            "SIGNAL_BRIDGE_API_BASE",
            "http://127.0.0.1:18797",
        ).strip(),
        signal_bridge_auth_token=os.getenv("SIGNAL_BRIDGE_AUTH_TOKEN", "").strip(),
        signal_poll_timeout_seconds=parse_int_env(
            "SIGNAL_POLL_TIMEOUT_SECONDS",
            20,
            minimum=1,
        ),
        keyword_routing_enabled=parse_bool_env(
            "TELEGRAM_KEYWORD_ROUTING_ENABLED",
            True,
        ),
        diary_mode_enabled=parse_bool_env(
            "TELEGRAM_DIARY_MODE_ENABLED",
            False,
        ),
        diary_capture_quiet_window_seconds=parse_int_env(
            "TELEGRAM_DIARY_CAPTURE_QUIET_WINDOW_SECONDS",
            75,
            minimum=1,
        ),
        diary_timezone=(
            os.getenv("TELEGRAM_DIARY_TIMEZONE", "Australia/Brisbane").strip()
            or "Australia/Brisbane"
        ),
        diary_local_root=(
            os.getenv(
                "TELEGRAM_DIARY_LOCAL_ROOT",
                os.path.join(state_dir, "diary"),
            ).strip()
            or os.path.join(state_dir, "diary")
        ),
        diary_nextcloud_enabled=parse_bool_env(
            "TELEGRAM_DIARY_NEXTCLOUD_ENABLED",
            False,
        ),
        diary_nextcloud_base_url=os.getenv(
            "TELEGRAM_DIARY_NEXTCLOUD_BASE_URL",
            "",
        ).strip(),
        diary_nextcloud_username=os.getenv(
            "TELEGRAM_DIARY_NEXTCLOUD_USERNAME",
            "",
        ).strip(),
        diary_nextcloud_app_password=os.getenv(
            "TELEGRAM_DIARY_NEXTCLOUD_APP_PASSWORD",
            "",
        ).strip(),
        diary_nextcloud_remote_root=(
            os.getenv("TELEGRAM_DIARY_NEXTCLOUD_REMOTE_ROOT", "/Diary").strip()
            or "/Diary"
        ),
        affective_runtime_enabled=parse_bool_env(
            "TELEGRAM_AFFECTIVE_RUNTIME_ENABLED",
            False,
        ),
        affective_runtime_db_path=affective_runtime_db_path,
        affective_runtime_ping_target=affective_runtime_ping_target,
        policy_reset_memory_on_change=parse_bool_env(
            "TELEGRAM_POLICY_RESET_MEMORY_ON_CHANGE",
            False,
        ),
        empty_output_message=f"(No output from {assistant_name})",
    )
