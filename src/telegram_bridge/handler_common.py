import logging
from typing import Dict, List, Optional

from telegram_bridge.conversation_scope import ConversationScope, build_telegram_scope_key, scope_from_message
from telegram_bridge.handler_progress import ProgressReporter
from telegram_bridge.runtime_profile import assistant_label
from telegram_bridge.state_store import State, get_chat_engine
from telegram_bridge.engine_controls import selectable_engine_plugins

RATE_LIMIT_MESSAGE = "Rate limit exceeded. Please wait a minute and retry."

def normalize_command(text: str) -> Optional[str]:
    stripped = text.strip()
    head: Optional[str] = None
    if stripped.startswith("/"):
        head = stripped.split(maxsplit=1)[0]
    else:
        parts = stripped.split(maxsplit=1)
        if len(parts) == 2 and parts[0].startswith("@"):
            candidate = parts[1].lstrip()
            if candidate.startswith("/"):
                head = candidate.split(maxsplit=1)[0]
    if not head:
        return None
    return head.split("@", maxsplit=1)[0]

def strip_required_prefix(
    text: str,
    prefixes: List[str],
    ignore_case: bool,
) -> tuple[bool, str]:
    allowed_punctuation_separators = (":", "-", ",", ".")

    def strip_prefix_separators(value: str) -> str:
        index = 0
        while index < len(value):
            current = value[index]
            if current.isspace() or current in allowed_punctuation_separators:
                index += 1
                continue
            break
        return value[index:]

    stripped = text.strip()
    if not stripped:
        return False, ""
    probe = stripped.casefold() if ignore_case else stripped
    for prefix in prefixes:
        normalized_prefix = prefix.strip()
        if not normalized_prefix:
            continue
        normalized_probe = normalized_prefix.casefold() if ignore_case else normalized_prefix
        if probe == normalized_probe:
            return True, ""
        if not probe.startswith(normalized_probe):
            continue
        remainder = stripped[len(normalized_prefix):]
        if remainder and not (
            remainder[0].isspace() or remainder[0] in allowed_punctuation_separators
        ):
            continue
        return True, strip_prefix_separators(remainder)
    return False, stripped

def trim_output(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    marker = "\n\n[output truncated]"
    return text[: max(0, limit - len(marker))] + marker

def extract_chat_context(
    update: Dict[str, object],
) -> tuple[Optional[Dict[str, object]], Optional[ConversationScope], Optional[int]]:
    message = update.get("message")
    if not isinstance(message, dict):
        return None, None, None

    scope = scope_from_message(message)
    if scope is None:
        return None, None, None

    message_id = message.get("message_id")
    if not isinstance(message_id, int):
        message_id = None
    return message, scope, message_id

def extract_callback_query_context(
    update: Dict[str, object],
) -> tuple[Optional[Dict[str, object]], Optional[ConversationScope], Optional[int], str, str]:
    callback_query = update.get("callback_query")
    if not isinstance(callback_query, dict):
        return None, None, None, "", ""
    message = callback_query.get("message")
    if not isinstance(message, dict):
        return None, None, None, "", ""
    scope = scope_from_message(message)
    if scope is None:
        return None, None, None, "", ""
    callback_query_id = str(callback_query.get("id", "") or "").strip()
    callback_data = str(callback_query.get("data", "") or "").strip()
    message_id = message.get("message_id")
    if not isinstance(message_id, int):
        message_id = None
    return message, scope, message_id, callback_query_id, callback_data

def build_help_text(config) -> str:
    selectable = selectable_engine_plugins(config)
    engine_help_choices = ["status", *selectable, "reset"]
    minimal = (
        "Available commands:\n"
        "/start - verify bridge connectivity\n"
        "/help or /h - show this message\n"
        "/status - show bridge status and context\n"
        f"/engine {'|'.join(engine_help_choices)} - show or select this chat's engine\n"
        "/model - show this chat's current model for the active engine\n"
        "/model list - list model choices/help for the active engine\n"
        "/model <name> - set this chat's model for the active engine\n"
        "/model reset - clear this chat's model override for the active engine\n"
        "/effort - show this chat's current Codex reasoning effort\n"
        "/effort list - list effort choices/help for the active model\n"
        "/effort <low|medium|high|xhigh> - set this chat's Codex reasoning effort\n"
        "/effort reset - clear this chat's Codex reasoning effort override\n"
        "/pi - show Pi provider/model status for this chat\n"
        "/pi providers - list available Pi providers\n"
        "/pi provider <name> - set this chat's Pi provider\n"
        "/pi reset - clear this chat's Pi provider and model overrides\n"
        "/dishframed - turn a menu photo into a DishFramed preview\n"
        "/reset - clear saved context for this chat\n"
        "/cancel or /c - cancel current in-flight request for this chat\n"
        "/restart - queue a safe bridge restart\n"
        "/voice-alias add <source> => <target> - add approved alias manually"
    )
    if getattr(config, "channel_plugin", "telegram") in {"whatsapp", "signal"}:
        return minimal

    name = assistant_label(config)
    base = (
        minimal
        + "\n"
        "/voice-alias list - show pending learned voice corrections\n"
        "/voice-alias approve <id> - approve one learned correction\n"
        "browser_brain_ctl.sh status - show browser brain API/runtime state (local shell command)\n"
        "server3-tv-start - start TV desktop mode (local shell command)\n"
        "server3-tv-stop - stop TV desktop mode and return to CLI (local shell command)\n\n"
        f"Send text, images, voice notes, or files and {name} will process them.\n"
        + (
            ""
            if not getattr(config, "keyword_routing_enabled", True)
            else (
                "Use `HA ...` or `Home Assistant ...` to force Home Assistant script routing.\n"
                "Use `Server3 Browser ...` or `Browser Brain ...` for Server3 browser-brain automation.\n"
                "Use `Server3 TV ...` for Server3 desktop/browser/UI operations.\n"
                "Mention `server2` or `staker2` in your request to target the Server2 LAN host over SSH.\n"
                "Use `Nextcloud ...` for Nextcloud files/calendar operations.\n"
                "Use `SRO ...` for Server3 Runtime Observer status, summaries, snapshot collection, and test alerts."
            )
        )
    )
    return base

def build_status_text(
    state: State,
    config,
    chat_id: Optional[int] = None,
    scope_key: Optional[str] = None,
    message_thread_id: Optional[int] = None,
) -> str:
    if scope_key is None and chat_id is not None:
        scope_key = build_telegram_scope_key(chat_id, message_thread_id=message_thread_id)
    with state.lock:
        busy_count = len(state.busy_chats)
        restart_requested = state.restart_requested
        restart_in_progress = state.restart_in_progress
        if state.canonical_sessions_enabled:
            thread_count = sum(
                1 for session in state.chat_sessions.values() if session.thread_id.strip()
            )
            worker_count = sum(
                1
                for session in state.chat_sessions.values()
                if session.worker_created_at is not None and session.worker_last_used_at is not None
            )
            has_thread = False
            has_worker = False
            if scope_key is not None:
                session = state.chat_sessions.get(scope_key)
                if session is not None:
                    has_thread = bool(session.thread_id.strip())
                    has_worker = (
                        session.worker_created_at is not None
                        and session.worker_last_used_at is not None
                    )
        else:
            thread_count = len(state.chat_threads)
            worker_count = len(state.worker_sessions)
            has_thread = scope_key in state.chat_threads if scope_key is not None else False
            has_worker = scope_key in state.worker_sessions if scope_key is not None else False

    lines = [
        "Bridge status: online",
        f"Allowed chats: {len(config.allowed_chat_ids)}",
        f"Required prefixes: {', '.join(config.required_prefixes) if config.required_prefixes else '(none)'}",
        f"Default engine: {getattr(config, 'engine_plugin', 'codex')}",
        f"Selectable engines: {', '.join(getattr(config, 'selectable_engine_plugins', [])) or '(none)'}",
        f"Busy chats: {busy_count}",
        f"Saved Codex threads: {thread_count}",
        (
            "Persistent workers: "
            f"enabled={config.persistent_workers_enabled} "
            f"active={worker_count}/{config.persistent_workers_max} "
            f"idle_expiry=disabled"
        ),
        f"Safe restart queued: {restart_requested}",
        f"Safe restart in progress: {restart_in_progress}",
    ]

    if scope_key is not None:
        selected_engine = get_chat_engine(state, scope_key)
        lines.append(f"This chat has Codex thread: {has_thread}")
        lines.append(f"This chat has worker session: {has_worker}")
        lines.append(f"This chat engine: {selected_engine or getattr(config, 'engine_plugin', 'codex')}")

    return "\n".join(lines)
