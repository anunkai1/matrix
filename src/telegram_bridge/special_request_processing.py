import logging
import subprocess
import tempfile
from typing import List

from telegram_bridge.engine_adapter import CodexEngineAdapter
from telegram_bridge.executor import ExecutorCancelledError
from telegram_bridge.handler_models import DishframedRequest, YoutubeRequest
from telegram_bridge.state_store import StateRepository

def process_youtube_request(
    request: YoutubeRequest,
    *,
    build_progress_reporter_fn,
    build_engine_progress_context_label_fn,
    state_repository_cls=StateRepository,
    codex_engine_adapter_factory=CodexEngineAdapter,
    send_canceled_response_fn,
    run_youtube_analyzer_fn,
    build_youtube_transcript_output_fn,
    deliver_output_and_emit_success_fn,
    build_youtube_unavailable_message_fn,
    execute_prompt_with_retry_fn,
    build_youtube_summary_prompt_fn,
    finalize_prompt_success_fn,
    finalize_request_progress_fn,
) -> None:
    active_engine = request.engine or codex_engine_adapter_factory()
    state_repo = state_repository_cls(request.state)
    cleanup_paths: List[str] = []
    progress = build_progress_reporter_fn(
        request.client,
        request.config,
        request.chat_id,
        request.message_id,
        request.message_thread_id,
        build_engine_progress_context_label_fn(
            request.config,
            getattr(active_engine, "engine_name", ""),
        ),
    )
    try:
        progress.start()
        if request.cancel_event is not None and request.cancel_event.is_set():
            progress.mark_failure("Execution canceled.")
            send_canceled_response_fn(
                request.client,
                request.chat_id,
                request.message_id,
                request.message_thread_id,
            )
            return

        progress.set_phase("Fetching YouTube metadata and transcript.")
        analysis = run_youtube_analyzer_fn(request.youtube_url, request.request_text)

        if request.cancel_event is not None and request.cancel_event.is_set():
            progress.mark_failure("Execution canceled.")
            send_canceled_response_fn(
                request.client,
                request.chat_id,
                request.message_id,
                request.message_thread_id,
            )
            return

        request_mode = str(analysis.get("request_mode") or "summary").strip().lower()
        transcript_text = str(analysis.get("transcript_text") or "").strip()

        if request_mode == "transcript" and transcript_text:
            output = build_youtube_transcript_output_fn(request.config, analysis, cleanup_paths)
            progress.mark_success()
            deliver_output_and_emit_success_fn(
                client=request.client,
                chat_id=request.chat_id,
                message_id=request.message_id,
                output=output,
                message_thread_id=request.message_thread_id,
            )
            return

        if not transcript_text:
            output = build_youtube_unavailable_message_fn(analysis)
            progress.mark_success()
            deliver_output_and_emit_success_fn(
                client=request.client,
                chat_id=request.chat_id,
                message_id=request.message_id,
                output=output,
                message_thread_id=request.message_thread_id,
            )
            return

        progress.set_phase("Summarizing the YouTube transcript.")
        result = execute_prompt_with_retry_fn(
            state_repo=state_repo,
            config=request.config,
            client=request.client,
            engine=active_engine,
            scope_key=request.scope_key,
            chat_id=request.chat_id,
            message_thread_id=request.message_thread_id,
            message_id=request.message_id,
            prompt_text=build_youtube_summary_prompt_fn(request.request_text, analysis),
            previous_thread_id=None,
            image_path=None,
            actor_user_id=request.actor_user_id,
            progress=progress,
            cancel_event=request.cancel_event,
            session_continuity_enabled=False,
        )
        if result is None:
            return
        finalize_prompt_success_fn(
            state_repo=state_repo,
            config=request.config,
            client=request.client,
            scope_key=request.scope_key,
            chat_id=request.chat_id,
            message_id=request.message_id,
            result=result,
            progress=progress,
        )
    finally:
        finalize_request_progress_fn(
            progress=progress,
            state=request.state,
            client=request.client,
            scope_key=request.scope_key,
            chat_id=request.chat_id,
            message_id=request.message_id,
            cancel_event=request.cancel_event,
            cleanup_paths=cleanup_paths,
        )

def process_youtube_worker_request(
    request: YoutubeRequest,
    *,
    process_youtube_request_fn,
    emit_event_fn,
    send_timeout_response_fn,
    emit_worker_exception_and_reply_fn,
) -> None:
    try:
        process_youtube_request_fn(request)
    except subprocess.TimeoutExpired:
        logging.warning("YouTube analysis timed out for chat_id=%s", request.chat_id)
        emit_event_fn(
            "bridge.request_timeout",
            level=logging.WARNING,
            fields={
                "chat_id": request.chat_id,
                "message_id": request.message_id,
                "phase": "youtube_analysis",
            },
        )
        try:
            send_timeout_response_fn(
                request.client,
                request.config,
                request.chat_id,
                request.message_id,
                request.message_thread_id,
            )
        except Exception:
            logging.exception(
                "Failed to send YouTube timeout response for chat_id=%s",
                request.chat_id,
            )
    except Exception:
        emit_worker_exception_and_reply_fn(
            log_message="Unexpected YouTube worker error for chat_id=%s",
            failure_log_message="Failed to send YouTube worker error response for chat_id=%s",
            event_fields={
                "chat_id": request.chat_id,
                "message_id": request.message_id,
                "phase": "youtube_analysis",
            },
            client=request.client,
            config=request.config,
            chat_id=request.chat_id,
            message_id=request.message_id,
            message_thread_id=request.message_thread_id,
        )

def process_dishframed_request(
    request: DishframedRequest,
    *,
    build_progress_reporter_fn,
    prepare_prompt_input_fn,
    dishframed_usage_message: str,
    run_dishframed_cli_fn,
    telegram_caption_limit: int,
    infer_media_kind_fn,
    send_chat_action_safe_fn,
    finalize_request_progress_fn,
) -> None:
    cleanup_paths: List[str] = []
    cleanup_dirs: List[str] = []
    progress = build_progress_reporter_fn(
        request.client,
        request.config,
        request.chat_id,
        request.message_id,
        request.message_thread_id,
        "DishFramed",
    )
    try:
        progress.start()
        prepared = prepare_prompt_input_fn(
            state=request.state,
            config=request.config,
            client=request.client,
            chat_id=request.chat_id,
            message_id=request.message_id,
            prompt="Render a DishFramed preview from these menu images.",
            photo_file_id=request.photo_file_ids[0] if request.photo_file_ids else None,
            photo_file_ids=request.photo_file_ids,
            voice_file_id=None,
            document=None,
            progress=progress,
        )
        if prepared is None:
            return
        cleanup_paths = list(prepared.cleanup_paths)
        image_paths = list(prepared.image_paths)
        if not image_paths:
            request.client.send_message(
                request.chat_id,
                dishframed_usage_message,
                reply_to_message_id=request.message_id,
                message_thread_id=request.message_thread_id,
            )
            return

        output_dir = tempfile.mkdtemp(prefix="dishframed-telegram-")
        cleanup_dirs.append(output_dir)
        progress.set_phase("Rendering DishFramed preview.")
        output_path, preview_text = run_dishframed_cli_fn(
            image_paths=image_paths,
            output_dir=output_dir,
            timeout_seconds=request.config.exec_timeout_seconds,
            cancel_event=request.cancel_event,
        )
        caption = (preview_text or "DishFramed preview attached.").strip()
        if len(caption) > telegram_caption_limit:
            caption = caption[: telegram_caption_limit - 1].rstrip() + "…"
        if infer_media_kind_fn(output_path) == "photo":
            send_chat_action_safe_fn(
                request.client,
                request.chat_id,
                "upload_photo",
                request.message_thread_id,
            )
            request.client.send_photo(
                chat_id=request.chat_id,
                photo=output_path,
                caption=caption,
                reply_to_message_id=request.message_id,
                message_thread_id=request.message_thread_id,
            )
        else:
            send_chat_action_safe_fn(
                request.client,
                request.chat_id,
                "upload_document",
                request.message_thread_id,
            )
            request.client.send_document(
                chat_id=request.chat_id,
                document=output_path,
                caption=caption,
                reply_to_message_id=request.message_id,
                message_thread_id=request.message_thread_id,
            )
        progress.mark_success()
    finally:
        finalize_request_progress_fn(
            progress=progress,
            state=request.state,
            client=request.client,
            scope_key=request.scope_key,
            chat_id=request.chat_id,
            message_id=request.message_id,
            cancel_event=request.cancel_event,
            cleanup_paths=cleanup_paths,
            cleanup_dirs=cleanup_dirs,
            finish_event_fields={"phase": "dishframed"},
        )

def process_dishframed_worker_request(
    request: DishframedRequest,
    *,
    process_dishframed_request_fn,
    send_timeout_response_fn,
    send_canceled_response_fn,
    emit_worker_exception_and_reply_fn,
) -> None:
    try:
        process_dishframed_request_fn(request)
    except subprocess.TimeoutExpired:
        logging.warning("DishFramed timed out for chat_id=%s", request.chat_id)
        try:
            send_timeout_response_fn(
                request.client,
                request.config,
                request.chat_id,
                request.message_id,
                request.message_thread_id,
            )
        except Exception:
            logging.exception(
                "Failed to send DishFramed timeout response for chat_id=%s",
                request.chat_id,
            )
    except ExecutorCancelledError:
        try:
            send_canceled_response_fn(
                request.client,
                request.chat_id,
                request.message_id,
                request.message_thread_id,
            )
        except Exception:
            logging.exception(
                "Failed to send DishFramed cancel response for chat_id=%s",
                request.chat_id,
            )
    except Exception:
        emit_worker_exception_and_reply_fn(
            log_message="Unexpected DishFramed worker error for chat_id=%s",
            failure_log_message="Failed to send DishFramed worker error response for chat_id=%s",
            event_fields={
                "chat_id": request.chat_id,
                "message_id": request.message_id,
                "phase": "dishframed",
            },
            client=request.client,
            config=request.config,
            chat_id=request.chat_id,
            message_id=request.message_id,
            message_thread_id=request.message_thread_id,
        )
