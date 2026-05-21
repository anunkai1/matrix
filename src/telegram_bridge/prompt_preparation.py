import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from telegram_bridge import attachment_processing
from telegram_bridge.handler_models import PreparedPromptInput, PromptRequest

@dataclass
class PromptPreparationState:
    prompt_text: str
    image_path: Optional[str] = None
    image_paths: List[str] = field(default_factory=list)
    document_path: Optional[str] = None
    cleanup_paths: List[str] = field(default_factory=list)
    attachment_file_ids: List[str] = field(default_factory=list)

    def append_context(self, context: str) -> None:
        if not context:
            return
        if self.prompt_text:
            self.prompt_text = f"{self.prompt_text}\n\n{context}"
        else:
            self.prompt_text = context


def _reply(request: PromptRequest, text: str) -> None:
    request.client.send_message(
        request.chat_id,
        text,
        reply_to_message_id=request.message_id,
    )


def _normalize_photo_file_ids(request: PromptRequest) -> List[str]:
    normalized_photo_file_ids = list(request.photo_file_ids or [])
    if request.photo_file_id and request.photo_file_id not in normalized_photo_file_ids:
        normalized_photo_file_ids.insert(0, request.photo_file_id)
    return normalized_photo_file_ids


def _handle_photo_attachments(
    request: PromptRequest,
    progress: Any,
    preparation: PromptPreparationState,
    *,
    attachment_store: Any,
    channel_name: str,
) -> Optional[PromptPreparationState]:
    normalized_photo_file_ids = _normalize_photo_file_ids(request)
    if not normalized_photo_file_ids:
        return preparation

    progress.set_phase(
        "Downloading images from Telegram." if len(normalized_photo_file_ids) > 1 else "Downloading image from Telegram."
    )
    for current_photo_file_id in normalized_photo_file_ids:
        preparation.attachment_file_ids.append(current_photo_file_id)
        try:
            resolution = attachment_processing.resolve_attachment_for_prompt(
                attachment_store,
                channel_name=channel_name,
                file_id=current_photo_file_id,
                media_label="image",
                media_kind="photo",
                downloader=lambda: attachment_processing.download_photo_to_temp(
                    request.client,
                    request.config,
                    current_photo_file_id,
                ),
            )
        except ValueError as exc:
            logging.warning("Photo rejected for chat_id=%s: %s", request.chat_id, exc)
            progress.mark_failure("Image request rejected.")
            _reply(request, str(exc))
            return None
        except Exception:
            logging.exception("Photo download failed for chat_id=%s", request.chat_id)
            progress.mark_failure("Image download failed.")
            _reply(request, request.config.image_download_error_message)
            return None

        if resolution.status == attachment_processing.AttachmentResolutionStatus.SUMMARY:
            preparation.append_context(resolution.summary_context)
            continue

        if resolution.local_path is not None:
            preparation.image_paths.append(resolution.local_path)
        if resolution.cleanup_path:
            preparation.cleanup_paths.append(resolution.cleanup_path)

    if preparation.image_paths:
        preparation.image_path = preparation.image_paths[0]
    return preparation


def _handle_voice_attachment(
    request: PromptRequest,
    progress: Any,
    preparation: PromptPreparationState,
    *,
    transcribe_voice_for_chat_fn,
    strip_required_prefix_fn,
    is_whatsapp_channel_fn,
    emit_event_fn,
    prefix_help_message: str,
) -> Optional[PromptPreparationState]:
    if not request.voice_file_id:
        return preparation

    preparation.attachment_file_ids.append(request.voice_file_id)
    progress.set_phase("Transcribing voice message.")
    transcript = transcribe_voice_for_chat_fn(
        state=request.state,
        config=request.config,
        client=request.client,
        chat_id=request.chat_id,
        message_id=request.message_id,
        voice_file_id=request.voice_file_id,
        echo_transcript=True,
    )
    if transcript is None:
        progress.mark_failure("Voice transcription failed.")
        return None

    if request.enforce_voice_prefix_from_transcript and request.config.required_prefixes:
        has_required_prefix, stripped_transcript = strip_required_prefix_fn(
            transcript,
            request.config.required_prefixes,
            request.config.required_prefix_ignore_case,
        )
        if not has_required_prefix:
            attachment_processing.maybe_suggest_voice_prefix_alias(
                state=request.state,
                config=request.config,
                client=request.client,
                chat_id=request.chat_id,
                message_id=request.message_id,
                transcript=transcript,
            )
            emit_event_fn(
                "bridge.request_ignored",
                fields={
                    "chat_id": request.chat_id,
                    "message_id": request.message_id,
                    "reason": "prefix_required_transcript",
                },
            )
            progress.mark_failure("Voice transcript missing required prefix.")
            if not is_whatsapp_channel_fn(request.client):
                _reply(request, prefix_help_message)
            return None
        transcript = stripped_transcript
        if not transcript.strip():
            emit_event_fn(
                "bridge.request_rejected",
                level=logging.WARNING,
                fields={
                    "chat_id": request.chat_id,
                    "message_id": request.message_id,
                    "reason": "prefix_missing_action",
                },
            )
            progress.mark_failure("Voice transcript prefix missing action.")
            if not is_whatsapp_channel_fn(request.client):
                _reply(request, prefix_help_message)
            return None

    if preparation.prompt_text:
        preparation.prompt_text = f"{preparation.prompt_text}\n\nVoice transcript:\n{transcript}"
    else:
        preparation.prompt_text = transcript
    return preparation


def _handle_document_attachment(
    request: PromptRequest,
    progress: Any,
    preparation: PromptPreparationState,
    *,
    attachment_store: Any,
    channel_name: str,
) -> Optional[PromptPreparationState]:
    document = request.document
    if document is None:
        return preparation

    preparation.attachment_file_ids.append(document.file_id)

    progress.set_phase("Downloading file from Telegram.")
    try:
        resolution = attachment_processing.resolve_attachment_for_prompt(
            attachment_store,
            channel_name=channel_name,
            file_id=document.file_id,
            media_label="file",
            media_kind="document",
            downloader=lambda: attachment_processing.download_document_to_temp(
                request.client,
                request.config,
                document,
            ),
            file_name=document.file_name,
            mime_type=document.mime_type,
        )
    except ValueError as exc:
        logging.warning("Document rejected for chat_id=%s: %s", request.chat_id, exc)
        progress.mark_failure("File request rejected.")
        _reply(request, str(exc))
        return None
    except Exception:
        logging.exception("Document download failed for chat_id=%s", request.chat_id)
        progress.mark_failure("File download failed.")
        _reply(request, request.config.document_download_error_message)
        return None

    if resolution.status == attachment_processing.AttachmentResolutionStatus.SUMMARY:
        preparation.append_context(resolution.summary_context)
        return preparation

    preparation.document_path = resolution.local_path
    if resolution.cleanup_path:
        preparation.cleanup_paths.append(resolution.cleanup_path)
    preparation.append_context(
        attachment_processing.build_document_analysis_context(
            preparation.document_path,
            document,
            resolution.size_bytes or os.path.getsize(preparation.document_path),
        )
    )
    return preparation


def _finalize_prompt_preparation(
    request: PromptRequest,
    progress: Any,
    preparation: PromptPreparationState,
    *,
    send_input_too_long_fn,
) -> Optional[PreparedPromptInput]:
    if not preparation.prompt_text:
        progress.mark_failure("No prompt content to execute.")
        return None

    if len(preparation.prompt_text) > request.config.max_input_chars:
        progress.mark_failure("Input rejected as too long.")
        send_input_too_long_fn(
            client=request.client,
            chat_id=request.chat_id,
            message_id=request.message_id,
            actual_length=len(preparation.prompt_text),
            max_input_chars=request.config.max_input_chars,
        )
        return None

    return PreparedPromptInput(
        prompt_text=preparation.prompt_text,
        image_path=preparation.image_path,
        image_paths=preparation.image_paths,
        document_path=preparation.document_path,
        cleanup_paths=preparation.cleanup_paths,
        attachment_file_ids=preparation.attachment_file_ids,
    )


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
    preparation = PromptPreparationState(prompt_text=request.prompt.strip())
    channel_name = getattr(request.client, "channel_name", "telegram")
    attachment_store = getattr(request.state, "attachment_store", None)

    for stage in (
        lambda current: _handle_photo_attachments(
            request,
            progress,
            current,
            attachment_store=attachment_store,
            channel_name=channel_name,
        ),
        lambda current: _handle_voice_attachment(
            request,
            progress,
            current,
            transcribe_voice_for_chat_fn=transcribe_voice_for_chat_fn,
            strip_required_prefix_fn=strip_required_prefix_fn,
            is_whatsapp_channel_fn=is_whatsapp_channel_fn,
            emit_event_fn=emit_event_fn,
            prefix_help_message=prefix_help_message,
        ),
        lambda current: _handle_document_attachment(
            request,
            progress,
            current,
            attachment_store=attachment_store,
            channel_name=channel_name,
        ),
    ):
        preparation = stage(preparation)
        if preparation is None:
            return None

    return _finalize_prompt_preparation(
        request,
        progress,
        preparation,
        send_input_too_long_fn=send_input_too_long_fn,
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
    download_voice_to_temp_fn,
    download_document_to_temp_fn,
    archive_media_path_fn,
) -> None:
    attachment_store = getattr(state, "attachment_store", None)
    if attachment_store is None:
        return
    channel_name = getattr(client, "channel_name", "telegram")

    photo_file_ids = extract_message_photo_file_ids_fn(message)
    _, voice_file_id, document = extract_message_media_payload_fn(message)
    for photo_file_id in photo_file_ids:
        try:
            attachment_processing.resolve_attachment_for_prompt(
                attachment_store,
                channel_name=channel_name,
                file_id=photo_file_id,
                media_label="image",
                media_kind="photo",
                downloader=lambda file_id=photo_file_id: download_photo_to_temp_fn(client, config, file_id),
                archiver=archive_media_path_fn,
            )
        except Exception:
            logging.warning(
                "Failed to prewarm attachment archive for chat_id=%s photo_file_id=%s",
                chat_id,
                photo_file_id,
                exc_info=True,
            )

    if voice_file_id is not None:
        record, _ = attachment_processing.resolve_attachment_binary_or_summary(
            attachment_store,
            channel_name=channel_name,
            file_id=voice_file_id,
            media_label="voice note",
        )
        if record is None:
            try:
                temp_path = download_voice_to_temp_fn(client, config, voice_file_id)
                archived_path = archive_media_path_fn(
                    attachment_store,
                    channel_name=channel_name,
                    file_id=voice_file_id,
                    media_kind="voice",
                    source_path=temp_path,
                )
                if archived_path:
                    os.remove(temp_path)
            except Exception:
                logging.warning(
                    "Failed to prewarm attachment archive for chat_id=%s voice_file_id=%s",
                    chat_id,
                    voice_file_id,
                    exc_info=True,
                )

    if document is not None:
        try:
            attachment_processing.resolve_attachment_for_prompt(
                attachment_store,
                channel_name=channel_name,
                file_id=document.file_id,
                media_label="file",
                media_kind="document",
                downloader=lambda: download_document_to_temp_fn(client, config, document),
                archiver=archive_media_path_fn,
                file_name=document.file_name,
                mime_type=document.mime_type,
            )
        except Exception:
            logging.warning(
                "Failed to prewarm attachment archive for chat_id=%s document_file_id=%s",
                chat_id,
                document.file_id,
                exc_info=True,
            )
