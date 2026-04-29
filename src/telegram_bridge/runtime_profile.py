"""Runtime-facing profile and routing policy helpers for the shared bridge core."""

from __future__ import annotations

import os
import re
from typing import List, Optional

try:
    from .channel_adapter import ChannelAdapter
    from .runtime_paths import build_shared_core_root, shared_core_path
except ImportError:
    from channel_adapter import ChannelAdapter
    from runtime_paths import build_shared_core_root, shared_core_path


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
BROWSER_BRAIN_KEYWORD_HELP_MESSAGE = (
    "Server3 Browser mode needs an action. Example: `Server3 Browser open https://example.com and snapshot the page`."
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
        shared_core_path("ops", "tv-desktop", "server3-tv-brave-browser-brain-session.sh"),
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


def build_browser_brain_routing_script_allowlist() -> List[str]:
    return [
        shared_core_path("ops", "browser_brain", "browser_brain_ctl.sh"),
        shared_core_path("ops", "browser_brain", "status_service.sh"),
    ]


def build_sro_routing_script_allowlist() -> List[str]:
    return [
        shared_core_path("ops", "runtime_observer", "runtime_observer_ctl.sh"),
    ]


def assistant_label(config) -> str:
    value = getattr(config, "assistant_name", "").strip()
    return value or "Architect"


def build_engine_progress_context_label(config, engine_name: Optional[str] = None) -> str:
    selected = str(engine_name or getattr(config, "engine_plugin", "codex") or "codex").strip().lower()
    if not selected:
        return ""
    if selected == "pi":
        provider = str(getattr(config, "pi_provider", "ollama") or "ollama").strip().lower()
        model = str(getattr(config, "pi_model", "qwen3-coder:30b") or "qwen3-coder:30b").strip()
        parts = ["pi", provider]
        if model:
            parts.append(model)
        return f"({' | '.join(parts)})"
    if selected == "venice":
        model = str(getattr(config, "venice_model", "mistral-31-24b") or "mistral-31-24b").strip()
        parts = ["venice"]
        if model:
            parts.append(model)
        return f"({' | '.join(parts)})"
    if selected == "gemma":
        provider = str(getattr(config, "gemma_provider", "ollama_ssh") or "ollama_ssh").strip().lower()
        model = str(getattr(config, "gemma_model", "gemma4:26b") or "gemma4:26b").strip()
        parts = ["gemma"]
        if provider and provider not in {"ollama", "ollama_ssh"}:
            parts.append(provider)
        if model:
            parts.append(model)
        return f"({' | '.join(parts)})"
    if selected == "codex":
        model = str(getattr(config, "codex_model", "") or "").strip()
        return f"(codex | {model})" if model else "(codex)"
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


def extract_browser_brain_keyword_request(text: str) -> tuple[bool, str]:
    return extract_keyword_request(text, ["server3 browser", "browser brain"])


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
        "- When a visible Browser Brain-attachable Brave session is needed, use server3-tv-brave-browser-brain-session.sh.\n"
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


def build_browser_brain_keyword_prompt(user_request: str) -> str:
    scripts = "\n".join(f"- {path}" for path in build_browser_brain_routing_script_allowlist())
    return (
        "Server3 Browser Brain priority mode is active.\n"
        "Treat this as a Server3 browser-control action request.\n"
        f"User request: {user_request.strip()}\n\n"
        "Mandatory execution policy:\n"
        f"{scripts}\n"
        "- Prefer browser_brain_ctl.sh over raw curl or ad-hoc shell commands.\n"
        "- Start with `browser_brain_ctl.sh start` when browser state may be idle.\n"
        "- For page interaction, use `open` or `navigate`, then `snapshot`, then act using refs from that snapshot.\n"
        "- Use exact snapshot refs for click/type/press/hover/select/upload actions; do not guess element targets.\n"
        "- Use console/network/dialogs for browser diagnostics instead of arbitrary JavaScript when possible.\n"
        "- After execution, report exact commands used plus resulting tab_id, snapshot_id, refs, and final URL/title."
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
