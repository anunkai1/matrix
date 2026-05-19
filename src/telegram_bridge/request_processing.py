from telegram_bridge.engine_adapter import CodexEngineAdapter
from telegram_bridge.dishframed_processing import DISHFRAMED_USAGE_MESSAGE, run_dishframed_cli
from telegram_bridge.handler_models import DishframedRequest, YoutubeRequest
from telegram_bridge import request_prompt_processing
from telegram_bridge import special_request_processing
from telegram_bridge.prompt_inputs import prepare_prompt_input
from telegram_bridge.prompt_runtime import execute_prompt_with_retry, finalize_prompt_success
from telegram_bridge import response_delivery
from telegram_bridge.runtime_profile import build_engine_progress_context_label
from telegram_bridge.state_store import StateRepository
from telegram_bridge.transport import TELEGRAM_CAPTION_LIMIT
from telegram_bridge.youtube_processing import (
    build_youtube_summary_prompt,
    build_youtube_transcript_output,
    build_youtube_unavailable_message,
    run_youtube_analyzer,
)

finalize_request_progress = response_delivery.finalize_request_progress
send_canceled_response = response_delivery.send_canceled_response
send_timeout_response = response_delivery.send_timeout_response
emit_worker_exception_and_reply = response_delivery.emit_worker_exception_and_reply
send_chat_action_safe = response_delivery.send_chat_action_safe
infer_media_kind = response_delivery.infer_media_kind

_emit_event = request_prompt_processing._emit_event
deliver_output_and_emit_success = request_prompt_processing.deliver_output_and_emit_success
begin_affective_turn = request_prompt_processing.begin_affective_turn
emit_request_processing_started = request_prompt_processing.emit_request_processing_started
emit_phase_timing = request_prompt_processing.emit_phase_timing
build_progress_reporter = request_prompt_processing.build_progress_reporter
_build_prompt_progress_reporter = request_prompt_processing._build_prompt_progress_reporter
_build_prompt_execution_runtime = request_prompt_processing._build_prompt_execution_runtime
_process_prompt_request = request_prompt_processing._process_prompt_request
_process_message_worker_request = request_prompt_processing._process_message_worker_request


def _build_youtube_processing_runtime():
    return special_request_processing.build_youtube_processing_runtime(
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


def _build_dishframed_processing_runtime():
    return special_request_processing.build_dishframed_processing_runtime(
        build_progress_reporter_fn=build_progress_reporter,
        prepare_prompt_input_fn=prepare_prompt_input,
        dishframed_usage_message=DISHFRAMED_USAGE_MESSAGE,
        run_dishframed_cli_fn=run_dishframed_cli,
        telegram_caption_limit=TELEGRAM_CAPTION_LIMIT,
        infer_media_kind_fn=infer_media_kind,
        send_chat_action_safe_fn=send_chat_action_safe,
        finalize_request_progress_fn=finalize_request_progress,
    )


def _process_youtube_request(request: YoutubeRequest) -> None:
    special_request_processing.process_youtube_request(
        request,
        runtime=_build_youtube_processing_runtime(),
    )


def _process_youtube_worker_request(request: YoutubeRequest) -> None:
    special_request_processing.process_youtube_worker_request(
        request,
        process_youtube_request_fn=_process_youtube_request,
        emit_event_fn=_emit_event,
        send_timeout_response_fn=send_timeout_response,
        emit_worker_exception_and_reply_fn=emit_worker_exception_and_reply,
    )


def _process_dishframed_request(request: DishframedRequest) -> None:
    special_request_processing.process_dishframed_request(
        request,
        runtime=_build_dishframed_processing_runtime(),
    )


def _process_dishframed_worker_request(request: DishframedRequest) -> None:
    special_request_processing.process_dishframed_worker_request(
        request,
        process_dishframed_request_fn=_process_dishframed_request,
        send_timeout_response_fn=send_timeout_response,
        send_canceled_response_fn=send_canceled_response,
        emit_worker_exception_and_reply_fn=emit_worker_exception_and_reply,
    )
