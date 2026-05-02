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
        parse_executor_output,
        should_reset_thread_after_resume_failure,
    )
    from .handler_common import (
        ProgressReporter,
        RATE_LIMIT_MESSAGE,
        build_help_text,
        build_status_text,
        extract_callback_query_context,
        extract_chat_context,
        normalize_command,
        strip_required_prefix,
        trim_output,
    )
    from .channel_adapter import ChannelAdapter
    from .command_routing import handle_callback_query, handle_known_command
    from . import control_commands
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
    from . import prompt_inputs
    from . import prompt_runtime
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
    from . import request_starts
    from . import request_processing
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
    from . import voice_alias_commands
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
        parse_executor_output,
        should_reset_thread_after_resume_failure,
    )
    from handler_common import (
        ProgressReporter,
        RATE_LIMIT_MESSAGE,
        build_help_text,
        build_status_text,
        extract_callback_query_context,
        extract_chat_context,
        normalize_command,
        strip_required_prefix,
        trim_output,
    )
    from channel_adapter import ChannelAdapter
    from command_routing import handle_callback_query, handle_known_command
    import control_commands
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
    import prompt_inputs
    import prompt_runtime
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
    import request_starts
    import request_processing
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
    import voice_alias_commands

GEMMA_HEALTH_TIMEOUT_SECONDS = 6
GEMMA_HEALTH_CURL_TIMEOUT_SECONDS = 5
DISHFRAMED_REPO_ROOT = dishframed_processing.DISHFRAMED_REPO_ROOT
DISHFRAMED_PYTHON_BIN = dishframed_processing.DISHFRAMED_PYTHON_BIN
DISHFRAMED_USAGE_MESSAGE = dishframed_processing.DISHFRAMED_USAGE_MESSAGE

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
handle_reset_command = control_commands.handle_reset_command
handle_restart_command = control_commands.handle_restart_command
handle_cancel_command = control_commands.handle_cancel_command
build_voice_alias_help_text = voice_alias_commands.build_voice_alias_help_text
parse_voice_alias_suggestion_id = voice_alias_commands.parse_voice_alias_suggestion_id
handle_voice_alias_command = voice_alias_commands.handle_voice_alias_command
maybe_process_voice_alias_learning_confirmation = (
    voice_alias_commands.maybe_process_voice_alias_learning_confirmation
)
resolve_engine_for_scope = request_starts.resolve_engine_for_scope
process_prompt = request_starts.process_prompt
process_message_worker = request_starts.process_message_worker
start_message_worker = request_starts.start_message_worker
process_youtube_request = request_starts.process_youtube_request
process_youtube_worker = request_starts.process_youtube_worker
start_youtube_worker = request_starts.start_youtube_worker
process_dishframed_request = request_starts.process_dishframed_request
process_dishframed_worker = request_starts.process_dishframed_worker
start_dishframed_worker = request_starts.start_dishframed_worker
deliver_output_and_emit_success = request_processing.deliver_output_and_emit_success
begin_memory_turn = request_processing.begin_memory_turn
begin_affective_turn = request_processing.begin_affective_turn
emit_request_processing_started = request_processing.emit_request_processing_started
emit_phase_timing = request_processing.emit_phase_timing
build_progress_reporter = request_processing.build_progress_reporter
_build_prompt_progress_reporter = request_processing._build_prompt_progress_reporter
_process_prompt_request = request_processing._process_prompt_request
_process_message_worker_request = request_processing._process_message_worker_request
_process_youtube_request = request_processing._process_youtube_request
_process_youtube_worker_request = request_processing._process_youtube_worker_request
_process_dishframed_request = request_processing._process_dishframed_request
_process_dishframed_worker_request = request_processing._process_dishframed_worker_request
execute_prompt_with_retry = prompt_runtime.execute_prompt_with_retry
finalize_prompt_success = prompt_runtime.finalize_prompt_success
transcribe_voice_for_chat = prompt_inputs.transcribe_voice_for_chat
_prepare_prompt_input_request = prompt_inputs._prepare_prompt_input_request
prepare_prompt_input = prompt_inputs.prepare_prompt_input
prewarm_attachment_archive_for_message = prompt_inputs.prewarm_attachment_archive_for_message



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
