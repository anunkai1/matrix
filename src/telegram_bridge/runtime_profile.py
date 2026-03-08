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
TRADE_KEYWORD_HELP_MESSAGE = (
    "Trade mode needs an action. Example: `Trade long BTC 2000 USDT 10x market`."
)
PREFIX_HELP_MESSAGE = (
    "Helper mode needs a prefixed prompt. Example: `@helper summarize this file`."
)
WHATSAPP_REPLY_PREFIX = "Даю справку:"
WHATSAPP_REPLY_PREFIX_RE = re.compile(r"^\s*даю\s+справку\s*:\s*", re.IGNORECASE)
WHATSAPP_LEGACY_REPLY_PREFIX_RE = re.compile(r"^\s*говорун\s*:\s*", re.IGNORECASE)
BLOCKED_PROMPT_MESSAGE = (
    "Птица Говорун отличается умом и сообразительностью, а потому политику сейчас "
    "обойдет стороной. Давай лучше о чем-то полезном, спокойном или веселом."
)


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


def build_trade_routing_script_allowlist() -> List[str]:
    return [
        shared_core_path("ops", "trading", "aster", "assistant_entry.py"),
        shared_core_path("ops", "trading", "aster", "trade_cli.sh"),
    ]


def assistant_label(config) -> str:
    value = getattr(config, "assistant_name", "").strip()
    return value or "Architect"


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


def extract_trade_keyword_request(text: str) -> tuple[bool, str]:
    return extract_keyword_request(text, ["trade", "aster trade"])


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


def build_trade_keyword_prompt(user_request: str, chat_id: int) -> str:
    scripts = "\n".join(f"- {path}" for path in build_trade_routing_script_allowlist())
    entrypoint = build_trade_routing_script_allowlist()[0]
    return (
        "ASTER trading priority mode is active.\n"
        "Treat this as a free-form ASTER futures trading request.\n"
        f"Chat key: tg:{chat_id}\n"
        f"User request: {user_request.strip()}\n\n"
        "Mandatory execution policy:\n"
        f"{scripts}\n"
        "- Execute only via deterministic script:\n"
        f"  python3 {entrypoint} --chat-id tg:{chat_id} --request '<user request>'\n"
        "- Do not place orders via direct curl/python snippets outside this script.\n"
        "- The script enforces confirmation tickets and risk guards (max notional, max leverage, daily loss).\n"
        "- If the script errors, report the error exactly and stop.\n"
        "- Return script output to the user verbatim.\n"
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
