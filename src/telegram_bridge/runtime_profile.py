"""Runtime-facing profile and routing policy helpers for the shared bridge core."""

from __future__ import annotations

import os
import re
import sqlite3
import time
from collections import OrderedDict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from telegram_bridge.channel_adapter import ChannelAdapter
from telegram_bridge.engine_catalog import (
    configured_codex_model,
    configured_default_engine,
    configured_gemma_model,
    configured_pi_model,
    configured_pi_provider,
)
from telegram_bridge.runtime_paths import build_shared_core_root, shared_core_path

HELP_COMMAND_ALIASES = ("/help", "/h")
CANCEL_COMMAND_ALIASES = ("/cancel", "/c")
RETRY_WITH_NEW_SESSION_PHASE = "Execution failed. Retrying once with a new session."
HA_KEYWORD_HELP_MESSAGE = (
    "HA mode needs an action. Example: `HA turn on masters AC to dry mode at 9:25am`."
)
SERVER3_KEYWORD_HELP_MESSAGE = (
    "Server3 TV mode needs an action. Example: `Server3 TV open desktop and play top YouTube result for deep house 2026`."
)
NEXTCLOUD_KEYWORD_HELP_MESSAGE = (
    "Nextcloud mode needs an action. Example: `Nextcloud create event tomorrow 3pm dentist in Personal calendar`."
)
SRO_KEYWORD_HELP_MESSAGE = (
    "SRO mode needs an action. Example: `SRO summary 24h`."
)
PREFIX_HELP_MESSAGE = (
    "Helper mode needs a prefixed prompt. Example: `@helper summarize this file`."
)
YOUTUBE_URL_RE = re.compile(
    r"(?P<url>https?://(?:[\w-]+\.)?(?:youtube\.com/(?:watch\?[^\s<>()]+|shorts/[^\s<>()]+|live/[^\s<>()]+|embed/[^\s<>()]+)|youtu\.be/[^\s<>()]+))",
    re.IGNORECASE,
)
YOUTUBE_LIGHTWEIGHT_REQUEST_RE = re.compile(
    r"^(?:(?:please|pls|summary|summarise|summarize|analyse|analyze|explain|transcript|full transcript|captions?|subtitles?|transcribe|translate|translation|key points?|timestamps?|таймкоды|переведи|перевод|суммаризируй|суммаризуй|кратко|краткое содержание|резюме|сводка|анализ|проанализируй|транскрипт|стенограмма|субтитры|расшифровка)(?:\s+(?:this|it|video|clip|short|link))?\s*)+$",
    re.IGNORECASE,
)
WHATSAPP_REPLY_PREFIX = "Даю справку:"
WHATSAPP_REPLY_PREFIX_RE = re.compile(r"^\s*даю\s+справку\s*:\s*", re.IGNORECASE)
WHATSAPP_LEGACY_REPLY_PREFIX_RE = re.compile(r"^\s*говорун\s*:\s*", re.IGNORECASE)
_RECENT_CODEX_MODEL_CACHE: "OrderedDict[Tuple[str, str, str], Tuple[float, Optional[int], str]]" = OrderedDict()
_RECENT_CODEX_STATE_PATH_CACHE: "OrderedDict[str, Tuple[float, Optional[str]]]" = OrderedDict()
_RECENT_CODEX_CACHE_LIMIT = 8
_RECENT_CODEX_STATE_PATH_CACHE_TTL_SECONDS = 1.0
_RECENT_CODEX_MODEL_CACHE_TTL_SECONDS = 1.0


def _remember_recent_cache_entry(cache: "OrderedDict[object, object]", key: object, value: object) -> None:
    cache[key] = value
    cache.move_to_end(key)
    while len(cache) > _RECENT_CODEX_CACHE_LIMIT:
        cache.popitem(last=False)


def _latest_codex_state_path(codex_home: Path) -> Optional[Path]:
    cache_key = str(codex_home)
    now = time.monotonic()
    cached_entry = _RECENT_CODEX_STATE_PATH_CACHE.get(cache_key)
    if cached_entry is not None:
        expires_at, cached_path = cached_entry
        if now < expires_at:
            _RECENT_CODEX_STATE_PATH_CACHE.move_to_end(cache_key)
            return Path(cached_path) if cached_path else None
        _RECENT_CODEX_STATE_PATH_CACHE.pop(cache_key, None)

    try:
        codex_home.stat()
    except OSError:
        return None

    latest_path: Optional[Path] = None
    latest_mtime_ns = -1
    for candidate in codex_home.glob("state_*.sqlite"):
        try:
            candidate_mtime_ns = candidate.stat().st_mtime_ns
        except OSError:
            continue
        if candidate_mtime_ns > latest_mtime_ns:
            latest_mtime_ns = candidate_mtime_ns
            latest_path = candidate

    _remember_recent_cache_entry(
        _RECENT_CODEX_STATE_PATH_CACHE,
        cache_key,
        (
            now + _RECENT_CODEX_STATE_PATH_CACHE_TTL_SECONDS,
            str(latest_path) if latest_path is not None else None,
        ),
    )
    return latest_path

def build_repo_root() -> str:
    return build_shared_core_root()

def build_ha_routing_script_allowlist() -> List[str]:
    return [
        shared_core_path("ops", "ha", "turn_entity_power.sh"),
        shared_core_path("ops", "ha", "schedule_entity_power.sh"),
        shared_core_path("ops", "ha", "set_climate_temperature.sh"),
        shared_core_path("ops", "ha", "schedule_climate_temperature.sh"),
        shared_core_path("ops", "ha", "set_climate_mode.sh"),
        shared_core_path("ops", "ha", "schedule_climate_mode.sh"),
    ]

def build_server3_routing_script_allowlist() -> List[str]:
    return [
        "/usr/local/bin/server3-tv-start",
        "/usr/local/bin/server3-tv-stop",
        shared_core_path("ops", "tv-desktop", "server3-tv-open-browser-url.sh"),
        shared_core_path("ops", "tv-desktop", "server3-tv-brave-remote-debug-session.sh"),
        shared_core_path("ops", "tv-desktop", "server3-youtube-open-top-result.sh"),
        shared_core_path("ops", "tv-desktop", "server3-tv-browser-youtube-pause.sh"),
        shared_core_path("ops", "tv-desktop", "server3-tv-browser-youtube-play.sh"),
    ]

def build_nextcloud_routing_script_allowlist() -> List[str]:
    return [
        shared_core_path("ops", "nextcloud", "nextcloud-files-list.sh"),
        shared_core_path("ops", "nextcloud", "nextcloud-file-upload.sh"),
        shared_core_path("ops", "nextcloud", "nextcloud-file-delete.sh"),
        shared_core_path("ops", "nextcloud", "nextcloud-calendars-list.sh"),
        shared_core_path("ops", "nextcloud", "nextcloud-calendar-create-event.sh"),
    ]

def build_sro_routing_script_allowlist() -> List[str]:
    return [
        shared_core_path("ops", "runtime_observer", "runtime_observer_ctl.sh"),
    ]

def assistant_label(config) -> str:
    identity = getattr(config, "identity", config)
    value = getattr(identity, "assistant_name", "").strip()
    return value or "Architect"

def _recent_codex_model_for_runtime(runtime_root: str) -> str:
    codex_home_raw = str(os.getenv("CODEX_HOME", "") or "").strip()
    codex_home = Path(codex_home_raw).expanduser() if codex_home_raw else Path.home() / ".codex"
    state_path = _latest_codex_state_path(codex_home)
    if state_path is None:
        return ""
    now = time.monotonic()
    cache_key = (str(codex_home), runtime_root, str(state_path))
    cached_entry = _RECENT_CODEX_MODEL_CACHE.get(cache_key)
    if cached_entry is not None:
        expires_at, _cached_mtime_ns, cached_model = cached_entry
        if now < expires_at:
            _RECENT_CODEX_MODEL_CACHE.move_to_end(cache_key)
            return cached_model
    try:
        state_mtime_ns = state_path.stat().st_mtime_ns
    except OSError:
        return ""
    if cached_entry is not None:
        expires_at, cached_mtime_ns, cached_model = cached_entry
        if cached_mtime_ns == int(state_mtime_ns):
            _remember_recent_cache_entry(
                _RECENT_CODEX_MODEL_CACHE,
                cache_key,
                (now + _RECENT_CODEX_MODEL_CACHE_TTL_SECONDS, cached_mtime_ns, cached_model),
            )
            return cached_model
    try:
        connection = sqlite3.connect(f"file:{state_path}?mode=ro", uri=True)
    except sqlite3.Error:
        return ""
    model = ""
    try:
        cursor = connection.cursor()
        order_clause = "coalesce(updated_at_ms, updated_at * 1000) desc"
        row = cursor.execute(
            f"""
            select model
            from threads
            where model is not null
              and trim(model) <> ''
            order by
                case
                    when ? <> '' and cwd = ? then 1
                    else 0
                end desc,
                {order_clause}
            limit 1
            """,
            (runtime_root, runtime_root),
        ).fetchone()
        if row and row[0]:
            model = str(row[0]).strip()
            return model
    except sqlite3.Error:
        return ""
    finally:
        connection.close()
        _remember_recent_cache_entry(
            _RECENT_CODEX_MODEL_CACHE,
            cache_key,
            (now + _RECENT_CODEX_MODEL_CACHE_TTL_SECONDS, int(state_mtime_ns), model),
        )
    return model

def _effective_codex_progress_model(config) -> str:
    model = configured_codex_model(config)
    if model:
        return model
    runtime_root = str(os.getenv("TELEGRAM_RUNTIME_ROOT", "") or "").strip()
    return _recent_codex_model_for_runtime(runtime_root)

def build_engine_progress_context_label(config, engine_name: Optional[str] = None) -> str:
    selected = str(engine_name or configured_default_engine(config) or "codex").strip().lower()
    if not selected:
        return ""
    if selected == "pi":
        provider = configured_pi_provider(config)
        model = configured_pi_model(config)
        parts = ["pi", provider]
        if model:
            parts.append(model)
        return f"({' | '.join(parts)})"
    if selected == "venice":
        engines = getattr(config, "engines", config)
        model = str(getattr(engines, "venice_model", "mistral-31-24b") or "mistral-31-24b").strip()
        parts = ["venice"]
        if model:
            parts.append(model)
        return f"({' | '.join(parts)})"
    if selected == "gemma":
        engines = getattr(config, "engines", config)
        provider = str(getattr(engines, "gemma_provider", "ollama_ssh") or "ollama_ssh").strip().lower()
        model = configured_gemma_model(config)
        parts = ["ollama(s4)"]
        if provider and provider not in {"ollama", "ollama_ssh"}:
            parts.append(provider)
        if model:
            parts.append(model)
        return f"({' | '.join(parts)})"
    if selected == "codex":
        model = _effective_codex_progress_model(config)
        return f"(codex | {model})" if model else "(codex)"
    if selected == "mavali_eth":
        model = _effective_codex_progress_model(config)
        return f"(mavali_eth | codex | {model})" if model else "(mavali_eth | codex)"
    return f"({selected})"

def start_command_message(config) -> str:
    return f"Telegram {assistant_label(config)} bridge is online. Send a prompt to begin."

def resume_retry_phase(config) -> str:
    return f"Retrying as a new {assistant_label(config)} session."

def extract_keyword_request(text: str, keywords: List[str]) -> tuple[bool, str]:
    stripped = text.strip()
    if not stripped:
        return False, ""

    lowered = stripped.lower()
    for keyword in keywords:
        if lowered == keyword:
            return True, ""
        if lowered.startswith(keyword):
            remainder = stripped[len(keyword):]
            if remainder and remainder[0] not in (" ", ":", "-"):
                continue
            return True, remainder.lstrip(" :-\t")
    return False, ""

def extract_ha_keyword_request(text: str) -> tuple[bool, str]:
    return extract_keyword_request(text, ["ha", "home assistant"])

def extract_server3_keyword_request(text: str) -> tuple[bool, str]:
    return extract_keyword_request(text, ["server3 tv"])

def extract_nextcloud_keyword_request(text: str) -> tuple[bool, str]:
    return extract_keyword_request(text, ["nextcloud"])

def extract_sro_keyword_request(text: str) -> tuple[bool, str]:
    return extract_keyword_request(text, ["sro", "server3 runtime observer", "runtime observer"])

def extract_youtube_link_request(text: str) -> tuple[bool, str]:
    stripped = text.strip()
    if not stripped:
        return False, ""

    match = YOUTUBE_URL_RE.search(stripped)
    if match is None:
        return False, ""

    url = match.group("url").rstrip(").,!?]}'\"")
    remainder = f"{stripped[: match.start()]} {stripped[match.end() :]}"
    normalized_remainder = re.sub(r"[\s\.,!?:;()\[\]{}'\"`~@#$%^&*_+=/\\|-]+", " ", remainder).strip()
    if normalized_remainder and not YOUTUBE_LIGHTWEIGHT_REQUEST_RE.fullmatch(normalized_remainder):
        return False, ""
    return True, url

def build_ha_keyword_prompt(user_request: str) -> str:
    scripts = "\n".join(f"- {path}" for path in build_ha_routing_script_allowlist())
    return (
        "Home Assistant priority mode is active.\n"
        "Treat this as a Home Assistant action request.\n"
        f"User request: {user_request.strip()}\n\n"
        "Mandatory execution policy:\n"
        f"{scripts}\n"
        "- For scheduling, only use the schedule_* scripts with --at or --in.\n"
        "- Do not use inline systemd-run, /bin/bash -lc, or direct curl commands for HA actions.\n"
        "- If entity/time/mode is unclear, ask one concise clarification question instead of guessing.\n"
        "- After execution, report the result with state or timer/service unit names."
    )

def build_server3_keyword_prompt(user_request: str) -> str:
    scripts = "\n".join(f"- {path}" for path in build_server3_routing_script_allowlist())
    return (
        "Server3 TV operations priority mode is active.\n"
        "Treat this as a Server3 TV desktop/browser/UI action request.\n"
        f"User request: {user_request.strip()}\n\n"
        "Mandatory execution policy:\n"
        f"{scripts}\n"
        "- Prefer deterministic script execution over ad-hoc shell steps.\n"
        "- For browser navigation, use server3-tv-open-browser-url.sh with firefox or brave and explicit URL.\n"
        "- When a visible Brave session with remote debugging is needed, use server3-tv-brave-remote-debug-session.sh.\n"
        "- For YouTube top-result playback, use server3-youtube-open-top-result.sh with quoted query.\n"
        "- Respect optional min-duration constraints when explicitly requested.\n"
        "- If intent is unclear, ask one concise clarification question instead of guessing.\n"
        "- After execution, report exact scripts/commands used and final outcome."
    )

def build_nextcloud_keyword_prompt(user_request: str) -> str:
    scripts = "\n".join(f"- {path}" for path in build_nextcloud_routing_script_allowlist())
    return (
        "Nextcloud operations priority mode is active.\n"
        "Treat this as a Nextcloud file/calendar action request.\n"
        f"User request: {user_request.strip()}\n\n"
        "Mandatory execution policy:\n"
        f"{scripts}\n"
        "- Prefer deterministic script execution over ad-hoc shell or direct curl commands.\n"
        "- For file browsing use nextcloud-files-list.sh.\n"
        "- For calendar discovery use nextcloud-calendars-list.sh before creating events if unsure.\n"
        "- Do not print or expose credentials.\n"
        "- If path/calendar/time is unclear, ask one concise clarification question.\n"
        "- After execution, report exact scripts used and final outcome."
    )

def build_sro_keyword_prompt(user_request: str) -> str:
    scripts = "\n".join(f"- {path}" for path in build_sro_routing_script_allowlist())
    return (
        "Server3 Runtime Observer priority mode is active.\n"
        "Treat this as a Server3 runtime observability request.\n"
        f"User request: {user_request.strip()}\n\n"
        "Mandatory execution policy:\n"
        f"{scripts}\n"
        "- Prefer runtime_observer_ctl.sh over direct python, systemctl, journalctl, or ad-hoc shell commands for supported observer actions.\n"
        "- Supported observer commands are: `status`, `summary --hours N`, `collect`, and `notify-test`.\n"
        "- Use `status` for current health/KPI state.\n"
        "- Use `summary --hours N` for rolling windows such as 6h, 24h, or 72h.\n"
        "- Use `notify-test` only when the user explicitly asks to send a runtime observer test alert.\n"
        "- Use `collect` only when the user explicitly asks to collect and persist a fresh snapshot.\n"
        "- If the requested observer action is unclear, ask one concise clarification question instead of guessing.\n"
        "- After execution, report the exact command used and the resulting KPI state or outcome."
    )

def is_whatsapp_channel(client: ChannelAdapter) -> bool:
    return getattr(client, "channel_name", "") == "whatsapp"

def is_signal_channel(client: ChannelAdapter) -> bool:
    return getattr(client, "channel_name", "") == "signal"

def command_bypasses_required_prefix(client: ChannelAdapter, command: Optional[str]) -> bool:
    return is_whatsapp_channel(client) and command == "/voice-alias"

def apply_outbound_reply_prefix(client: ChannelAdapter, text: str) -> str:
    if not is_whatsapp_channel(client):
        return text
    stripped = (text or "").strip()
    if not stripped:
        return text
    if WHATSAPP_REPLY_PREFIX_RE.match(stripped):
        body = WHATSAPP_REPLY_PREFIX_RE.sub("", stripped, count=1).strip()
    else:
        body = WHATSAPP_LEGACY_REPLY_PREFIX_RE.sub("", stripped, count=1).strip()
    if not body:
        return WHATSAPP_REPLY_PREFIX
    return f"{WHATSAPP_REPLY_PREFIX} {body}"
