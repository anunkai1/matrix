import importlib
import logging
import os
import subprocess
from typing import Dict, List, Optional

try:
    from .channel_adapter import ChannelAdapter
    from .handler_models import DocumentPayload, PreparedPromptInput, PromptRequest
    from .state_store import State
    from . import prompt_preparation
except ImportError:
    from channel_adapter import ChannelAdapter
    from handler_models import DocumentPayload, PreparedPromptInput, PromptRequest
    from state_store import State
    import prompt_preparation


def _bridge_handlers():
    if __package__:
        return importlib.import_module(".handlers", __package__)
    return importlib.import_module("handlers")


def transcribe_voice_for_chat(
    state: State,
    config,
    client: ChannelAdapter,
    chat_id: int,
    message_id: Optional[int],
    voice_file_id: str,
    echo_transcript: bool = True,
) -> Optional[str]:
    handlers = _bridge_handlers()
    if not config.voice_transcribe_cmd:
        client.send_message(
            chat_id,
            config.voice_not_configured_message,
            reply_to_message_id=message_id,
        )
        return None

    voice_path: Optional[str] = None
    try:
        try:
            voice_path = handlers.download_voice_to_temp(client, config, voice_file_id)
        except ValueError as exc:
            logging.warning("Voice rejected for chat_id=%s: %s", chat_id, exc)
            client.send_message(chat_id, str(exc), reply_to_message_id=message_id)
            return None
        except Exception:
            logging.exception("Voice download failed for chat_id=%s", chat_id)
            client.send_message(
                chat_id,
                config.voice_download_error_message,
                reply_to_message_id=message_id,
            )
            return None

        try:
            transcript, confidence = handlers.transcribe_voice(config, voice_path)
        except subprocess.TimeoutExpired:
            logging.warning("Voice transcription timeout for chat_id=%s", chat_id)
            client.send_message(
                chat_id,
                config.timeout_message,
                reply_to_message_id=message_id,
            )
            return None
        except ValueError:
            logging.warning("Voice transcription was empty for chat_id=%s", chat_id)
            client.send_message(
                chat_id,
                config.voice_transcribe_empty_message,
                reply_to_message_id=message_id,
            )
            return None
        except RuntimeError:
            client.send_message(
                chat_id,
                config.voice_transcribe_error_message,
                reply_to_message_id=message_id,
            )
            return None
        except Exception:
            logging.exception("Unexpected voice transcription error for chat_id=%s", chat_id)
            client.send_message(
                chat_id,
                config.voice_transcribe_error_message,
                reply_to_message_id=message_id,
            )
            return None

        transcript, aliases_applied = handlers.apply_voice_alias_replacements(
            transcript,
            handlers.build_active_voice_alias_replacements(config, state),
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
            client.send_message(
                chat_id,
                handlers.build_low_confidence_voice_message(config, transcript, confidence),
                reply_to_message_id=message_id,
            )
            return None

        if echo_transcript:
            try:
                heading = "Voice transcript:"
                if confidence is not None:
                    heading = f"Voice transcript (confidence {confidence:.2f}):"
                client.send_message(
                    chat_id,
                    f"{heading}\n{transcript}",
                    reply_to_message_id=message_id,
                )
            except Exception:
                logging.exception("Failed to send voice transcript echo for chat_id=%s", chat_id)
        return transcript
    finally:
        if voice_path:
            try:
                os.remove(voice_path)
            except OSError:
                logging.warning("Failed to remove temp voice file: %s", voice_path)


def _prepare_prompt_input_request(
    request: PromptRequest,
    progress,
) -> Optional[PreparedPromptInput]:
    handlers = _bridge_handlers()
    return prompt_preparation.prepare_prompt_input_request(
        request,
        progress,
        transcribe_voice_for_chat_fn=handlers.transcribe_voice_for_chat,
        strip_required_prefix_fn=handlers.strip_required_prefix,
        is_whatsapp_channel_fn=handlers.is_whatsapp_channel,
        send_input_too_long_fn=handlers.send_input_too_long,
        emit_event_fn=handlers.emit_event,
        prefix_help_message=handlers.PREFIX_HELP_MESSAGE,
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
    handlers = _bridge_handlers()
    return _prepare_prompt_input_request(
        handlers.build_prompt_request(
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
    handlers = _bridge_handlers()
    prompt_preparation.prewarm_attachment_archive_for_message(
        state,
        config,
        client,
        chat_id,
        message,
        extract_message_photo_file_ids_fn=handlers.extract_message_photo_file_ids,
        extract_message_media_payload_fn=handlers.extract_message_media_payload,
        download_photo_to_temp_fn=handlers.download_photo_to_temp,
        download_document_to_temp_fn=handlers.download_document_to_temp,
        archive_media_path_fn=handlers.archive_media_path,
    )
