import logging
import os
import subprocess
from typing import Dict, List, Optional

from telegram_bridge.attachment_processing import (
    apply_voice_alias_replacements,
    archive_media_path,
    build_active_voice_alias_replacements,
    build_low_confidence_voice_message,
    download_document_to_temp,
    download_photo_to_temp,
    download_voice_to_temp,
    resolve_voice_attachment_for_prompt,
    transcribe_voice,
)
from telegram_bridge.channel_adapter import ChannelAdapter
from telegram_bridge.handler_common import strip_required_prefix
from telegram_bridge.handler_models import (
    DocumentPayload,
    PreparedPromptInput,
    PromptRequest,
    build_prompt_request,
)
from telegram_bridge.message_inputs import extract_message_media_payload, extract_message_photo_file_ids
from telegram_bridge.response_delivery import send_input_too_long
from telegram_bridge.runtime_profile import PREFIX_HELP_MESSAGE, is_whatsapp_channel
from telegram_bridge.state_store import State
from telegram_bridge.structured_logging import emit_event
from telegram_bridge import prompt_preparation


def _reply(client: ChannelAdapter, chat_id: int, message_id: Optional[int], text: str) -> None:
    client.send_message(
        chat_id,
        text,
        reply_to_message_id=message_id,
    )


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
        _reply(client, chat_id, message_id, config.voice_not_configured_message)
        return None

    voice_path: Optional[str] = None
    cleanup_voice_path = False
    try:
        try:
            resolution = resolve_voice_attachment_for_prompt(
                getattr(state, "attachment_store", None),
                channel_name=getattr(client, "channel_name", "telegram"),
                file_id=voice_file_id,
                downloader=lambda: download_voice_to_temp(client, config, voice_file_id),
            )
        except ValueError as exc:
            logging.warning("Voice rejected for chat_id=%s: %s", chat_id, exc)
            _reply(client, chat_id, message_id, str(exc))
            return None
        except Exception:
            logging.exception("Voice download failed for chat_id=%s", chat_id)
            _reply(client, chat_id, message_id, config.voice_download_error_message)
            return None

        voice_path = resolution.local_path
        cleanup_voice_path = bool(resolution.cleanup_path)
        if voice_path is None:
            logging.warning("Voice audio unavailable for chat_id=%s file_id=%s", chat_id, voice_file_id)
            _reply(client, chat_id, message_id, config.voice_transcribe_error_message)
            return None

        try:
            transcript, confidence = transcribe_voice(config, voice_path)
        except subprocess.TimeoutExpired:
            logging.warning("Voice transcription timeout for chat_id=%s", chat_id)
            _reply(client, chat_id, message_id, config.timeout_message)
            return None
        except ValueError:
            logging.warning("Voice transcription was empty for chat_id=%s", chat_id)
            _reply(client, chat_id, message_id, config.voice_transcribe_empty_message)
            return None
        except RuntimeError:
            _reply(client, chat_id, message_id, config.voice_transcribe_error_message)
            return None
        except Exception:
            logging.exception("Unexpected voice transcription error for chat_id=%s", chat_id)
            _reply(client, chat_id, message_id, config.voice_transcribe_error_message)
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
            _reply(
                client,
                chat_id,
                message_id,
                build_low_confidence_voice_message(config, transcript, confidence),
            )
            return None

        if echo_transcript:
            try:
                heading = "Voice transcript:"
                if confidence is not None:
                    heading = f"Voice transcript (confidence {confidence:.2f}):"
                _reply(client, chat_id, message_id, f"{heading}\n{transcript}")
            except Exception:
                logging.exception("Failed to send voice transcript echo for chat_id=%s", chat_id)
        return transcript
    finally:
        if voice_path and cleanup_voice_path:
            try:
                os.remove(voice_path)
            except OSError:
                logging.warning("Failed to remove temp voice file: %s", voice_path)


def _prepare_prompt_input_request(
    request: PromptRequest,
    progress,
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
    progress,
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
        download_voice_to_temp_fn=download_voice_to_temp,
        download_document_to_temp_fn=download_document_to_temp,
        archive_media_path_fn=archive_media_path,
    )
