import importlib
import logging
import subprocess
import threading
import time
from typing import List, Optional

try:
    from .channel_adapter import ChannelAdapter
    from .engine_adapter import EngineAdapter
    from .executor import ExecutorCancelledError
    from .state_store import StateRepository
except ImportError:
    from channel_adapter import ChannelAdapter
    from engine_adapter import EngineAdapter
    from executor import ExecutorCancelledError
    from state_store import StateRepository


def _bridge_handlers():
    if __package__:
        return importlib.import_module(".handlers", __package__)
    return importlib.import_module("handlers")


def execute_prompt_with_retry(
    state_repo: StateRepository,
    config,
    client: ChannelAdapter,
    engine: EngineAdapter,
    chat_id: int,
    prompt_text: str,
    previous_thread_id: Optional[str],
    progress,
    message_thread_id: Optional[int] = None,
    message_id: Optional[int] = None,
    scope_key: Optional[str] = None,
    image_path: Optional[str] = None,
    image_paths: Optional[List[str]] = None,
    actor_user_id: Optional[int] = None,
    cancel_event: Optional[threading.Event] = None,
    session_continuity_enabled: bool = True,
) -> Optional[subprocess.CompletedProcess[str]]:
    handlers = _bridge_handlers()
    if scope_key is None:
        scope_key = handlers.build_telegram_scope_key(chat_id, message_thread_id=message_thread_id)
    allow_automatic_retry = config.persistent_workers_enabled
    retry_attempted = False
    attempt_thread_id: Optional[str] = previous_thread_id
    attempt = 0
    normalized_image_paths = list(image_paths or [])
    if image_path and image_path not in normalized_image_paths:
        normalized_image_paths.insert(0, image_path)

    while True:
        if cancel_event is not None and cancel_event.is_set():
            handlers.emit_event(
                "bridge.request_cancelled",
                fields={
                    "chat_id": chat_id,
                    "message_id": message_id,
                    "phase": "before_executor_attempt",
                    "attempt": attempt + 1,
                },
            )
            progress.mark_failure("Execution canceled.")
            handlers.send_canceled_response(client, chat_id, message_id, message_thread_id)
            return None

        attempt += 1
        handlers.emit_event(
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
                handlers.emit_phase_timing(
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
                handlers.emit_phase_timing(
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
            handlers.emit_phase_timing(
                chat_id=chat_id,
                message_id=message_id,
                phase="engine_run",
                started_at_monotonic=engine_started_at,
                attempt=attempt,
                success=False,
                error_type="ExecutorCancelledError",
            )
            logging.info("Executor canceled for chat_id=%s", chat_id)
            handlers.emit_event(
                "bridge.request_cancelled",
                fields={"chat_id": chat_id, "message_id": message_id, "attempt": attempt},
            )
            progress.mark_failure("Execution canceled.")
            handlers.send_canceled_response(client, chat_id, message_id, message_thread_id)
            return None
        except subprocess.TimeoutExpired:
            handlers.emit_phase_timing(
                chat_id=chat_id,
                message_id=message_id,
                phase="engine_run",
                started_at_monotonic=engine_started_at,
                attempt=attempt,
                success=False,
                error_type="TimeoutExpired",
            )
            logging.warning("Executor timeout for chat_id=%s", chat_id)
            handlers.emit_event(
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
            handlers.emit_phase_timing(
                chat_id=chat_id,
                message_id=message_id,
                phase="engine_run",
                started_at_monotonic=engine_started_at,
                attempt=attempt,
                success=False,
                error_type="FileNotFoundError",
            )
            logging.exception("Executor command not found: %s", config.executor_cmd)
            handlers.emit_event(
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
            handlers.emit_phase_timing(
                chat_id=chat_id,
                message_id=message_id,
                phase="engine_run",
                started_at_monotonic=engine_started_at,
                attempt=attempt,
                success=False,
                error_type="Exception",
            )
            logging.exception("Unexpected executor error for chat_id=%s", chat_id)
            handlers.emit_event(
                "bridge.executor_exception",
                level=logging.WARNING,
                fields={"chat_id": chat_id, "message_id": message_id, "attempt": attempt},
            )
            if allow_automatic_retry and not retry_attempted:
                retry_attempted = True
                if session_continuity_enabled:
                    state_repo.clear_thread_id(scope_key)
                attempt_thread_id = None
                progress.set_phase(handlers.RETRY_WITH_NEW_SESSION_PHASE)
                handlers.emit_event(
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
            handlers.send_executor_failure_message(
                client=client,
                config=config,
                chat_id=chat_id,
                message_id=message_id,
                allow_automatic_retry=allow_automatic_retry,
                message_thread_id=message_thread_id,
            )
            return None

        if result.returncode == 0:
            handlers.emit_event(
                "bridge.executor_completed",
                fields={
                    "chat_id": chat_id,
                    "message_id": message_id,
                    "attempt": attempt,
                },
            )
            return result

        reset_and_retry_new = False
        failure_message = handlers.extract_executor_failure_message(result.stdout or "", result.stderr or "")
        if attempt_thread_id and handlers.should_reset_thread_after_resume_failure(
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
            progress.set_phase(handlers.resume_retry_phase(config))
            handlers.emit_event(
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
            progress.set_phase(handlers.RETRY_WITH_NEW_SESSION_PHASE)
            handlers.emit_event(
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
        handlers.emit_event(
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
        handlers.send_executor_failure_message(
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
    progress,
    scope_key: Optional[str] = None,
    message_thread_id: Optional[int] = None,
) -> tuple[Optional[str], str]:
    handlers = _bridge_handlers()
    if scope_key is None:
        scope_key = handlers.build_telegram_scope_key(chat_id, message_thread_id=message_thread_id)
    new_thread_id, output = handlers.parse_executor_output(result.stdout or "")
    if new_thread_id:
        state_repo.set_thread_id(scope_key, new_thread_id)
    if not output:
        output = config.empty_output_message
    if not handlers.output_contains_control_directive(output):
        output = handlers.trim_output(output, config.max_output_chars)
    progress.mark_success()
    delivered_output = handlers.deliver_output_and_emit_success(
        client=client,
        chat_id=chat_id,
        message_id=message_id,
        output=output,
        message_thread_id=message_thread_id,
        new_thread_id=bool(new_thread_id),
    )
    return new_thread_id, delivered_output
