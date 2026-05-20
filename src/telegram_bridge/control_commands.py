import logging
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from telegram_bridge.channel_adapter import ChannelAdapter
from telegram_bridge.dream_loop_state import (
    LATEST_RUN_STATE,
    LATEST_TRUTH_STATE,
    build_dream_loop_artifact_path,
    build_stale_context_state_path,
    get_scope_stale_context_status,
    mark_scope_stale_context_handled,
)
from telegram_bridge.engine_adapter import PiEngineAdapter
from telegram_bridge.session_manager import request_safe_restart, trigger_restart_async
from telegram_bridge.state_store import State, clear_thread_id, clear_worker_session
from telegram_bridge.structured_logging import emit_event
from telegram_bridge import response_delivery
from telegram_bridge import prompt_execution

CANCEL_REQUESTED_MESSAGE = "Cancel requested. Stopping current request."
CANCEL_ALREADY_REQUESTED_MESSAGE = (
    "Cancel is already in progress. Waiting for current request to stop."
)
CANCEL_NO_ACTIVE_MESSAGE = "No active request to cancel."

request_chat_cancel = response_delivery.request_chat_cancel


def _read_json_artifact(path):
    try:
        import json

        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except FileNotFoundError:
        return None
    except Exception:
        logging.exception("Failed to read dream-loop artifact %s", path)
        return None
    return payload if isinstance(payload, dict) else None


def _brisbane_now_iso() -> str:
    return datetime.now(ZoneInfo("Australia/Brisbane")).isoformat()


def _send_command_reply(
    client: ChannelAdapter,
    chat_id: int,
    message_thread_id: Optional[int],
    message_id: Optional[int],
    text: str,
) -> None:
    client.send_message(
        chat_id,
        text,
        reply_to_message_id=message_id,
        message_thread_id=message_thread_id,
    )


def handle_reset_command(
    state: State,
    config,
    client: ChannelAdapter,
    scope_key: str,
    chat_id: int,
    message_thread_id: Optional[int],
    message_id: Optional[int],
) -> None:
    removed_thread = clear_thread_id(state, scope_key)
    removed_worker = clear_worker_session(state, scope_key) if config.persistent_workers_enabled else False
    stale_status = mark_scope_stale_context_handled(
        build_stale_context_state_path(config.state_dir),
        scope_key,
        handled_at=_brisbane_now_iso(),
    )
    try:
        PiEngineAdapter.clear_scope_session_files(config, scope_key)
    except Exception:
        logging.exception("Failed to archive Pi session files for scope=%s", scope_key)
    handled_stale_warning = bool(stale_status.get("warning_fingerprint"))
    if removed_thread or removed_worker:
        extra = " Outstanding stale-context warning marked handled." if handled_stale_warning else ""
        _send_command_reply(
            client,
            chat_id,
            message_thread_id,
            message_id,
            "Context reset. Your next message starts a new conversation." + extra,
        )
        return
    if handled_stale_warning:
        _send_command_reply(
            client,
            chat_id,
            message_thread_id,
            message_id,
            "No saved context was found for this chat. Outstanding stale-context warning marked handled.",
        )
        return
    _send_command_reply(
        client,
        chat_id,
        message_thread_id,
        message_id,
        "No saved context was found for this chat.",
    )


def handle_truth_status_command(
    state: State,
    config,
    client: ChannelAdapter,
    scope_key: str,
    chat_id: int,
    message_thread_id: Optional[int],
    message_id: Optional[int],
) -> None:
    del state
    truth_state = _read_json_artifact(build_dream_loop_artifact_path(LATEST_TRUTH_STATE))
    run_state = _read_json_artifact(build_dream_loop_artifact_path(LATEST_RUN_STATE))
    stale_status = get_scope_stale_context_status(
        build_stale_context_state_path(config.state_dir),
        scope_key,
    )
    if truth_state is None or run_state is None:
        _send_command_reply(
            client,
            chat_id,
            message_thread_id,
            message_id,
            "Dream-loop state is unavailable. Run the dream loop first.",
        )
        return
    stale = truth_state.get("stale_context_eligibility", {}) or {}
    eligible_scope_keys = stale.get("eligible_scope_keys", []) or []
    lines = [
        "Dream-loop truth status:",
        f"- Generated at: {run_state.get('generated_at', 'unknown')}",
        f"- Run status: {run_state.get('run_status', 'unknown')}",
        f"- Current scope: {scope_key}",
        f"- Scope currently eligible for stale warning: {'yes' if scope_key in eligible_scope_keys else 'no'}",
        f"- Outstanding stale warning: {'yes' if stale_status.get('warning_outstanding') else 'no'}",
    ]
    warning_fingerprint = str(stale_status.get("warning_fingerprint") or "")
    if warning_fingerprint:
        lines.append(f"- Warning fingerprint tracked: `{warning_fingerprint[:12]}`")
    handled_at = str(stale_status.get("handled_at") or "")
    if handled_at:
        lines.append(f"- Last handled at: {handled_at}")
    changed_machine_inputs = stale.get("changed_machine_inputs", []) or []
    changed_policy_inputs = stale.get("changed_policy_inputs", []) or []
    lines.append(
        "- Changed machine inputs: " + (", ".join(changed_machine_inputs) if changed_machine_inputs else "none")
    )
    lines.append(
        "- Changed policy inputs: " + (", ".join(changed_policy_inputs) if changed_policy_inputs else "none")
    )
    skipped_checks = run_state.get("skipped_checks", []) or []
    if skipped_checks:
        labels = []
        for item in skipped_checks:
            if isinstance(item, dict):
                labels.append(f"{item.get('check_id', 'unknown')} ({item.get('reason', 'skipped')})")
        lines.append("- Skipped checks: " + (", ".join(labels) if labels else "none"))
    _send_command_reply(
        client,
        chat_id,
        message_thread_id,
        message_id,
        "\n".join(lines),
    )

def handle_restart_command(
    state: State,
    client: ChannelAdapter,
    chat_id: int,
    message_thread_id: Optional[int],
    message_id: Optional[int],
) -> None:
    status, busy_count = request_safe_restart(state, chat_id, message_thread_id, message_id)
    emit_event(
        "bridge.restart_requested",
        fields={
            "chat_id": chat_id,
            "message_id": message_id,
            "status": status,
            "busy_count": busy_count,
        },
    )
    if status == "in_progress":
        _send_command_reply(
            client,
            chat_id,
            message_thread_id,
            message_id,
            "Restart is already in progress.",
        )
        return
    if status == "already_queued":
        _send_command_reply(
            client,
            chat_id,
            message_thread_id,
            message_id,
            "Restart is already queued and will run after current work completes.",
        )
        return
    if status == "queued":
        _send_command_reply(
            client,
            chat_id,
            message_thread_id,
            message_id,
            f"Safe restart queued. Waiting for {busy_count} active request(s) to finish.",
        )
        return

    _send_command_reply(
        client,
        chat_id,
        message_thread_id,
        message_id,
        "No active request. Restarting bridge now.",
    )
    trigger_restart_async(state, client, chat_id, message_thread_id, message_id)

def handle_cancel_command(
    state: State,
    client: ChannelAdapter,
    scope_key: str,
    chat_id: int,
    message_thread_id: Optional[int],
    message_id: Optional[int],
) -> None:
    status = request_chat_cancel(state, scope_key)
    emit_event(
        "bridge.cancel_requested",
        fields={"chat_id": chat_id, "message_id": message_id, "status": status},
    )
    if status == "requested":
        _send_command_reply(
            client,
            chat_id,
            message_thread_id,
            message_id,
            CANCEL_REQUESTED_MESSAGE,
        )
        return
    if status == "already_requested":
        _send_command_reply(
            client,
            chat_id,
            message_thread_id,
            message_id,
            CANCEL_ALREADY_REQUESTED_MESSAGE,
        )
        return
    if status == "unavailable":
        _send_command_reply(
            client,
            chat_id,
            message_thread_id,
            message_id,
            "Active request cannot be canceled at this stage. Please wait a few seconds and retry.",
        )
        return
    _send_command_reply(
        client,
        chat_id,
        message_thread_id,
        message_id,
        CANCEL_NO_ACTIVE_MESSAGE,
    )
