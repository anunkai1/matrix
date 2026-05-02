import logging
import os
from typing import Any, Dict, List, Optional

try:
    from . import attachment_processing
    from .handler_models import PreparedPromptInput, PromptRequest
except ImportError:
    import attachment_processing
    from handler_models import PreparedPromptInput, PromptRequest


def prepare_prompt_input_request(
    request: PromptRequest,
    progress: Any,
    *,
    transcribe_voice_for_chat_fn,
    strip_required_prefix_fn,
    is_whatsapp_channel_fn,
    send_input_too_long_fn,
    emit_event_fn,
    prefix_help_message: str,
) -> Optional[PreparedPromptInput]:
    state = request.state
    config = request.config
    client = request.client
    chat_id = request.chat_id
    message_id = request.message_id
    prompt = request.prompt
    photo_file_id = request.photo_file_id
    voice_file_id = request.voice_file_id
    document = request.document
    photo_file_ids = request.photo_file_ids
    enforce_voice_prefix_from_transcript = request.enforce_voice_prefix_from_transcript
    channel_name = getattr(client, "channel_name", "telegram")
    attachment_store = getattr(state, "attachment_store", None)
    prompt_text = prompt.strip()
    image_path: Optional[str] = None
    image_paths: List[str] = []
    document_path: Optional[str] = None
    cleanup_paths: List[str] = []
    attachment_file_ids: List[str] = []

    normalized_photo_file_ids = list(photo_file_ids or [])
    if photo_file_id and photo_file_id not in normalized_photo_file_ids:
        normalized_photo_file_ids.insert(0, photo_file_id)

    if normalized_photo_file_ids:
        progress.set_phase(
            "Downloading images from Telegram." if len(normalized_photo_file_ids) > 1 else "Downloading image from Telegram."
        )
        for current_photo_file_id in normalized_photo_file_ids:
            attachment_file_ids.append(current_photo_file_id)
            resolved_image_path, archived_summary_context = (
                attachment_processing.resolve_attachment_binary_or_summary(
                    attachment_store,
                    channel_name=channel_name,
                    file_id=current_photo_file_id,
                    media_label="image",
                )
            )
            if resolved_image_path is None:
                try:
                    downloaded_image_path = attachment_processing.download_photo_to_temp(
                        client,
                        config,
                        current_photo_file_id,
                    )
                    archived_image_path = attachment_processing.archive_media_path(
                        attachment_store,
                        channel_name=channel_name,
                        file_id=current_photo_file_id,
                        media_kind="photo",
                        source_path=downloaded_image_path,
                    )
                    if archived_image_path:
                        resolved_image_path = archived_image_path
                        try:
                            os.remove(downloaded_image_path)
                        except OSError:
                            logging.warning(
                                "Failed to remove temporary image after archiving: %s",
                                downloaded_image_path,
                            )
                    else:
                        resolved_image_path = downloaded_image_path
                        cleanup_paths.append(downloaded_image_path)
                except ValueError as exc:
                    if archived_summary_context:
                        if prompt_text:
                            prompt_text = f"{prompt_text}\n\n{archived_summary_context}"
                        else:
                            prompt_text = archived_summary_context
                    else:
                        logging.warning("Photo rejected for chat_id=%s: %s", chat_id, exc)
                        progress.mark_failure("Image request rejected.")
                        client.send_message(chat_id, str(exc), reply_to_message_id=message_id)
                        return None
                except Exception:
                    if archived_summary_context:
                        logging.warning(
                            "Photo redownload failed for chat_id=%s; using archived summary fallback.",
                            chat_id,
                        )
                        if prompt_text:
                            prompt_text = f"{prompt_text}\n\n{archived_summary_context}"
                        else:
                            prompt_text = archived_summary_context
                    else:
                        logging.exception("Photo download failed for chat_id=%s", chat_id)
                        progress.mark_failure("Image download failed.")
                        client.send_message(
                            chat_id,
                            config.image_download_error_message,
                            reply_to_message_id=message_id,
                        )
                        return None
            if resolved_image_path is not None:
                image_paths.append(resolved_image_path)

        if image_paths:
            image_path = image_paths[0]

    if voice_file_id:
        progress.set_phase("Transcribing voice message.")
        transcript = transcribe_voice_for_chat_fn(
            state=state,
            config=config,
            client=client,
            chat_id=chat_id,
            message_id=message_id,
            voice_file_id=voice_file_id,
            echo_transcript=True,
        )
        if transcript is None:
            progress.mark_failure("Voice transcription failed.")
            return None
        if enforce_voice_prefix_from_transcript and config.required_prefixes:
            has_required_prefix, stripped_transcript = strip_required_prefix_fn(
                transcript,
                config.required_prefixes,
                config.required_prefix_ignore_case,
            )
            if not has_required_prefix:
                attachment_processing.maybe_suggest_voice_prefix_alias(
                    state=state,
                    config=config,
                    client=client,
                    chat_id=chat_id,
                    message_id=message_id,
                    transcript=transcript,
                )
                emit_event_fn(
                    "bridge.request_ignored",
                    fields={
                        "chat_id": chat_id,
                        "message_id": message_id,
                        "reason": "prefix_required_transcript",
                    },
                )
                progress.mark_failure("Voice transcript missing required prefix.")
                if not is_whatsapp_channel_fn(client):
                    client.send_message(
                        chat_id,
                        prefix_help_message,
                        reply_to_message_id=message_id,
                    )
                return None
            transcript = stripped_transcript
            if not transcript.strip():
                emit_event_fn(
                    "bridge.request_rejected",
                    level=logging.WARNING,
                    fields={
                        "chat_id": chat_id,
                        "message_id": message_id,
                        "reason": "prefix_missing_action",
                    },
                )
                progress.mark_failure("Voice transcript prefix missing action.")
                if not is_whatsapp_channel_fn(client):
                    client.send_message(
                        chat_id,
                        prefix_help_message,
                        reply_to_message_id=message_id,
                    )
                return None
        if prompt_text:
            prompt_text = f"{prompt_text}\n\nVoice transcript:\n{transcript}"
        else:
            prompt_text = transcript

    if document:
        attachment_file_ids.append(document.file_id)
        archived_document_summary = ""
        if attachment_store is not None:
            archived_document_summary = attachment_processing.build_archived_attachment_summary_context(
                "file",
                attachment_store.get_summary(channel_name, document.file_id),
            )
        document_record_path, _ = attachment_processing.resolve_attachment_binary_or_summary(
            attachment_store,
            channel_name=channel_name,
            file_id=document.file_id,
            media_label="file",
        )
        if document_record_path is not None:
            document_path = document_record_path
            file_size = os.path.getsize(document_path)
            context = attachment_processing.build_document_analysis_context(
                document_path,
                document,
                file_size,
            )
            if prompt_text:
                prompt_text = f"{prompt_text}\n\n{context}"
            else:
                prompt_text = context
        else:
            progress.set_phase("Downloading file from Telegram.")
            try:
                downloaded_document_path, file_size = attachment_processing.download_document_to_temp(
                    client,
                    config,
                    document,
                )
                archived_document_path = attachment_processing.archive_media_path(
                    attachment_store,
                    channel_name=channel_name,
                    file_id=document.file_id,
                    media_kind="document",
                    source_path=downloaded_document_path,
                    file_name=document.file_name,
                    mime_type=document.mime_type,
                )
                if archived_document_path:
                    document_path = archived_document_path
                    try:
                        os.remove(downloaded_document_path)
                    except OSError:
                        logging.warning(
                            "Failed to remove temporary document after archiving: %s",
                            downloaded_document_path,
                        )
                    file_size = os.path.getsize(document_path)
                else:
                    document_path = downloaded_document_path
                    cleanup_paths.append(downloaded_document_path)
                context = attachment_processing.build_document_analysis_context(
                    document_path,
                    document,
                    file_size,
                )
                if prompt_text:
                    prompt_text = f"{prompt_text}\n\n{context}"
                else:
                    prompt_text = context
            except ValueError as exc:
                if archived_document_summary:
                    if prompt_text:
                        prompt_text = f"{prompt_text}\n\n{archived_document_summary}"
                    else:
                        prompt_text = archived_document_summary
                else:
                    logging.warning("Document rejected for chat_id=%s: %s", chat_id, exc)
                    progress.mark_failure("File request rejected.")
                    client.send_message(chat_id, str(exc), reply_to_message_id=message_id)
                    return None
            except Exception:
                if archived_document_summary:
                    logging.warning(
                        "Document redownload failed for chat_id=%s; using archived summary fallback.",
                        chat_id,
                    )
                    if prompt_text:
                        prompt_text = f"{prompt_text}\n\n{archived_document_summary}"
                    else:
                        prompt_text = archived_document_summary
                else:
                    logging.exception("Document download failed for chat_id=%s", chat_id)
                    progress.mark_failure("File download failed.")
                    client.send_message(
                        chat_id,
                        config.document_download_error_message,
                        reply_to_message_id=message_id,
                    )
                    return None

    if not prompt_text:
        progress.mark_failure("No prompt content to execute.")
        return None

    if len(prompt_text) > config.max_input_chars:
        progress.mark_failure("Input rejected as too long.")
        send_input_too_long_fn(
            client=client,
            chat_id=chat_id,
            message_id=message_id,
            actual_length=len(prompt_text),
            max_input_chars=config.max_input_chars,
        )
        return None

    return PreparedPromptInput(
        prompt_text=prompt_text,
        image_path=image_path,
        image_paths=image_paths,
        document_path=document_path,
        cleanup_paths=cleanup_paths,
        attachment_file_ids=attachment_file_ids,
    )


def prewarm_attachment_archive_for_message(
    state,
    config,
    client,
    chat_id: int,
    message: Dict[str, object],
    *,
    extract_message_photo_file_ids_fn,
    extract_message_media_payload_fn,
    download_photo_to_temp_fn,
    download_document_to_temp_fn,
    archive_media_path_fn,
) -> None:
    attachment_store = getattr(state, "attachment_store", None)
    if attachment_store is None:
        return
    channel_name = getattr(client, "channel_name", "telegram")

    photo_file_ids = extract_message_photo_file_ids_fn(message)
    _, _, document = extract_message_media_payload_fn(message)
    for photo_file_id in photo_file_ids:
        record, _ = attachment_processing.resolve_attachment_binary_or_summary(
            attachment_store,
            channel_name=channel_name,
            file_id=photo_file_id,
            media_label="image",
        )
        if record is None:
            try:
                temp_path = download_photo_to_temp_fn(client, config, photo_file_id)
                archived_path = archive_media_path_fn(
                    attachment_store,
                    channel_name=channel_name,
                    file_id=photo_file_id,
                    media_kind="photo",
                    source_path=temp_path,
                )
                if archived_path:
                    os.remove(temp_path)
            except Exception:
                logging.warning(
                    "Failed to prewarm attachment archive for chat_id=%s photo_file_id=%s",
                    chat_id,
                    photo_file_id,
                    exc_info=True,
                )

    if document is not None:
        record, _ = attachment_processing.resolve_attachment_binary_or_summary(
            attachment_store,
            channel_name=channel_name,
            file_id=document.file_id,
            media_label="file",
        )
        if record is None:
            try:
                temp_path, _ = download_document_to_temp_fn(client, config, document)
                archived_path = archive_media_path_fn(
                    attachment_store,
                    channel_name=channel_name,
                    file_id=document.file_id,
                    media_kind="document",
                    source_path=temp_path,
                    file_name=document.file_name,
                    mime_type=document.mime_type,
                )
                if archived_path:
                    os.remove(temp_path)
            except Exception:
                logging.warning(
                    "Failed to prewarm attachment archive for chat_id=%s document_file_id=%s",
                    chat_id,
                    document.file_id,
                    exc_info=True,
                )
