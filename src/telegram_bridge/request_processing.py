from typing import List, Optional

try:
    from .auth_state import refresh_runtime_auth_fingerprint
    from .channel_adapter import ChannelAdapter
    from .engine_adapter import CodexEngineAdapter, EngineAdapter
    from .handler_models import DocumentPayload, DishframedRequest, PromptRequest, YoutubeRequest
    from . import prompt_execution
    from . import special_request_processing
    from . import response_delivery
    from .runtime_profile import assistant_label, build_engine_progress_context_label
    from .state_store import StateRepository
    from .structured_logging import emit_event
    from .engine_controls import build_engine_runtime_config
except ImportError:
    from auth_state import refresh_runtime_auth_fingerprint
    from channel_adapter import ChannelAdapter
    from engine_adapter import CodexEngineAdapter, EngineAdapter
    from handler_models import DocumentPayload, DishframedRequest, PromptRequest, YoutubeRequest
    import prompt_execution
    import special_request_processing
    import response_delivery
    from runtime_profile import assistant_label, build_engine_progress_context_label
    from state_store import StateRepository
    from structured_logging import emit_event
    from engine_controls import build_engine_runtime_config


finalize_request_progress = response_delivery.finalize_request_progress
send_canceled_response = response_delivery.send_canceled_response
send_timeout_response = response_delivery.send_timeout_response
emit_worker_exception_and_reply = response_delivery.emit_worker_exception_and_reply
send_chat_action_safe = response_delivery.send_chat_action_safe
infer_media_kind = response_delivery.infer_media_kind


try:
    from . import bridge_deps as handlers
except ImportError:
    import bridge_deps as handlers


def deliver_output_and_emit_success(
    client: ChannelAdapter,
    chat_id: int,
    message_id: Optional[int],
    output: str,
    message_thread_id: Optional[int] = None,
    new_thread_id: bool = False,
) -> str:
    delivered_output = handlers.send_executor_output(
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
):
    return prompt_execution.build_progress_reporter(
        client,
        config,
        chat_id,
        message_id,
        message_thread_id,
        progress_context_label,
        progress_reporter_cls=handlers.ProgressReporter,
        assistant_label_fn=assistant_label,
    )


def _build_prompt_progress_reporter(
    request: PromptRequest,
    active_engine: EngineAdapter,
):
    return prompt_execution.build_prompt_progress_reporter(
        request,
        active_engine,
        build_engine_runtime_config_fn=build_engine_runtime_config,
        build_engine_progress_context_label_fn=build_engine_progress_context_label,
        progress_reporter_cls=handlers.ProgressReporter,
        assistant_label_fn=assistant_label,
    )


def _process_prompt_request(request: PromptRequest) -> None:
    prompt_execution.process_prompt_request(
        request,
        progress_reporter_cls=handlers.ProgressReporter,
        state_repository_cls=StateRepository,
        codex_engine_adapter_factory=CodexEngineAdapter,
        assistant_label_fn=assistant_label,
        build_engine_runtime_config_fn=build_engine_runtime_config,
        build_engine_progress_context_label_fn=build_engine_progress_context_label,
        refresh_runtime_auth_fingerprint_fn=refresh_runtime_auth_fingerprint,
        prepare_prompt_input_request_fn=handlers._prepare_prompt_input_request,
        execute_prompt_with_retry_fn=handlers.execute_prompt_with_retry,
        finalize_prompt_success_fn=handlers.finalize_prompt_success,
        finalize_request_progress_fn=finalize_request_progress,
        emit_event_fn=emit_event,
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


def _process_youtube_request(request: YoutubeRequest) -> None:
    special_request_processing.process_youtube_request(
        request,
        build_progress_reporter_fn=build_progress_reporter,
        build_engine_progress_context_label_fn=build_engine_progress_context_label,
        state_repository_cls=StateRepository,
        codex_engine_adapter_factory=CodexEngineAdapter,
        send_canceled_response_fn=send_canceled_response,
        run_youtube_analyzer_fn=handlers.run_youtube_analyzer,
        build_youtube_transcript_output_fn=handlers.build_youtube_transcript_output,
        deliver_output_and_emit_success_fn=deliver_output_and_emit_success,
        build_youtube_unavailable_message_fn=handlers.build_youtube_unavailable_message,
        execute_prompt_with_retry_fn=handlers.execute_prompt_with_retry,
        build_youtube_summary_prompt_fn=handlers.build_youtube_summary_prompt,
        finalize_prompt_success_fn=handlers.finalize_prompt_success,
        finalize_request_progress_fn=finalize_request_progress,
    )


def _process_youtube_worker_request(request: YoutubeRequest) -> None:
    special_request_processing.process_youtube_worker_request(
        request,
        process_youtube_request_fn=_process_youtube_request,
        emit_event_fn=emit_event,
        send_timeout_response_fn=send_timeout_response,
        emit_worker_exception_and_reply_fn=emit_worker_exception_and_reply,
    )


def _process_dishframed_request(request: DishframedRequest) -> None:
    special_request_processing.process_dishframed_request(
        request,
        build_progress_reporter_fn=build_progress_reporter,
        prepare_prompt_input_fn=handlers.prepare_prompt_input,
        dishframed_usage_message=handlers.DISHFRAMED_USAGE_MESSAGE,
        run_dishframed_cli_fn=handlers.run_dishframed_cli,
        telegram_caption_limit=handlers.TELEGRAM_CAPTION_LIMIT,
        infer_media_kind_fn=infer_media_kind,
        send_chat_action_safe_fn=send_chat_action_safe,
        finalize_request_progress_fn=finalize_request_progress,
    )


def _process_dishframed_worker_request(request: DishframedRequest) -> None:
    special_request_processing.process_dishframed_worker_request(
        request,
        process_dishframed_request_fn=_process_dishframed_request,
        send_timeout_response_fn=send_timeout_response,
        send_canceled_response_fn=send_canceled_response,
        emit_worker_exception_and_reply_fn=emit_worker_exception_and_reply,
    )
