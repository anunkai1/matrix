import logging
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import datetime as dt
import copy
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple
from urllib import error as urllib_error
from urllib import request as urllib_request
from urllib.parse import urlparse

try:
    from .auth_state import refresh_runtime_auth_fingerprint
    from . import attachment_processing
    from .background_tasks import start_daemon_thread
    from . import engine_controls
    from . import response_delivery
    from .conversation_scope import (
        ConversationScope,
        build_telegram_scope_key,
        parse_telegram_scope_key,
        scope_from_message,
    )
    from .executor import (
        ExecutorCancelledError,
        ExecutorProgressEvent,
        parse_executor_output,
        should_reset_thread_after_resume_failure,
    )
    from .channel_adapter import ChannelAdapter
    from .command_routing import handle_callback_query, handle_known_command
    from . import dishframed_processing
    from .diary_processing import (
        build_diary_entry_title,
        build_diary_photo_caption,
        build_diary_progress_context_label,
        build_diary_queue_status,
        build_diary_today_status,
        diary_capture_batch_worker,
        diary_control_command,
        diary_queue_worker,
        ensure_diary_queue_processor,
        process_diary_batch,
        queue_diary_capture,
        transcribe_voice_for_diary_batch,
    )
    from .diary_store import (
        DiaryEntry,
        DiaryPhoto,
        append_day_entry,
        copy_photo_to_day_assets,
        diary_day_docx_path,
        diary_day_remote_docx_path,
        diary_mode_enabled,
        diary_nextcloud_enabled,
        diary_timezone,
        read_day_entries,
        upload_to_nextcloud,
    )
    from .engine_adapter import CodexEngineAdapter, EngineAdapter
    from .handler_models import (
        CallbackActionContext,
        CallbackActionResult,
        DishframedRequest,
        DocumentPayload,
        IncomingUpdateContext,
        KnownCommandContext,
        OutboundMediaDirective,
        PreparedPromptInput,
        PreparedUpdateRequest,
        PromptRequest,
        UpdateDispatchRequest,
        UpdateFlowState,
        YoutubeRequest,
        build_dishframed_request,
        build_prompt_request,
        build_youtube_request,
    )
    from . import message_inputs
    from . import youtube_processing
    from .memory_engine import (
        MemoryEngine,
        TurnContext,
        build_memory_help_lines,
        handle_memory_command,
        handle_natural_language_memory_query,
    )
    from .memory_scope import (
        resolve_memory_conversation_key,
        resolve_shared_memory_archive_key,
    )
    from .memory_merge import merge_conversation_keys
    from .plugin_registry import build_default_plugin_registry
    from . import prompt_execution
    from . import prompt_preparation
    from .runtime_profile import (
        BROWSER_BRAIN_KEYWORD_HELP_MESSAGE,
        HA_KEYWORD_HELP_MESSAGE,
        HELP_COMMAND_ALIASES,
        CANCEL_COMMAND_ALIASES,
        NEXTCLOUD_KEYWORD_HELP_MESSAGE,
        PREFIX_HELP_MESSAGE,
        RETRY_WITH_NEW_SESSION_PHASE,
        SERVER3_KEYWORD_HELP_MESSAGE,
        WHATSAPP_REPLY_PREFIX,
        WHATSAPP_REPLY_PREFIX_RE,
        apply_outbound_reply_prefix,
        assistant_label,
        build_engine_progress_context_label,
        build_browser_brain_keyword_prompt,
        build_browser_brain_routing_script_allowlist,
        build_ha_keyword_prompt,
        build_ha_routing_script_allowlist,
        build_nextcloud_keyword_prompt,
        build_nextcloud_routing_script_allowlist,
        build_server3_keyword_prompt,
        build_server3_routing_script_allowlist,
        command_bypasses_required_prefix,
        extract_browser_brain_keyword_request,
        extract_ha_keyword_request,
        extract_nextcloud_keyword_request,
        extract_server3_keyword_request,
        is_signal_channel,
        is_whatsapp_channel,
        resume_retry_phase,
        start_command_message,
    )
    from .runtime_routing import apply_priority_keyword_routing, apply_required_prefix_gate
    from .session_manager import (
        ensure_chat_worker_session,
        finalize_chat_work,
        is_rate_limited,
        mark_busy,
        request_safe_restart,
        trigger_restart_async,
    )
    from .state_store import PendingDiaryBatch, RecentPhotoSelection, State, StateRepository
    from .structured_logging import emit_event
    from . import special_request_processing
    from .transport import TELEGRAM_CAPTION_LIMIT, TELEGRAM_LIMIT
    from .update_flow import (
        allow_update_chat,
        build_update_flow_state,
        extract_incoming_update_context,
        maybe_handle_diary_update_flow,
        prepare_update_dispatch_request,
        prepare_update_request,
        start_dishframed_dispatch,
        start_standard_dispatch,
    )
except ImportError:
    from auth_state import refresh_runtime_auth_fingerprint
    import attachment_processing
    from background_tasks import start_daemon_thread
    import engine_controls
    import response_delivery
    from conversation_scope import (
        ConversationScope,
        build_telegram_scope_key,
        parse_telegram_scope_key,
        scope_from_message,
    )
    from executor import (
        ExecutorCancelledError,
        ExecutorProgressEvent,
        parse_executor_output,
        should_reset_thread_after_resume_failure,
    )
    from channel_adapter import ChannelAdapter
    from command_routing import handle_callback_query, handle_known_command
    import dishframed_processing
    from diary_processing import (
        build_diary_entry_title,
        build_diary_photo_caption,
        build_diary_progress_context_label,
        build_diary_queue_status,
        build_diary_today_status,
        diary_capture_batch_worker,
        diary_control_command,
        diary_queue_worker,
        ensure_diary_queue_processor,
        process_diary_batch,
        queue_diary_capture,
        transcribe_voice_for_diary_batch,
    )
    from diary_store import (
        DiaryEntry,
        DiaryPhoto,
        append_day_entry,
        copy_photo_to_day_assets,
        diary_day_docx_path,
        diary_day_remote_docx_path,
        diary_mode_enabled,
        diary_nextcloud_enabled,
        diary_timezone,
        read_day_entries,
        upload_to_nextcloud,
    )
    from engine_adapter import CodexEngineAdapter, EngineAdapter
    from handler_models import (
        CallbackActionContext,
        CallbackActionResult,
        DishframedRequest,
        DocumentPayload,
        IncomingUpdateContext,
        KnownCommandContext,
        OutboundMediaDirective,
        PreparedPromptInput,
        PreparedUpdateRequest,
        PromptRequest,
        UpdateDispatchRequest,
        UpdateFlowState,
        YoutubeRequest,
        build_dishframed_request,
        build_prompt_request,
        build_youtube_request,
    )
    import message_inputs
    import youtube_processing
    from memory_engine import (
        MemoryEngine,
        TurnContext,
        build_memory_help_lines,
        handle_memory_command,
        handle_natural_language_memory_query,
    )
    from memory_scope import (
        resolve_memory_conversation_key,
        resolve_shared_memory_archive_key,
    )
    from memory_merge import merge_conversation_keys
    from plugin_registry import build_default_plugin_registry
    import prompt_execution
    import prompt_preparation
    from runtime_profile import (
        BROWSER_BRAIN_KEYWORD_HELP_MESSAGE,
        HA_KEYWORD_HELP_MESSAGE,
        HELP_COMMAND_ALIASES,
        CANCEL_COMMAND_ALIASES,
        NEXTCLOUD_KEYWORD_HELP_MESSAGE,
        PREFIX_HELP_MESSAGE,
        RETRY_WITH_NEW_SESSION_PHASE,
        SERVER3_KEYWORD_HELP_MESSAGE,
        WHATSAPP_REPLY_PREFIX,
        WHATSAPP_REPLY_PREFIX_RE,
        apply_outbound_reply_prefix,
        assistant_label,
        build_engine_progress_context_label,
        build_browser_brain_keyword_prompt,
        build_browser_brain_routing_script_allowlist,
        build_ha_keyword_prompt,
        build_ha_routing_script_allowlist,
        build_nextcloud_keyword_prompt,
        build_nextcloud_routing_script_allowlist,
        build_server3_keyword_prompt,
        build_server3_routing_script_allowlist,
        command_bypasses_required_prefix,
        extract_browser_brain_keyword_request,
        extract_ha_keyword_request,
        extract_nextcloud_keyword_request,
        extract_server3_keyword_request,
        is_signal_channel,
        is_whatsapp_channel,
        resume_retry_phase,
        start_command_message,
    )
    from runtime_routing import apply_priority_keyword_routing, apply_required_prefix_gate
    from session_manager import (
        ensure_chat_worker_session,
        finalize_chat_work,
        is_rate_limited,
        mark_busy,
        request_safe_restart,
        trigger_restart_async,
    )
    from state_store import PendingDiaryBatch, RecentPhotoSelection, State, StateRepository
    from structured_logging import emit_event
    import special_request_processing
    from transport import TELEGRAM_CAPTION_LIMIT, TELEGRAM_LIMIT
    from update_flow import (
        allow_update_chat,
        build_update_flow_state,
        extract_incoming_update_context,
        maybe_handle_diary_update_flow,
        prepare_update_dispatch_request,
        prepare_update_request,
        start_dishframed_dispatch,
        start_standard_dispatch,
    )

PROGRESS_TYPING_INTERVAL_SECONDS = 4
PROGRESS_EDIT_MIN_INTERVAL_SECONDS = 6
PROGRESS_HEARTBEAT_EDIT_SECONDS = 30
RATE_LIMIT_MESSAGE = "Rate limit exceeded. Please wait a minute and retry."
CANCEL_REQUESTED_MESSAGE = "Cancel requested. Stopping current request."
CANCEL_ALREADY_REQUESTED_MESSAGE = (
    "Cancel is already in progress. Waiting for current request to stop."
)
CANCEL_NO_ACTIVE_MESSAGE = "No active request to cancel."
GEMMA_HEALTH_TIMEOUT_SECONDS = 6
GEMMA_HEALTH_CURL_TIMEOUT_SECONDS = 5
DISHFRAMED_REPO_ROOT = dishframed_processing.DISHFRAMED_REPO_ROOT
DISHFRAMED_PYTHON_BIN = dishframed_processing.DISHFRAMED_PYTHON_BIN
DISHFRAMED_USAGE_MESSAGE = dishframed_processing.DISHFRAMED_USAGE_MESSAGE


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


parse_outbound_media_directive = response_delivery.parse_outbound_media_directive
parse_structured_outbound_payload = response_delivery.parse_structured_outbound_payload
output_contains_control_directive = response_delivery.output_contains_control_directive
media_extension = response_delivery.media_extension
infer_media_kind = response_delivery.infer_media_kind
is_voice_compatible_media = response_delivery.is_voice_compatible_media
is_voice_messages_forbidden_error = response_delivery.is_voice_messages_forbidden_error
send_chat_action_safe = response_delivery.send_chat_action_safe
send_executor_output = response_delivery.send_executor_output
compact_progress_text = response_delivery.compact_progress_text
send_input_too_long = response_delivery.send_input_too_long
send_canceled_response = response_delivery.send_canceled_response
send_generic_worker_error_response = response_delivery.send_generic_worker_error_response
send_timeout_response = response_delivery.send_timeout_response
emit_worker_exception_and_reply = response_delivery.emit_worker_exception_and_reply
normalize_known_executor_failure_message = response_delivery.normalize_known_executor_failure_message
extract_executor_failure_message = response_delivery.extract_executor_failure_message
send_executor_failure_message = response_delivery.send_executor_failure_message
register_cancel_event = response_delivery.register_cancel_event
clear_cancel_event = response_delivery.clear_cancel_event
cleanup_temp_files = response_delivery.cleanup_temp_files
cleanup_temp_dirs = response_delivery.cleanup_temp_dirs
finalize_request_progress = response_delivery.finalize_request_progress
start_background_worker = response_delivery.start_background_worker
request_chat_cancel = response_delivery.request_chat_cancel
pick_largest_photo_file_id = message_inputs.pick_largest_photo_file_id
extract_discrete_photo_file_ids = message_inputs.extract_discrete_photo_file_ids
normalize_optional_text = message_inputs.normalize_optional_text
iter_media_group_messages = message_inputs.iter_media_group_messages
collapse_media_group_updates = message_inputs.collapse_media_group_updates
build_reply_context_prompt = message_inputs.build_reply_context_prompt
should_include_telegram_context_prompt = message_inputs.should_include_telegram_context_prompt
build_telegram_context_prompt = message_inputs.build_telegram_context_prompt
select_media_prompt = message_inputs.select_media_prompt
extract_document_payload = message_inputs.extract_document_payload
extract_message_media_payload = message_inputs.extract_message_media_payload
extract_message_photo_file_ids = message_inputs.extract_message_photo_file_ids
remember_recent_scope_photos = message_inputs.remember_recent_scope_photos
get_recent_scope_photos = message_inputs.get_recent_scope_photos
describe_message_media = message_inputs.describe_message_media
extract_prompt_and_media = message_inputs.extract_prompt_and_media
extract_sender_name = message_inputs.extract_sender_name
download_photo_to_temp = attachment_processing.download_photo_to_temp
download_voice_to_temp = attachment_processing.download_voice_to_temp
download_document_to_temp = attachment_processing.download_document_to_temp
build_document_analysis_context = attachment_processing.build_document_analysis_context
build_archived_attachment_summary_context = (
    attachment_processing.build_archived_attachment_summary_context
)
archive_media_path = attachment_processing.archive_media_path
resolve_attachment_binary_or_summary = attachment_processing.resolve_attachment_binary_or_summary
build_voice_transcribe_command = attachment_processing.build_voice_transcribe_command
parse_voice_confidence = attachment_processing.parse_voice_confidence
apply_voice_alias_replacements = attachment_processing.apply_voice_alias_replacements
build_active_voice_alias_replacements = attachment_processing.build_active_voice_alias_replacements
build_low_confidence_voice_message = attachment_processing.build_low_confidence_voice_message
build_voice_alias_suggestions_message = attachment_processing.build_voice_alias_suggestions_message
suggest_required_prefix_alias_candidate = (
    attachment_processing.suggest_required_prefix_alias_candidate
)
maybe_suggest_voice_prefix_alias = attachment_processing.maybe_suggest_voice_prefix_alias
transcribe_voice = attachment_processing.transcribe_voice
build_youtube_analyzer_command = youtube_processing.build_youtube_analyzer_command
run_youtube_analyzer = youtube_processing.run_youtube_analyzer
build_youtube_summary_prompt = youtube_processing.build_youtube_summary_prompt
build_youtube_unavailable_message = youtube_processing.build_youtube_unavailable_message
build_youtube_transcript_output = youtube_processing.build_youtube_transcript_output
build_dishframed_command = dishframed_processing.build_dishframed_command
parse_dishframed_cli_output = dishframed_processing.parse_dishframed_cli_output
run_dishframed_cli = dishframed_processing.run_dishframed_cli


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


class ProgressReporter:
    def __init__(
        self,
        client: ChannelAdapter,
        chat_id: int,
        reply_to_message_id: Optional[int],
        message_thread_id: Optional[int],
        assistant_name: str,
        progress_label: str = "",
        progress_context_label: str = "",
        compact_elapsed_prefix: str = "Already",
        compact_elapsed_suffix: str = "s",
    ) -> None:
        self.client = client
        self.chat_id = chat_id
        self.reply_to_message_id = reply_to_message_id
        self.message_thread_id = message_thread_id
        self.assistant_name = assistant_name
        self.progress_label = progress_label.strip()
        self.progress_context_label = progress_context_label.strip()
        if compact_elapsed_prefix is None:
            self.compact_elapsed_prefix = "Already"
        else:
            self.compact_elapsed_prefix = compact_elapsed_prefix.strip()
        if compact_elapsed_suffix is None:
            self.compact_elapsed_suffix = "s"
        else:
            self.compact_elapsed_suffix = compact_elapsed_suffix
        self.started_at = time.time()
        self.progress_message_id: Optional[int] = None
        self.phase = ""
        self.commands_started = 0
        self.commands_completed = 0
        self.pending_update = True
        self.last_edit_at = 0.0
        self.last_rendered_text = ""
        self._is_compact_progress = bool(self.progress_label)
        self._edit_min_interval_seconds = (
            1.0 if self._is_compact_progress else PROGRESS_EDIT_MIN_INTERVAL_SECONDS
        )
        self._heartbeat_edit_seconds = (
            1.0 if self._is_compact_progress else PROGRESS_HEARTBEAT_EDIT_SECONDS
        )
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._worker: Optional[threading.Thread] = None
        self.edit_attempts = 0
        self.edit_successes = 0
        self.edit_failures_400 = 0
        self.edit_failures_other = 0

    def start(self) -> None:
        text = self._render_progress_text()
        try:
            self.progress_message_id = self.client.send_message_get_id(
                self.chat_id,
                text,
                reply_to_message_id=self.reply_to_message_id,
                message_thread_id=self.message_thread_id,
            )
        except Exception:
            logging.exception("Failed to send initial progress message for chat_id=%s", self.chat_id)
            self.progress_message_id = None

        self.last_rendered_text = text
        self.last_edit_at = time.time()
        self._worker = start_daemon_thread(self._heartbeat_loop)

    def close(self) -> None:
        self._stop_event.set()
        if self._worker:
            self._worker.join(timeout=2.0)
        self._maybe_edit(force=True)
        emit_event(
            "bridge.progress_edit_stats",
            fields={
                "chat_id": self.chat_id,
                "reply_to_message_id": self.reply_to_message_id,
                "progress_message_id": self.progress_message_id,
                "edit_attempts": self.edit_attempts,
                "edit_successes": self.edit_successes,
                "edit_failures_400": self.edit_failures_400,
                "edit_failures_other": self.edit_failures_other,
            },
        )

    def mark_success(self) -> None:
        self.set_phase("Finalizing response.", immediate=True)

    def mark_failure(self, detail: str) -> None:
        self.set_phase(detail, immediate=True)

    def set_phase(self, phase: str, immediate: bool = False) -> None:
        with self._lock:
            self.phase = phase
            self.pending_update = True
        if immediate:
            self._maybe_edit(force=True)

    def handle_executor_event(self, event: ExecutorProgressEvent) -> None:
        if event.kind == "turn_started":
            self.set_phase(f"{self.assistant_name} started reasoning.", immediate=False)
            return
        if event.kind == "reasoning":
            detail = (
                compact_progress_text(event.detail)
                if event.detail
                else f"{self.assistant_name} is reasoning."
            )
            self.set_phase(detail, immediate=False)
            return
        if event.kind == "agent_message":
            self.set_phase(f"{self.assistant_name} is preparing the reply.", immediate=False)
            return
        if event.kind == "command_started":
            with self._lock:
                self.commands_started += 1
            command_text = compact_progress_text(event.detail) if event.detail else "shell command"
            self.set_phase(f"Running command: {command_text}", immediate=False)
            return
        if event.kind == "command_completed":
            with self._lock:
                self.commands_completed += 1
            if event.exit_code is None:
                self.set_phase("A command finished.", immediate=False)
            elif event.exit_code == 0:
                self.set_phase("A command finished successfully.", immediate=False)
            else:
                self.set_phase(
                    f"A command finished with exit code {event.exit_code}.",
                    immediate=False,
                )

    def _heartbeat_loop(self) -> None:
        next_typing_at = 0.0
        next_progress_at = 0.0
        while not self._stop_event.is_set():
            now = time.time()
            if now >= next_typing_at:
                self._send_typing()
                next_typing_at = now + PROGRESS_TYPING_INTERVAL_SECONDS
            self._maybe_edit(force=False)
            if now >= next_progress_at:
                self._maybe_edit(force=True)
                next_progress_at = now + self._heartbeat_edit_seconds
            self._stop_event.wait(1.0)

    def _send_typing(self) -> None:
        try:
            self.client.send_chat_action(
                self.chat_id,
                action="typing",
                message_thread_id=self.message_thread_id,
            )
        except Exception:
            logging.debug("Failed to send typing action for chat_id=%s", self.chat_id)

    def _render_progress_text(self) -> str:
        elapsed = max(1, int(time.time() - self.started_at))
        with self._lock:
            phase = self.phase
            started = self.commands_started
            completed = self.commands_completed
        if self.progress_label:
            label = self.progress_label
        elif self.progress_context_label:
            label = f"{self.assistant_name} {self.progress_context_label} is working"
        else:
            label = f"{self.assistant_name} is working"
        if self._is_compact_progress:
            if not self.compact_elapsed_prefix and not self.compact_elapsed_suffix:
                text = f"{label}..."
            else:
                elapsed_prefix = (
                    f"{self.compact_elapsed_prefix} " if self.compact_elapsed_prefix else ""
                )
                text = f"{label}... {elapsed_prefix}{elapsed}{self.compact_elapsed_suffix}"
            return trim_output(text, TELEGRAM_LIMIT)

        text = f"{label}... {elapsed}s elapsed."
        if phase:
            text += f"\n{phase}"
        if started > 0:
            text += f"\nCommands done: {completed}/{started}"
        return trim_output(text, TELEGRAM_LIMIT)

    def _maybe_edit(self, force: bool = False) -> None:
        message_id = self.progress_message_id
        if message_id is None:
            return
        if not getattr(self.client, "supports_message_edits", True):
            return

        with self._lock:
            pending_update = self.pending_update
        if not force and not pending_update:
            return

        now = time.time()
        if not force and now - self.last_edit_at < self._edit_min_interval_seconds:
            return

        text = self._render_progress_text()
        if not force and text == self.last_rendered_text:
            with self._lock:
                self.pending_update = False
            return

        self.edit_attempts += 1
        try:
            self.client.edit_message(self.chat_id, message_id, text)
        except RuntimeError as exc:
            if "message is not modified" in str(exc).lower():
                self.edit_failures_400 += 1
                with self._lock:
                    self.pending_update = False
                return
            self.edit_failures_other += 1
            if getattr(self.client, "channel_name", "") in {"whatsapp", "signal"}:
                # WhatsApp edit failures can create visible noise if retried aggressively.
                self.progress_message_id = None
            logging.debug("Failed to edit progress message for chat_id=%s: %s", self.chat_id, exc)
            return
        except Exception:
            self.edit_failures_other += 1
            if getattr(self.client, "channel_name", "") in {"whatsapp", "signal"}:
                self.progress_message_id = None
            logging.debug("Failed to edit progress message for chat_id=%s", self.chat_id)
            return

        self.edit_successes += 1
        self.last_rendered_text = text
        self.last_edit_at = now
        with self._lock:
            self.pending_update = False


def transcribe_voice_for_chat(
    state: State,
    config,
    client: ChannelAdapter,
    chat_id: int,
    message_id: Optional[int],
    voice_file_id: str,
    echo_transcript: bool = True,
) -> Optional[str]:
    if not config.voice_transcribe_cmd:
        client.send_message(
            chat_id,
            config.voice_not_configured_message,
            reply_to_message_id=message_id,
        )
        return None

    voice_path: Optional[str] = None
    try:
        try:
            voice_path = download_voice_to_temp(client, config, voice_file_id)
        except ValueError as exc:
            logging.warning("Voice rejected for chat_id=%s: %s", chat_id, exc)
            client.send_message(chat_id, str(exc), reply_to_message_id=message_id)
            return None
        except Exception:
            logging.exception("Voice download failed for chat_id=%s", chat_id)
            client.send_message(
                chat_id,
                config.voice_download_error_message,
                reply_to_message_id=message_id,
            )
            return None

        try:
            transcript, confidence = transcribe_voice(config, voice_path)
        except subprocess.TimeoutExpired:
            logging.warning("Voice transcription timeout for chat_id=%s", chat_id)
            client.send_message(
                chat_id,
                config.timeout_message,
                reply_to_message_id=message_id,
            )
            return None
        except ValueError:
            logging.warning("Voice transcription was empty for chat_id=%s", chat_id)
            client.send_message(
                chat_id,
                config.voice_transcribe_empty_message,
                reply_to_message_id=message_id,
            )
            return None
        except RuntimeError:
            client.send_message(
                chat_id,
                config.voice_transcribe_error_message,
                reply_to_message_id=message_id,
            )
            return None
        except Exception:
            logging.exception("Unexpected voice transcription error for chat_id=%s", chat_id)
            client.send_message(
                chat_id,
                config.voice_transcribe_error_message,
                reply_to_message_id=message_id,
            )
            return None

        transcript, aliases_applied = apply_voice_alias_replacements(
            transcript,
            build_active_voice_alias_replacements(config, state),
        )
        if aliases_applied:
            logging.info("Applied voice alias corrections chat_id=%s", chat_id)

        if (
            getattr(config, "voice_low_confidence_confirmation_enabled", False)
            and confidence is not None
            and confidence < float(getattr(config, "voice_low_confidence_threshold", 0.0))
        ):
            learning_store = getattr(state, "voice_alias_learning_store", None)
            if learning_store is not None:
                try:
                    learning_store.register_low_confidence_transcript(
                        chat_id=chat_id,
                        transcript=transcript,
                        confidence=confidence,
                    )
                except Exception:
                    logging.exception("Failed to register low-confidence transcript for learning")
            client.send_message(
                chat_id,
                build_low_confidence_voice_message(config, transcript, confidence),
                reply_to_message_id=message_id,
            )
            return None

        if echo_transcript:
            try:
                heading = "Voice transcript:"
                if confidence is not None:
                    heading = f"Voice transcript (confidence {confidence:.2f}):"
                client.send_message(
                    chat_id,
                    f"{heading}\n{transcript}",
                    reply_to_message_id=message_id,
                )
            except Exception:
                logging.exception("Failed to send voice transcript echo for chat_id=%s", chat_id)
        return transcript
    finally:
        if voice_path:
            try:
                os.remove(voice_path)
            except OSError:
                logging.warning("Failed to remove temp voice file: %s", voice_path)


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
    return base + "\n\n" + "\n".join(build_memory_help_lines())


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
        selected_engine = StateRepository(state).get_chat_engine(scope_key)
        lines.append(f"This chat has Codex thread: {has_thread}")
        lines.append(f"This chat has worker session: {has_worker}")
        lines.append(f"This chat engine: {selected_engine or getattr(config, 'engine_plugin', 'codex')}")
        memory_engine = state.memory_engine
        if isinstance(memory_engine, MemoryEngine):
            memory_channel = getattr(config, "channel_plugin", "telegram")
            try:
                memory_status = memory_engine.get_status(
                    resolve_memory_conversation_key(config, memory_channel, scope_key)
                )
            except Exception:
                logging.exception("Failed to query memory status for scope_key=%s", scope_key)
            else:
                lines.append(f"Memory mode: {memory_status.mode}")
                lines.append(f"Memory facts: {memory_status.active_fact_count}")
                lines.append(f"Memory summaries: {memory_status.summary_count}")
                lines.append(f"Memory messages: {memory_status.message_count}")
                lines.append(f"Memory session active: {memory_status.session_active}")

    return "\n".join(lines)


def _prepare_prompt_input_request(
    request: PromptRequest,
    progress: ProgressReporter,
) -> Optional[PreparedPromptInput]:
    return prompt_preparation.prepare_prompt_input_request(
        request,
        progress,
        transcribe_voice_for_chat_fn=transcribe_voice_for_chat,
        strip_required_prefix_fn=strip_required_prefix,
        is_whatsapp_channel_fn=is_whatsapp_channel,
        send_input_too_long_fn=send_input_too_long,
        emit_event_fn=emit_event,
        prefix_help_message=PREFIX_HELP_MESSAGE,
    )


def prepare_prompt_input(
    state: State,
    config,
    client: ChannelAdapter,
    chat_id: int,
    message_id: Optional[int],
    prompt: str,
    photo_file_id: Optional[str],
    voice_file_id: Optional[str],
    document: Optional[DocumentPayload],
    progress: ProgressReporter,
    photo_file_ids: Optional[List[str]] = None,
    enforce_voice_prefix_from_transcript: bool = False,
) -> Optional[PreparedPromptInput]:
    return _prepare_prompt_input_request(
        build_prompt_request(
            state=state,
            config=config,
            client=client,
            engine=None,
            scope_key="",
            chat_id=chat_id,
            message_thread_id=None,
            message_id=message_id,
            prompt=prompt,
            photo_file_id=photo_file_id,
            voice_file_id=voice_file_id,
            document=document,
            photo_file_ids=photo_file_ids,
            enforce_voice_prefix_from_transcript=enforce_voice_prefix_from_transcript,
        ),
        progress,
    )


def prewarm_attachment_archive_for_message(
    state: State,
    config,
    client: ChannelAdapter,
    chat_id: int,
    message: Dict[str, object],
) -> None:
    prompt_preparation.prewarm_attachment_archive_for_message(
        state,
        config,
        client,
        chat_id,
        message,
        extract_message_photo_file_ids_fn=extract_message_photo_file_ids,
        extract_message_media_payload_fn=extract_message_media_payload,
        download_photo_to_temp_fn=download_photo_to_temp,
        download_document_to_temp_fn=download_document_to_temp,
        archive_media_path_fn=archive_media_path,
    )


def execute_prompt_with_retry(
    state_repo: StateRepository,
    config,
    client: ChannelAdapter,
    engine: EngineAdapter,
    chat_id: int,
    prompt_text: str,
    previous_thread_id: Optional[str],
    progress: ProgressReporter,
    message_thread_id: Optional[int] = None,
    message_id: Optional[int] = None,
    scope_key: Optional[str] = None,
    image_path: Optional[str] = None,
    image_paths: Optional[List[str]] = None,
    actor_user_id: Optional[int] = None,
    cancel_event: Optional[threading.Event] = None,
    session_continuity_enabled: bool = True,
) -> Optional[subprocess.CompletedProcess[str]]:
    if scope_key is None:
        scope_key = build_telegram_scope_key(chat_id, message_thread_id=message_thread_id)
    allow_automatic_retry = config.persistent_workers_enabled
    retry_attempted = False
    attempt_thread_id: Optional[str] = previous_thread_id
    attempt = 0
    normalized_image_paths = list(image_paths or [])
    if image_path and image_path not in normalized_image_paths:
        normalized_image_paths.insert(0, image_path)

    while True:
        if cancel_event is not None and cancel_event.is_set():
            emit_event(
                "bridge.request_cancelled",
                fields={
                    "chat_id": chat_id,
                    "message_id": message_id,
                    "phase": "before_executor_attempt",
                    "attempt": attempt + 1,
                },
            )
            progress.mark_failure("Execution canceled.")
            send_canceled_response(client, chat_id, message_id, message_thread_id)
            return None

        attempt += 1
        emit_event(
            "bridge.executor_attempt",
            fields={
                "chat_id": chat_id,
                "message_id": message_id,
                "attempt": attempt,
                "resume_mode": bool(attempt_thread_id),
                "automatic_retry_enabled": allow_automatic_retry,
            },
        )
        engine_started_at = time.monotonic()
        try:
            try:
                result = engine.run(
                    config=config,
                    prompt=prompt_text,
                    thread_id=attempt_thread_id,
                    session_key=scope_key,
                    channel_name=getattr(client, "channel_name", "telegram"),
                    actor_chat_id=chat_id,
                    actor_user_id=actor_user_id,
                    image_paths=normalized_image_paths,
                    progress_callback=progress.handle_executor_event,
                    cancel_event=cancel_event,
                )
                emit_phase_timing(
                    chat_id=chat_id,
                    message_id=message_id,
                    phase="engine_run",
                    started_at_monotonic=engine_started_at,
                    attempt=attempt,
                    success=True,
                    returncode=result.returncode,
                )
            except TypeError as exc:
                exc_text = str(exc)
                if not any(
                    token in exc_text
                    for token in (
                        "unexpected keyword argument 'session_key'",
                        "unexpected keyword argument 'channel_name'",
                        "unexpected keyword argument 'actor_chat_id'",
                        "unexpected keyword argument 'actor_user_id'",
                        "unexpected keyword argument 'image_paths'",
                    )
                ):
                    raise
                result = engine.run(
                    config=config,
                    prompt=prompt_text,
                    thread_id=attempt_thread_id,
                    image_path=normalized_image_paths[0] if normalized_image_paths else None,
                    progress_callback=progress.handle_executor_event,
                    cancel_event=cancel_event,
                )
                emit_phase_timing(
                    chat_id=chat_id,
                    message_id=message_id,
                    phase="engine_run",
                    started_at_monotonic=engine_started_at,
                    attempt=attempt,
                    success=True,
                    returncode=result.returncode,
                    fallback_signature=True,
                )
        except ExecutorCancelledError:
            emit_phase_timing(
                chat_id=chat_id,
                message_id=message_id,
                phase="engine_run",
                started_at_monotonic=engine_started_at,
                attempt=attempt,
                success=False,
                error_type="ExecutorCancelledError",
            )
            logging.info("Executor canceled for chat_id=%s", chat_id)
            emit_event(
                "bridge.request_cancelled",
                fields={"chat_id": chat_id, "message_id": message_id, "attempt": attempt},
            )
            progress.mark_failure("Execution canceled.")
            send_canceled_response(client, chat_id, message_id, message_thread_id)
            return None
        except subprocess.TimeoutExpired:
            emit_phase_timing(
                chat_id=chat_id,
                message_id=message_id,
                phase="engine_run",
                started_at_monotonic=engine_started_at,
                attempt=attempt,
                success=False,
                error_type="TimeoutExpired",
            )
            logging.warning("Executor timeout for chat_id=%s", chat_id)
            emit_event(
                "bridge.request_timeout",
                level=logging.WARNING,
                fields={"chat_id": chat_id, "message_id": message_id, "attempt": attempt},
            )
            progress.mark_failure("Execution timed out.")
            client.send_message(
                chat_id,
                config.timeout_message,
                reply_to_message_id=message_id,
                message_thread_id=message_thread_id,
            )
            return None
        except FileNotFoundError:
            emit_phase_timing(
                chat_id=chat_id,
                message_id=message_id,
                phase="engine_run",
                started_at_monotonic=engine_started_at,
                attempt=attempt,
                success=False,
                error_type="FileNotFoundError",
            )
            logging.exception("Executor command not found: %s", config.executor_cmd)
            emit_event(
                "bridge.executor_missing",
                level=logging.ERROR,
                fields={"chat_id": chat_id, "message_id": message_id},
            )
            progress.mark_failure("Executor command not found.")
            client.send_message(
                chat_id,
                config.generic_error_message,
                reply_to_message_id=message_id,
                message_thread_id=message_thread_id,
            )
            return None
        except Exception:
            emit_phase_timing(
                chat_id=chat_id,
                message_id=message_id,
                phase="engine_run",
                started_at_monotonic=engine_started_at,
                attempt=attempt,
                success=False,
                error_type="Exception",
            )
            logging.exception("Unexpected executor error for chat_id=%s", chat_id)
            emit_event(
                "bridge.executor_exception",
                level=logging.WARNING,
                fields={"chat_id": chat_id, "message_id": message_id, "attempt": attempt},
            )
            if allow_automatic_retry and not retry_attempted:
                retry_attempted = True
                if session_continuity_enabled:
                    state_repo.clear_thread_id(scope_key)
                attempt_thread_id = None
                progress.set_phase(RETRY_WITH_NEW_SESSION_PHASE)
                emit_event(
                    "bridge.request_retry_scheduled",
                    level=logging.WARNING,
                    fields={
                        "chat_id": chat_id,
                        "message_id": message_id,
                        "attempt": attempt,
                        "reason": "executor_exception",
                    },
                )
                continue
            progress.mark_failure("Execution failed before completion.")
            send_executor_failure_message(
                client=client,
                config=config,
                chat_id=chat_id,
                message_id=message_id,
                allow_automatic_retry=allow_automatic_retry,
                message_thread_id=message_thread_id,
            )
            return None

        if result.returncode == 0:
            emit_event(
                "bridge.executor_completed",
                fields={
                    "chat_id": chat_id,
                    "message_id": message_id,
                    "attempt": attempt,
                },
            )
            return result

        reset_and_retry_new = False
        failure_message = extract_executor_failure_message(result.stdout or "", result.stderr or "")
        if attempt_thread_id and should_reset_thread_after_resume_failure(
            result.stderr or "",
            result.stdout or "",
        ):
            logging.warning(
                "Executor failed for chat_id=%s on resume due to invalid thread; "
                "clearing thread and retrying as new. stderr=%r",
                chat_id,
                (result.stderr or "")[-1000:],
            )
            reset_and_retry_new = True
            progress.set_phase(resume_retry_phase(config))
            emit_event(
                "bridge.request_retry_scheduled",
                level=logging.WARNING,
                fields={
                    "chat_id": chat_id,
                    "message_id": message_id,
                    "attempt": attempt,
                    "reason": "invalid_resume_thread",
                },
            )
        elif failure_message:
            logging.warning(
                "Executor failed for chat_id=%s with surfaced failure=%r",
                chat_id,
                failure_message,
            )
        elif allow_automatic_retry and not retry_attempted:
            logging.warning(
                "Executor failed for chat_id=%s; retrying once as new. returncode=%s stderr=%r",
                chat_id,
                result.returncode,
                (result.stderr or "")[-1000:],
            )
            reset_and_retry_new = True
            retry_attempted = True
            progress.set_phase(RETRY_WITH_NEW_SESSION_PHASE)
            emit_event(
                "bridge.request_retry_scheduled",
                level=logging.WARNING,
                fields={
                    "chat_id": chat_id,
                    "message_id": message_id,
                    "attempt": attempt,
                    "reason": "nonzero_exit",
                    "returncode": result.returncode,
                },
            )

        if reset_and_retry_new:
            if session_continuity_enabled:
                state_repo.clear_thread_id(scope_key)
            attempt_thread_id = None
            retry_attempted = True
            continue

        logging.error(
            "Executor failed for chat_id=%s returncode=%s stderr=%r",
            chat_id,
            result.returncode,
            (result.stderr or "")[-1000:],
        )
        emit_event(
            "bridge.request_failed",
            level=logging.WARNING,
            fields={
                "chat_id": chat_id,
                "message_id": message_id,
                "attempt": attempt,
                "returncode": result.returncode,
            },
        )
        progress.mark_failure("Execution failed.")
        send_executor_failure_message(
            client=client,
            config=config,
            chat_id=chat_id,
            message_id=message_id,
            allow_automatic_retry=allow_automatic_retry,
            failure_message=failure_message,
            message_thread_id=message_thread_id,
        )
        return None


def finalize_prompt_success(
    state_repo: StateRepository,
    config,
    client: ChannelAdapter,
    chat_id: int,
    message_id: Optional[int],
    result: subprocess.CompletedProcess[str],
    progress: ProgressReporter,
    scope_key: Optional[str] = None,
    message_thread_id: Optional[int] = None,
) -> tuple[Optional[str], str]:
    if scope_key is None:
        scope_key = build_telegram_scope_key(chat_id, message_thread_id=message_thread_id)
    new_thread_id, output = parse_executor_output(result.stdout or "")
    if new_thread_id:
        state_repo.set_thread_id(scope_key, new_thread_id)
    if not output:
        output = config.empty_output_message
    if not output_contains_control_directive(output):
        output = trim_output(output, config.max_output_chars)
    progress.mark_success()
    delivered_output = deliver_output_and_emit_success(
        client=client,
        chat_id=chat_id,
        message_id=message_id,
        output=output,
        message_thread_id=message_thread_id,
        new_thread_id=bool(new_thread_id),
    )
    return new_thread_id, delivered_output


def deliver_output_and_emit_success(
    client: ChannelAdapter,
    chat_id: int,
    message_id: Optional[int],
    output: str,
    message_thread_id: Optional[int] = None,
    new_thread_id: bool = False,
) -> str:
    delivered_output = send_executor_output(
        client=client,
        chat_id=chat_id,
        message_id=message_id,
        output=output,
        message_thread_id=message_thread_id,
    )
    emit_event(
        "bridge.request_succeeded",
        fields={
            "chat_id": chat_id,
            "message_id": message_id,
            "new_thread_id": bool(new_thread_id),
            "output_chars": len(delivered_output),
        },
    )
    return delivered_output


def begin_memory_turn(
    memory_engine: Optional[MemoryEngine],
    state_repo: StateRepository,
    config,
    channel_name: str,
    scope_key: str,
    prompt_text: str,
    sender_name: str,
    stateless: bool,
    chat_id: int,
) -> tuple[str, Optional[str], Optional[TurnContext]]:
    return prompt_execution.begin_memory_turn(
        memory_engine,
        state_repo,
        config,
        channel_name,
        scope_key,
        prompt_text,
        sender_name,
        stateless,
        chat_id,
        resolve_memory_conversation_key_fn=resolve_memory_conversation_key,
        resolve_shared_memory_archive_key_fn=resolve_shared_memory_archive_key,
    )


def begin_affective_turn(
    affective_runtime,
    prompt_text: str,
    *,
    chat_id: int,
    message_id: Optional[int],
) -> tuple[str, bool]:
    return prompt_execution.begin_affective_turn(
        affective_runtime,
        prompt_text,
        chat_id=chat_id,
        message_id=message_id,
        emit_event_fn=emit_event,
    )


def emit_request_processing_started(
    *,
    chat_id: int,
    message_id: Optional[int],
    prompt: str,
    photo_file_ids: Optional[List[str]],
    photo_file_id: Optional[str],
    voice_file_id: Optional[str],
    document: Optional[DocumentPayload],
    previous_thread_id: Optional[str],
) -> None:
    prompt_execution.emit_request_processing_started(
        chat_id=chat_id,
        message_id=message_id,
        prompt=prompt,
        photo_file_ids=photo_file_ids,
        photo_file_id=photo_file_id,
        voice_file_id=voice_file_id,
        document=document,
        previous_thread_id=previous_thread_id,
        emit_event_fn=emit_event,
    )


def emit_phase_timing(
    *,
    chat_id: int,
    message_id: Optional[int],
    phase: str,
    started_at_monotonic: float,
    **extra_fields,
) -> None:
    prompt_execution.emit_phase_timing(
        chat_id=chat_id,
        message_id=message_id,
        phase=phase,
        started_at_monotonic=started_at_monotonic,
        emit_event_fn=emit_event,
        **extra_fields,
    )


def build_progress_reporter(
    client: ChannelAdapter,
    config,
    chat_id: int,
    message_id: Optional[int],
    message_thread_id: Optional[int],
    progress_context_label: str,
) -> ProgressReporter:
    return prompt_execution.build_progress_reporter(
        client,
        config,
        chat_id,
        message_id,
        message_thread_id,
        progress_context_label,
        progress_reporter_cls=ProgressReporter,
        assistant_label_fn=assistant_label,
    )


def _build_prompt_progress_reporter(
    request: PromptRequest,
    active_engine: EngineAdapter,
) -> ProgressReporter:
    return prompt_execution.build_prompt_progress_reporter(
        request,
        active_engine,
        build_engine_runtime_config_fn=build_engine_runtime_config,
        build_engine_progress_context_label_fn=build_engine_progress_context_label,
        progress_reporter_cls=ProgressReporter,
        assistant_label_fn=assistant_label,
    )


def _process_prompt_request(request: PromptRequest) -> None:
    prompt_execution.process_prompt_request(
        request,
        progress_reporter_cls=ProgressReporter,
        state_repository_cls=StateRepository,
        codex_engine_adapter_factory=CodexEngineAdapter,
        memory_engine_cls=MemoryEngine,
        assistant_label_fn=assistant_label,
        build_engine_runtime_config_fn=build_engine_runtime_config,
        build_engine_progress_context_label_fn=build_engine_progress_context_label,
        refresh_runtime_auth_fingerprint_fn=refresh_runtime_auth_fingerprint,
        prepare_prompt_input_request_fn=_prepare_prompt_input_request,
        execute_prompt_with_retry_fn=execute_prompt_with_retry,
        finalize_prompt_success_fn=finalize_prompt_success,
        finalize_request_progress_fn=finalize_request_progress,
        emit_event_fn=emit_event,
        resolve_memory_conversation_key_fn=resolve_memory_conversation_key,
        resolve_shared_memory_archive_key_fn=resolve_shared_memory_archive_key,
    )


def process_prompt(
    state: State,
    config,
    client: ChannelAdapter,
    engine: Optional[EngineAdapter],
    scope_key: str,
    chat_id: int,
    message_thread_id: Optional[int],
    message_id: Optional[int],
    prompt: str,
    photo_file_id: Optional[str],
    voice_file_id: Optional[str],
    document: Optional[DocumentPayload],
    cancel_event: Optional[threading.Event] = None,
    stateless: bool = False,
    sender_name: str = "Telegram User",
    photo_file_ids: Optional[List[str]] = None,
    actor_user_id: Optional[int] = None,
    enforce_voice_prefix_from_transcript: bool = False,
) -> None:
    _process_prompt_request(
        build_prompt_request(
            state=state,
            config=config,
            client=client,
            engine=engine,
            scope_key=scope_key,
            chat_id=chat_id,
            message_thread_id=message_thread_id,
            message_id=message_id,
            prompt=prompt,
            photo_file_id=photo_file_id,
            voice_file_id=voice_file_id,
            document=document,
            cancel_event=cancel_event,
            stateless=stateless,
            sender_name=sender_name,
            photo_file_ids=photo_file_ids,
            actor_user_id=actor_user_id,
            enforce_voice_prefix_from_transcript=enforce_voice_prefix_from_transcript,
        )
    )


def _process_message_worker_request(request: PromptRequest) -> None:
    try:
        _process_prompt_request(request)
    except Exception:
        emit_worker_exception_and_reply(
            log_message="Unexpected message worker error for chat_id=%s",
            failure_log_message="Failed to send worker error response for chat_id=%s",
            event_fields={"chat_id": request.chat_id, "message_id": request.message_id},
            client=request.client,
            config=request.config,
            chat_id=request.chat_id,
            message_id=request.message_id,
            message_thread_id=request.message_thread_id,
        )


def process_message_worker(
    state: State,
    config,
    client: ChannelAdapter,
    engine: Optional[EngineAdapter],
    scope_key: str,
    chat_id: int,
    message_thread_id: Optional[int],
    message_id: Optional[int],
    prompt: str,
    photo_file_id: Optional[str],
    voice_file_id: Optional[str],
    document: Optional[DocumentPayload],
    cancel_event: Optional[threading.Event] = None,
    stateless: bool = False,
    sender_name: str = "Telegram User",
    photo_file_ids: Optional[List[str]] = None,
    actor_user_id: Optional[int] = None,
    enforce_voice_prefix_from_transcript: bool = False,
) -> None:
    _process_message_worker_request(
        build_prompt_request(
            state=state,
            config=config,
            client=client,
            engine=engine,
            scope_key=scope_key,
            chat_id=chat_id,
            message_thread_id=message_thread_id,
            message_id=message_id,
            prompt=prompt,
            photo_file_id=photo_file_id,
            voice_file_id=voice_file_id,
            document=document,
            cancel_event=cancel_event,
            stateless=stateless,
            sender_name=sender_name,
            photo_file_ids=photo_file_ids,
            actor_user_id=actor_user_id,
            enforce_voice_prefix_from_transcript=enforce_voice_prefix_from_transcript,
        )
    )


def _process_youtube_request(request: YoutubeRequest) -> None:
    special_request_processing.process_youtube_request(
        request,
        build_progress_reporter_fn=build_progress_reporter,
        build_engine_progress_context_label_fn=build_engine_progress_context_label,
        state_repository_cls=StateRepository,
        codex_engine_adapter_factory=CodexEngineAdapter,
        send_canceled_response_fn=send_canceled_response,
        run_youtube_analyzer_fn=run_youtube_analyzer,
        build_youtube_transcript_output_fn=build_youtube_transcript_output,
        deliver_output_and_emit_success_fn=deliver_output_and_emit_success,
        build_youtube_unavailable_message_fn=build_youtube_unavailable_message,
        execute_prompt_with_retry_fn=execute_prompt_with_retry,
        build_youtube_summary_prompt_fn=build_youtube_summary_prompt,
        finalize_prompt_success_fn=finalize_prompt_success,
        finalize_request_progress_fn=finalize_request_progress,
    )


def process_youtube_request(
    state: State,
    config,
    client: ChannelAdapter,
    engine: Optional[EngineAdapter],
    chat_id: int,
    request_text: str,
    youtube_url: str,
    message_thread_id: Optional[int] = None,
    message_id: Optional[int] = None,
    scope_key: Optional[str] = None,
    actor_user_id: Optional[int] = None,
    cancel_event: Optional[threading.Event] = None,
) -> None:
    if scope_key is None:
        scope_key = build_telegram_scope_key(chat_id, message_thread_id=message_thread_id)
    _process_youtube_request(
        build_youtube_request(
            state=state,
            config=config,
            client=client,
            engine=engine,
            scope_key=scope_key,
            chat_id=chat_id,
            message_thread_id=message_thread_id,
            message_id=message_id,
            request_text=request_text,
            youtube_url=youtube_url,
            actor_user_id=actor_user_id,
            cancel_event=cancel_event,
        )
    )


def _process_youtube_worker_request(request: YoutubeRequest) -> None:
    special_request_processing.process_youtube_worker_request(
        request,
        process_youtube_request_fn=_process_youtube_request,
        emit_event_fn=emit_event,
        send_timeout_response_fn=send_timeout_response,
        emit_worker_exception_and_reply_fn=emit_worker_exception_and_reply,
    )


def process_youtube_worker(
    state: State,
    config,
    client: ChannelAdapter,
    engine: Optional[EngineAdapter],
    scope_key: str,
    chat_id: int,
    message_thread_id: Optional[int],
    message_id: Optional[int],
    request_text: str,
    youtube_url: str,
    actor_user_id: Optional[int] = None,
    cancel_event: Optional[threading.Event] = None,
) -> None:
    _process_youtube_worker_request(
        build_youtube_request(
            state=state,
            config=config,
            client=client,
            engine=engine,
            scope_key=scope_key,
            chat_id=chat_id,
            message_thread_id=message_thread_id,
            message_id=message_id,
            request_text=request_text,
            youtube_url=youtube_url,
            actor_user_id=actor_user_id,
            cancel_event=cancel_event,
        )
    )


def start_youtube_worker(
    state: State,
    config,
    client: ChannelAdapter,
    engine: Optional[EngineAdapter],
    scope_key: str,
    chat_id: int,
    message_thread_id: Optional[int],
    message_id: Optional[int],
    request_text: str,
    youtube_url: str,
    actor_user_id: Optional[int] = None,
    cancel_event: Optional[threading.Event] = None,
) -> None:
    start_background_worker(
        _process_youtube_worker_request,
        build_youtube_request(
            state=state,
            config=config,
            client=client,
            engine=engine,
            scope_key=scope_key,
            chat_id=chat_id,
            message_thread_id=message_thread_id,
            message_id=message_id,
            request_text=request_text,
            youtube_url=youtube_url,
            actor_user_id=actor_user_id,
            cancel_event=cancel_event,
        ),
    )


def _process_dishframed_request(request: DishframedRequest) -> None:
    special_request_processing.process_dishframed_request(
        request,
        build_progress_reporter_fn=build_progress_reporter,
        prepare_prompt_input_fn=prepare_prompt_input,
        dishframed_usage_message=DISHFRAMED_USAGE_MESSAGE,
        run_dishframed_cli_fn=run_dishframed_cli,
        telegram_caption_limit=TELEGRAM_CAPTION_LIMIT,
        infer_media_kind_fn=infer_media_kind,
        send_chat_action_safe_fn=send_chat_action_safe,
        finalize_request_progress_fn=finalize_request_progress,
    )


def process_dishframed_request(
    state: State,
    config,
    client: ChannelAdapter,
    scope_key: str,
    chat_id: int,
    message_thread_id: Optional[int],
    message_id: Optional[int],
    photo_file_ids: List[str],
    cancel_event: Optional[threading.Event] = None,
) -> None:
    _process_dishframed_request(
        build_dishframed_request(
            state=state,
            config=config,
            client=client,
            scope_key=scope_key,
            chat_id=chat_id,
            message_thread_id=message_thread_id,
            message_id=message_id,
            photo_file_ids=photo_file_ids,
            cancel_event=cancel_event,
        )
    )


def _process_dishframed_worker_request(request: DishframedRequest) -> None:
    special_request_processing.process_dishframed_worker_request(
        request,
        process_dishframed_request_fn=_process_dishframed_request,
        send_timeout_response_fn=send_timeout_response,
        send_canceled_response_fn=send_canceled_response,
        emit_worker_exception_and_reply_fn=emit_worker_exception_and_reply,
    )


def process_dishframed_worker(
    state: State,
    config,
    client: ChannelAdapter,
    scope_key: str,
    chat_id: int,
    message_thread_id: Optional[int],
    message_id: Optional[int],
    photo_file_ids: List[str],
    cancel_event: Optional[threading.Event] = None,
) -> None:
    _process_dishframed_worker_request(
        build_dishframed_request(
            state=state,
            config=config,
            client=client,
            scope_key=scope_key,
            chat_id=chat_id,
            message_thread_id=message_thread_id,
            message_id=message_id,
            photo_file_ids=photo_file_ids,
            cancel_event=cancel_event,
        )
    )


def start_dishframed_worker(
    state: State,
    config,
    client: ChannelAdapter,
    scope_key: str,
    chat_id: int,
    message_thread_id: Optional[int],
    message_id: Optional[int],
    photo_file_ids: List[str],
    cancel_event: Optional[threading.Event] = None,
) -> None:
    start_background_worker(
        _process_dishframed_worker_request,
        build_dishframed_request(
            state=state,
            config=config,
            client=client,
            scope_key=scope_key,
            chat_id=chat_id,
            message_thread_id=message_thread_id,
            message_id=message_id,
            photo_file_ids=photo_file_ids,
            cancel_event=cancel_event,
        ),
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
    state_repo = StateRepository(state)
    removed_thread = state_repo.clear_thread_id(scope_key)
    removed_worker = state_repo.clear_worker_session(scope_key) if config.persistent_workers_enabled else False
    memory_engine = state.memory_engine if isinstance(state.memory_engine, MemoryEngine) else None
    if memory_engine is not None:
        memory_channel = getattr(client, "channel_name", "telegram")
        conversation_key = resolve_memory_conversation_key(config, memory_channel, scope_key)
        shared_archive_key = resolve_shared_memory_archive_key(config, memory_channel)
        try:
            if shared_archive_key and shared_archive_key != conversation_key:
                merge_conversation_keys(
                    db_path=memory_engine.db_path,
                    source_keys=[conversation_key],
                    target_key=shared_archive_key,
                    allow_existing_target=True,
                    force_summarize_target=True,
                    min_message_score=0.75,
                )
                memory_engine.compact_summarized_messages(shared_archive_key)
            memory_engine.clear_session(conversation_key)
        except Exception:
            logging.exception("Failed to clear shared memory session for scope=%s", scope_key)
    if removed_thread or removed_worker:
        client.send_message(
            chat_id,
            "Context reset. Your next message starts a new conversation.",
            reply_to_message_id=message_id,
            message_thread_id=message_thread_id,
        )
        return
    client.send_message(
        chat_id,
        "No saved context was found for this chat.",
        reply_to_message_id=message_id,
        message_thread_id=message_thread_id,
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
        client.send_message(
            chat_id,
            "Restart is already in progress.",
            reply_to_message_id=message_id,
            message_thread_id=message_thread_id,
        )
        return
    if status == "already_queued":
        client.send_message(
            chat_id,
            "Restart is already queued and will run after current work completes.",
            reply_to_message_id=message_id,
            message_thread_id=message_thread_id,
        )
        return
    if status == "queued":
        client.send_message(
            chat_id,
            f"Safe restart queued. Waiting for {busy_count} active request(s) to finish.",
            reply_to_message_id=message_id,
            message_thread_id=message_thread_id,
        )
        return

    client.send_message(
        chat_id,
        "No active request. Restarting bridge now.",
        reply_to_message_id=message_id,
        message_thread_id=message_thread_id,
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
        client.send_message(
            chat_id,
            CANCEL_REQUESTED_MESSAGE,
            reply_to_message_id=message_id,
            message_thread_id=message_thread_id,
        )
        return
    if status == "already_requested":
        client.send_message(
            chat_id,
            CANCEL_ALREADY_REQUESTED_MESSAGE,
            reply_to_message_id=message_id,
            message_thread_id=message_thread_id,
        )
        return
    if status == "unavailable":
        client.send_message(
            chat_id,
            "Active request cannot be canceled at this stage. Please wait a few seconds and retry.",
            reply_to_message_id=message_id,
            message_thread_id=message_thread_id,
        )
        return
    client.send_message(
        chat_id,
        CANCEL_NO_ACTIVE_MESSAGE,
        reply_to_message_id=message_id,
        message_thread_id=message_thread_id,
    )


ENGINE_NAME_ALIASES = {
    "chatgpt_web": "chatgptweb",
}

PI_PROVIDER_ALIASES = {
    "ollama_ssh": "ollama",
    "ssh": "ollama",
}

normalize_engine_name = engine_controls.normalize_engine_name
configured_default_engine = engine_controls.configured_default_engine
selectable_engine_plugins = engine_controls.selectable_engine_plugins
configured_pi_provider = engine_controls.configured_pi_provider
normalize_pi_provider_name = engine_controls.normalize_pi_provider_name
configured_pi_model = engine_controls.configured_pi_model
pi_provider_uses_ollama_tunnel = engine_controls.pi_provider_uses_ollama_tunnel
configured_codex_model = engine_controls.configured_codex_model
configured_codex_reasoning_effort = engine_controls.configured_codex_reasoning_effort
build_engine_runtime_config = engine_controls.build_engine_runtime_config
build_pi_providers_text = engine_controls.build_pi_providers_text
build_pi_models_text = engine_controls.build_pi_models_text
build_pi_status_text = engine_controls.build_pi_status_text
check_gemma_health = engine_controls.check_gemma_health
check_venice_health = engine_controls.check_venice_health
check_pi_health = engine_controls.check_pi_health
check_chatgpt_web_health = engine_controls.check_chatgpt_web_health
build_engine_status_text = engine_controls.build_engine_status_text
_build_engine_picker_markup = engine_controls._build_engine_picker_markup
_set_engine_for_scope = engine_controls._set_engine_for_scope
_reset_engine_for_scope = engine_controls._reset_engine_for_scope
handle_engine_command = engine_controls.handle_engine_command
handle_pi_command = engine_controls.handle_pi_command
_model_active_engine_name = engine_controls._model_active_engine_name
_load_codex_model_catalog = engine_controls._load_codex_model_catalog
_load_codex_model_choices = engine_controls._load_codex_model_choices
_pi_available_provider_names = engine_controls._pi_available_provider_names
_pi_provider_model_names = engine_controls._pi_provider_model_names
_brief_health_error = engine_controls._brief_health_error
_build_model_picker_markup = engine_controls._build_model_picker_markup
_build_provider_picker_markup = engine_controls._build_provider_picker_markup
_build_effort_picker_markup = engine_controls._build_effort_picker_markup
build_model_status_text = engine_controls.build_model_status_text
build_effort_status_text = engine_controls.build_effort_status_text
build_effort_list_text = engine_controls.build_effort_list_text
build_model_list_text = engine_controls.build_model_list_text
_set_codex_model_for_scope = engine_controls._set_codex_model_for_scope
_reset_model_for_scope = engine_controls._reset_model_for_scope
_set_pi_provider_for_scope = engine_controls._set_pi_provider_for_scope
_set_pi_model_for_scope = engine_controls._set_pi_model_for_scope
_set_codex_effort_for_scope = engine_controls._set_codex_effort_for_scope
_reset_codex_effort_for_scope = engine_controls._reset_codex_effort_for_scope
_parse_page_index = engine_controls._parse_page_index
handle_model_command = engine_controls.handle_model_command
handle_effort_command = engine_controls.handle_effort_command


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


def build_voice_alias_help_text() -> str:
    return (
        "Voice alias learning commands:\n"
        "/voice-alias list - show pending learned corrections\n"
        "/voice-alias approve <id> - approve one suggestion\n"
        "/voice-alias reject <id> - reject one suggestion\n"
        "/voice-alias add <source> => <target> - add approved alias manually"
    )


def parse_voice_alias_suggestion_id(tail: str, action: str) -> Optional[int]:
    prefix = f"{action} "
    if not tail.lower().startswith(prefix):
        return None
    value = tail[len(prefix):].strip()
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def handle_voice_alias_command(
    state: State,
    config,
    client: ChannelAdapter,
    chat_id: int,
    message_id: Optional[int],
    raw_text: str,
) -> bool:
    learning_store = getattr(state, "voice_alias_learning_store", None)
    if learning_store is None:
        client.send_message(
            chat_id,
            "Voice alias learning is disabled.",
            reply_to_message_id=message_id,
        )
        return True

    pieces = raw_text.strip().split(maxsplit=1)
    tail = pieces[1].strip() if len(pieces) > 1 else ""
    if not tail or tail.lower() == "help":
        client.send_message(
            chat_id,
            build_voice_alias_help_text(),
            reply_to_message_id=message_id,
        )
        return True

    if tail.lower() == "list":
        pending = learning_store.list_pending()
        if not pending:
            client.send_message(
                chat_id,
                "No pending learned voice alias suggestions.",
                reply_to_message_id=message_id,
            )
            return True
        lines = ["Pending voice alias suggestions:"]
        for suggestion in pending:
            lines.append(
                f"- #{suggestion.suggestion_id}: `{suggestion.source}` => `{suggestion.target}` (seen {suggestion.count}x)"
            )
        lines.append("Approve with: `/voice-alias approve <id>`")
        lines.append("Reject with: `/voice-alias reject <id>`")
        client.send_message(chat_id, "\n".join(lines), reply_to_message_id=message_id)
        return True

    approve_id = parse_voice_alias_suggestion_id(tail, "approve")
    if approve_id is not None:
        approved = learning_store.approve(approve_id)
        if approved is None:
            client.send_message(
                chat_id,
                f"No pending suggestion with id {approve_id}.",
                reply_to_message_id=message_id,
            )
            return True
        client.send_message(
            chat_id,
            f"Approved voice alias #{approve_id}: `{approved.source}` => `{approved.target}`",
            reply_to_message_id=message_id,
        )
        return True

    reject_id = parse_voice_alias_suggestion_id(tail, "reject")
    if reject_id is not None:
        rejected = learning_store.reject(reject_id)
        if rejected is None:
            client.send_message(
                chat_id,
                f"No pending suggestion with id {reject_id}.",
                reply_to_message_id=message_id,
            )
            return True
        client.send_message(
            chat_id,
            f"Rejected voice alias #{reject_id}: `{rejected.source}` => `{rejected.target}`",
            reply_to_message_id=message_id,
        )
        return True

    if tail.lower().startswith("add "):
        payload = tail[4:].strip()
        if "=>" not in payload:
            client.send_message(
                chat_id,
                "Usage: /voice-alias add <source> => <target>",
                reply_to_message_id=message_id,
            )
            return True
        source, target = payload.split("=>", 1)
        source = source.strip()
        target = target.strip()
        if not source or not target:
            client.send_message(
                chat_id,
                "Usage: /voice-alias add <source> => <target>",
                reply_to_message_id=message_id,
            )
            return True
        try:
            added_source, added_target = learning_store.add_manual(source, target)
        except ValueError:
            client.send_message(
                chat_id,
                "Usage: /voice-alias add <source> => <target>",
                reply_to_message_id=message_id,
            )
            return True
        client.send_message(
            chat_id,
            f"Added manual voice alias: `{added_source}` => `{added_target}`",
            reply_to_message_id=message_id,
        )
        return True

    client.send_message(
        chat_id,
        build_voice_alias_help_text(),
        reply_to_message_id=message_id,
    )
    return True


def maybe_process_voice_alias_learning_confirmation(
    state: State,
    config,
    client: ChannelAdapter,
    chat_id: int,
    message_id: Optional[int],
    prompt_input: str,
    command: Optional[str],
    priority_keyword_mode: bool,
    photo_file_id: Optional[str],
    voice_file_id: Optional[str],
    document: Optional[DocumentPayload],
    photo_file_ids: Optional[List[str]] = None,
) -> None:
    if not prompt_input.strip():
        return
    if command is not None:
        return
    if priority_keyword_mode:
        return
    if photo_file_id or photo_file_ids or voice_file_id or document is not None:
        return

    learning_store = getattr(state, "voice_alias_learning_store", None)
    if learning_store is None:
        return

    try:
        result = learning_store.consume_confirmation(
            chat_id=chat_id,
            confirmed_text=prompt_input,
            active_replacements=build_active_voice_alias_replacements(config, state),
        )
    except Exception:
        logging.exception("Failed to process voice alias learning confirmation")
        return

    if not result.suggestion_created:
        return

    message = build_voice_alias_suggestions_message(result.suggestion_created)
    if not message:
        return
    client.send_message(
        chat_id,
        message,
        reply_to_message_id=message_id,
    )


def start_message_worker(
    state: State,
    config,
    client: ChannelAdapter,
    engine: Optional[EngineAdapter],
    scope_key: str,
    chat_id: int,
    message_thread_id: Optional[int],
    message_id: Optional[int],
    prompt: str,
    photo_file_id: Optional[str],
    voice_file_id: Optional[str],
    document: Optional[DocumentPayload],
    cancel_event: Optional[threading.Event] = None,
    stateless: bool = False,
    sender_name: str = "Telegram User",
    photo_file_ids: Optional[List[str]] = None,
    actor_user_id: Optional[int] = None,
    enforce_voice_prefix_from_transcript: bool = False,
) -> None:
    request = build_prompt_request(
        state=state,
        config=config,
        client=client,
        engine=engine,
        scope_key=scope_key,
        chat_id=chat_id,
        message_thread_id=message_thread_id,
        message_id=message_id,
        prompt=prompt,
        photo_file_id=photo_file_id,
        voice_file_id=voice_file_id,
        document=document,
        cancel_event=cancel_event,
        stateless=stateless,
        sender_name=sender_name,
        photo_file_ids=photo_file_ids,
        actor_user_id=actor_user_id,
        enforce_voice_prefix_from_transcript=enforce_voice_prefix_from_transcript,
    )
    start_background_worker(_process_message_worker_request, request)


def handle_update(
    state: State,
    config,
    client: ChannelAdapter,
    update: Dict[str, object],
    engine: Optional[EngineAdapter] = None,
) -> None:
    handle_update_started_at = time.monotonic()
    if handle_callback_query(state, config, client, update):
        return
    ctx = extract_incoming_update_context(update)
    if ctx is None:
        return
    emit_event(
        "bridge.update_received",
        fields={
            "chat_id": ctx.chat_id,
            "message_id": ctx.message_id,
            "scope_key": ctx.scope_key,
            "update_id": ctx.update_id,
        },
    )

    if not allow_update_chat(ctx, config, client):
        return

    prepared = prepare_update_request(state, config, client, ctx)
    if prepared is None:
        return
    chat_id = ctx.chat_id
    message_id = ctx.message_id
    message_thread_id = ctx.message_thread_id
    scope_key = ctx.scope_key
    flow = build_update_flow_state(state, config, client, engine, prepared)

    if maybe_handle_diary_update_flow(flow):
        return
    dispatch_request = prepare_update_dispatch_request(flow, handle_update_started_at)
    if dispatch_request is None:
        return

    if flow.command == "/dishframed":
        start_dishframed_dispatch(dispatch_request)
        return
    start_standard_dispatch(dispatch_request)
    return
