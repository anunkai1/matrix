from typing import List, Optional

from telegram_bridge.auth_state import refresh_runtime_auth_fingerprint
from telegram_bridge.channel_adapter import ChannelAdapter
from telegram_bridge.engine_adapter import CodexEngineAdapter, EngineAdapter
from telegram_bridge.handler_progress import ProgressReporter
from telegram_bridge.handler_models import DocumentPayload, PromptRequest
from telegram_bridge.prompt_inputs import _prepare_prompt_input_request
from telegram_bridge.prompt_runtime import execute_prompt_with_retry, finalize_prompt_success
from telegram_bridge import prompt_execution
from telegram_bridge import response_delivery
from telegram_bridge.runtime_profile import assistant_label, build_engine_progress_context_label
from telegram_bridge.state_store import StateRepository
from telegram_bridge.structured_logging import emit_event
from telegram_bridge.engine_controls import build_engine_runtime_config

finalize_request_progress = response_delivery.finalize_request_progress
emit_worker_exception_and_reply = response_delivery.emit_worker_exception_and_reply


def _emit_event(*args, **kwargs) -> None:
    emit_event(*args, **kwargs)


def deliver_output_and_emit_success(
    client: ChannelAdapter,
    chat_id: int,
    message_id: Optional[int],
    output: str,
    message_thread_id: Optional[int] = None,
    new_thread_id: bool = False,
    reply_to_message_id: Optional[int] = None,
) -> str:
    delivered_output = response_delivery.send_executor_output(
        client=client,
        chat_id=chat_id,
        message_id=message_id,
        output=output,
        message_thread_id=message_thread_id,
        reply_to_message_id=reply_to_message_id,
    )
    _emit_event(
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
        emit_event_fn=_emit_event,
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
        emit_event_fn=_emit_event,
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
        emit_event_fn=_emit_event,
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
        progress_reporter_cls=ProgressReporter,
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
        progress_reporter_cls=ProgressReporter,
        assistant_label_fn=assistant_label,
    )


def _build_prompt_execution_runtime():
    return prompt_execution.build_prompt_execution_runtime(
        progress_reporter_cls=ProgressReporter,
        state_repository_cls=StateRepository,
        codex_engine_adapter_factory=CodexEngineAdapter,
        assistant_label_fn=assistant_label,
        build_engine_runtime_config_fn=build_engine_runtime_config,
        build_engine_progress_context_label_fn=build_engine_progress_context_label,
        refresh_runtime_auth_fingerprint_fn=refresh_runtime_auth_fingerprint,
        prepare_prompt_input_request_fn=_prepare_prompt_input_request,
        execute_prompt_with_retry_fn=execute_prompt_with_retry,
        finalize_prompt_success_fn=finalize_prompt_success,
        finalize_request_progress_fn=finalize_request_progress,
        emit_event_fn=_emit_event,
    )


def _process_prompt_request(request: PromptRequest) -> None:
    prompt_execution.process_prompt_request(
        request,
        runtime=_build_prompt_execution_runtime(),
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
