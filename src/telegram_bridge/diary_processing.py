import copy
import datetime as dt
import importlib
import logging
import os
import subprocess
import time
from typing import Dict, List, Optional

try:
    from .channel_adapter import ChannelAdapter
    from .engine_controls import build_engine_runtime_config, configured_default_engine
    from .handler_models import DocumentPayload
    from .state_store import PendingDiaryBatch, State, StateRepository
except ImportError:
    from channel_adapter import ChannelAdapter
    from engine_controls import build_engine_runtime_config, configured_default_engine
    from handler_models import DocumentPayload
    from state_store import PendingDiaryBatch, State, StateRepository


def _bridge_handlers():
    if __package__:
        return importlib.import_module(".handlers", __package__)
    return importlib.import_module("handlers")


def diary_control_command(command: Optional[str]) -> bool:
    return command in {"/today", "/queue"}


def build_diary_entry_title(
    text_blocks: List[str],
    voice_transcripts: List[str],
    photo_count: int,
) -> str:
    for candidate in [*text_blocks, *voice_transcripts]:
        cleaned = " ".join(candidate.split()).strip()
        if not cleaned:
            continue
        words = cleaned.split()
        snippet = " ".join(words[:6]).strip(" .,:;!-")
        if snippet:
            return snippet[:72]
    if photo_count > 0:
        return "Photo entry"
    if voice_transcripts:
        return "Voice note"
    return "Diary entry"


def build_diary_photo_caption(message: Dict[str, object], photo_index: int) -> str:
    handlers = _bridge_handlers()
    caption = handlers.normalize_optional_text(message.get("caption"))
    if caption:
        return caption
    return f"Photo {photo_index}"


def build_diary_queue_status(state: State, scope_key: str) -> str:
    with state.lock:
        open_batch = state.pending_diary_batches.get(scope_key)
        queued_batches = list(state.queued_diary_batches.get(scope_key, []))
        processing = scope_key in state.diary_queue_processing_scopes or scope_key in state.busy_chats
    lines = []
    lines.append(f"Processing active: {processing}")
    lines.append(f"Queued closed batches: {len(queued_batches)}")
    if open_batch is not None:
        lines.append(f"Open capture batch messages: {len(open_batch.messages)}")
    else:
        lines.append("Open capture batch messages: 0")
    if queued_batches:
        ahead = queued_batches[0]
        lines.append(f"Next queued batch messages: {len(ahead.messages)}")
    return "\n".join(lines)


def build_diary_today_status(state: State, config, scope_key: str) -> str:
    handlers = _bridge_handlers()
    now = dt.datetime.now(handlers.diary_timezone(config))
    entries = handlers.read_day_entries(config, now.date())
    docx_path = handlers.diary_day_docx_path(config, now.date())
    remote_path = handlers.diary_day_remote_docx_path(config, now.date()) or ""
    lines = [
        f"Today: {now.date().isoformat()}",
        f"Entries saved: {len(entries)}",
        f"Local document: {docx_path}",
    ]
    if handlers.diary_nextcloud_enabled(config):
        lines.append(f"Nextcloud document: {remote_path}")
    if entries:
        latest = entries[-1]
        lines.append(f"Latest entry: {latest.time_label} - {latest.title}")
    lines.append(build_diary_queue_status(state, scope_key))
    return "\n".join(lines)


def build_diary_progress_context_label(state: State, config, scope_key: str) -> str:
    handlers = _bridge_handlers()
    selected_engine = StateRepository(state).get_chat_engine(scope_key)
    engine_name = selected_engine or configured_default_engine(config)
    display_config = build_engine_runtime_config(state, config, scope_key, engine_name)
    return handlers.build_engine_progress_context_label(display_config, selected_engine)


def transcribe_voice_for_diary_batch(
    config,
    client: ChannelAdapter,
    voice_file_id: str,
) -> tuple[Optional[str], Optional[str]]:
    handlers = _bridge_handlers()
    voice_path: Optional[str] = None
    try:
        voice_path = handlers.download_voice_to_temp(client, config, voice_file_id)
        transcript, _ = handlers.transcribe_voice(config, voice_path)
        return transcript, None
    except ValueError:
        return None, config.voice_transcribe_empty_message
    except subprocess.TimeoutExpired:
        return None, config.timeout_message
    except Exception:
        return None, config.voice_transcribe_error_message
    finally:
        if voice_path:
            try:
                os.remove(voice_path)
            except OSError:
                logging.warning("Failed to remove temp diary voice file: %s", voice_path)


def process_diary_batch(
    state: State,
    config,
    client: ChannelAdapter,
    scope_key: str,
    pending: PendingDiaryBatch,
) -> None:
    handlers = _bridge_handlers()
    progress = handlers.build_progress_reporter(
        client,
        config,
        pending.chat_id,
        pending.latest_message_id,
        pending.message_thread_id,
        build_diary_progress_context_label(state, config, scope_key),
    )
    cleanup_paths: List[str] = []
    state_repo = StateRepository(state)
    cancel_event = handlers.register_cancel_event(state, scope_key)
    state_repo.mark_in_flight_request(scope_key, pending.latest_message_id)
    try:
        progress.start()
        progress.set_phase("Preparing diary entry.")
        messages = sorted(
            pending.messages,
            key=lambda item: (
                item.get("date") if isinstance(item.get("date"), int) else 0,
                item.get("message_id") if isinstance(item.get("message_id"), int) else 0,
            ),
        )
        tz = handlers.diary_timezone(config)
        timestamp_value = messages[-1].get("date") if messages else None
        if not isinstance(timestamp_value, int):
            timestamp_value = int(time.time())
        entry_dt = dt.datetime.fromtimestamp(timestamp_value, tz)
        entry_id = entry_dt.strftime("%Y%m%dT%H%M%S")
        text_blocks: List[str] = []
        voice_transcripts: List[str] = []
        notes: List[str] = []
        photos = []
        photo_index = 0

        for message in messages:
            text = handlers.normalize_optional_text(message.get("text"))
            caption = handlers.normalize_optional_text(message.get("caption"))
            if text:
                text_blocks.append(text)
            elif caption and not handlers.extract_message_photo_file_ids(message):
                text_blocks.append(caption)

            photo_file_ids = handlers.extract_message_photo_file_ids(message)
            if photo_file_ids:
                progress.set_phase(
                    "Saving diary photos." if len(photo_file_ids) > 1 else "Saving diary photo."
                )
            for photo_file_id in photo_file_ids:
                photo_index += 1
                downloaded_photo_path: Optional[str] = None
                try:
                    downloaded_photo_path = handlers.download_photo_to_temp(client, config, photo_file_id)
                    relative_path = handlers.copy_photo_to_day_assets(
                        config=config,
                        day=entry_dt.date(),
                        source_path=downloaded_photo_path,
                        entry_id=entry_id,
                        index=photo_index,
                    )
                    photos.append(
                        handlers.DiaryPhoto(
                            relative_path=relative_path,
                            caption=build_diary_photo_caption(message, photo_index),
                        )
                    )
                finally:
                    if downloaded_photo_path:
                        try:
                            os.remove(downloaded_photo_path)
                        except OSError:
                            logging.warning(
                                "Failed to remove temporary diary photo file: %s",
                                downloaded_photo_path,
                            )

            _, voice_file_id, _ = handlers.extract_message_media_payload(message)
            if voice_file_id:
                progress.set_phase("Transcribing diary voice note.")
                transcript, error_message = handlers.transcribe_voice_for_diary_batch(
                    config=config,
                    client=client,
                    voice_file_id=voice_file_id,
                )
                if transcript:
                    voice_transcripts.append(transcript)
                elif error_message:
                    notes.append(f"Voice note was received but not transcribed: {error_message}")

        if not text_blocks and not voice_transcripts and not photos:
            progress.mark_failure("No diary content to save.")
            client.send_message(
                pending.chat_id,
                "Nothing to save from that batch.",
                reply_to_message_id=pending.latest_message_id,
            )
            return

        entry = handlers.DiaryEntry(
            entry_id=entry_id,
            created_at=entry_dt.isoformat(),
            time_label=entry_dt.strftime("%I:%M %p").lstrip("0"),
            title=build_diary_entry_title(text_blocks, voice_transcripts, len(photos)),
            text_blocks=text_blocks,
            voice_transcripts=voice_transcripts,
            notes=notes,
            photos=photos,
        )

        progress.set_phase("Writing diary document.")
        docx_path = handlers.append_day_entry(config, entry_dt.date(), entry)
        remote_path = handlers.diary_day_remote_docx_path(config, entry_dt.date()) or ""
        if handlers.diary_nextcloud_enabled(config):
            progress.set_phase("Uploading diary document to Nextcloud.")
            handlers.upload_to_nextcloud(config, docx_path, remote_path)

        progress.mark_success()
        counts = []
        if text_blocks:
            counts.append(f"{len(text_blocks)} text")
        if voice_transcripts:
            counts.append(f"{len(voice_transcripts)} voice")
        if photos:
            counts.append(f"{len(photos)} photo{'s' if len(photos) != 1 else ''}")
        count_summary = ", ".join(counts) if counts else "no content"
        message = (
            f"Saved {entry.time_label} - {entry.title}.\n"
            f"Included: {count_summary}.\n"
            f"Local file: {docx_path}"
        )
        if handlers.diary_nextcloud_enabled(config):
            message += f"\nNextcloud file: {remote_path}"
        client.send_message(
            pending.chat_id,
            message,
            reply_to_message_id=pending.latest_message_id,
        )
        handlers.emit_event(
            "bridge.diary_batch_saved",
            fields={
                "chat_id": pending.chat_id,
                "message_id": pending.latest_message_id,
                "scope_key": scope_key,
                "entry_id": entry.entry_id,
                "photo_count": len(photos),
                "voice_count": len(voice_transcripts),
                "text_count": len(text_blocks),
            },
        )
    except Exception:
        logging.exception("Diary batch save failed for chat_id=%s", pending.chat_id)
        progress.mark_failure("Diary save failed.")
        handlers.send_generic_worker_error_response(
            client,
            config,
            pending.chat_id,
            pending.latest_message_id,
        )
    finally:
        handlers.finalize_request_progress(
            progress=progress,
            state=state,
            client=client,
            scope_key=scope_key,
            chat_id=pending.chat_id,
            message_id=pending.latest_message_id,
            cancel_event=cancel_event,
            cleanup_paths=cleanup_paths,
            finish_event_name="bridge.diary_batch_finished",
        )


def ensure_diary_queue_processor(
    state: State,
    config,
    client: ChannelAdapter,
    scope_key: str,
) -> None:
    handlers = _bridge_handlers()
    should_start_worker = False
    with state.lock:
        if scope_key not in state.diary_queue_processing_scopes:
            state.diary_queue_processing_scopes.add(scope_key)
            should_start_worker = True
    if not should_start_worker:
        return
    handlers.start_background_worker(handlers.diary_queue_worker, state, config, client, scope_key)


def diary_capture_batch_worker(
    state: State,
    config,
    client: ChannelAdapter,
    scope_key: str,
) -> None:
    handlers = _bridge_handlers()
    while True:
        with state.lock:
            pending = state.pending_diary_batches.get(scope_key)
            if pending is None:
                return
            quiet_window = float(getattr(config, "diary_capture_quiet_window_seconds", 75))
            remaining = quiet_window - (time.time() - pending.last_seen_at)
        if remaining > 0:
            time.sleep(min(1.0, remaining))
            continue
        with state.lock:
            pending = state.pending_diary_batches.pop(scope_key, None)
            if pending is not None:
                queue = state.queued_diary_batches.setdefault(scope_key, [])
                queue.append(pending)
                queue_depth = len(queue)
            else:
                queue_depth = 0
        if pending is None:
            return
        handlers.emit_event(
            "bridge.diary_batch_enqueued",
            fields={
                "chat_id": pending.chat_id,
                "message_id": pending.latest_message_id,
                "scope_key": scope_key,
                "queue_depth": queue_depth,
            },
        )
        if queue_depth > 1:
            client.send_message(
                pending.chat_id,
                f"Queued. {queue_depth - 1} batch{'es' if queue_depth - 1 != 1 else ''} ahead.",
                reply_to_message_id=pending.latest_message_id,
            )
        handlers.ensure_diary_queue_processor(state, config, client, scope_key)
        return


def diary_queue_worker(
    state: State,
    config,
    client: ChannelAdapter,
    scope_key: str,
) -> None:
    handlers = _bridge_handlers()
    try:
        while True:
            with state.lock:
                queue = state.queued_diary_batches.get(scope_key, [])
                pending = queue[0] if queue else None
            if pending is None:
                return
            if not handlers.mark_busy(state, scope_key):
                time.sleep(0.5)
                continue
            with state.lock:
                queue = state.queued_diary_batches.get(scope_key, [])
                pending = queue.pop(0) if queue else None
                if not queue:
                    state.queued_diary_batches.pop(scope_key, None)
            if pending is None:
                handlers.finalize_chat_work(state, client, chat_id=0, scope_key=scope_key)
                continue
            handlers.process_diary_batch(
                state=state,
                config=config,
                client=client,
                scope_key=scope_key,
                pending=pending,
            )
    finally:
        with state.lock:
            state.diary_queue_processing_scopes.discard(scope_key)
            has_more = bool(state.queued_diary_batches.get(scope_key))
        if has_more:
            handlers.ensure_diary_queue_processor(state, config, client, scope_key)


def queue_diary_capture(
    state: State,
    config,
    client: ChannelAdapter,
    scope_key: str,
    chat_id: int,
    message_thread_id: Optional[int],
    message_id: Optional[int],
    sender_name: str,
    actor_user_id: Optional[int],
    message: Dict[str, object],
) -> None:
    handlers = _bridge_handlers()
    should_start_capture_worker = False
    buffered_message_count = 0
    with state.lock:
        pending = state.pending_diary_batches.get(scope_key)
        if pending is None:
            pending = PendingDiaryBatch(
                scope_key=scope_key,
                chat_id=chat_id,
                message_thread_id=message_thread_id,
                latest_message_id=message_id,
                sender_name=sender_name,
                actor_user_id=actor_user_id,
            )
            state.pending_diary_batches[scope_key] = pending
        pending.messages.append(copy.deepcopy(message))
        pending.last_seen_at = time.time()
        pending.latest_message_id = message_id
        buffered_message_count = len(pending.messages)
        if not pending.worker_started:
            pending.worker_started = True
            should_start_capture_worker = True
    handlers.emit_event(
        "bridge.diary_batch_buffered",
        fields={
            "chat_id": chat_id,
            "message_id": message_id,
            "scope_key": scope_key,
            "buffered_message_count": buffered_message_count,
        },
    )
    if should_start_capture_worker:
        handlers.start_background_worker(handlers.diary_capture_batch_worker, state, config, client, scope_key)
