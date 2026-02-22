import logging
import os
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

try:
    from .executor import (
        ExecutorProgressEvent,
        parse_executor_output,
        run_executor,
        should_reset_thread_after_resume_failure,
    )
    from .media import TelegramFileDownloadSpec, download_telegram_file_to_temp
    from .session_manager import (
        ensure_chat_worker_session,
        finalize_chat_work,
        is_rate_limited,
        mark_busy,
        request_safe_restart,
        trigger_restart_async,
    )
    from .state_store import State, StateRepository
    from .transport import TELEGRAM_LIMIT, TelegramClient
except ImportError:
    from executor import (
        ExecutorProgressEvent,
        parse_executor_output,
        run_executor,
        should_reset_thread_after_resume_failure,
    )
    from media import TelegramFileDownloadSpec, download_telegram_file_to_temp
    from session_manager import (
        ensure_chat_worker_session,
        finalize_chat_work,
        is_rate_limited,
        mark_busy,
        request_safe_restart,
        trigger_restart_async,
    )
    from state_store import State, StateRepository
    from transport import TELEGRAM_LIMIT, TelegramClient

PROGRESS_TYPING_INTERVAL_SECONDS = 4
PROGRESS_EDIT_MIN_INTERVAL_SECONDS = 6
PROGRESS_HEARTBEAT_EDIT_SECONDS = 30


@dataclass
class DocumentPayload:
    file_id: str
    file_name: str
    mime_type: str


@dataclass
class PreparedPromptInput:
    prompt_text: str
    image_path: Optional[str] = None
    document_path: Optional[str] = None


def normalize_command(text: str) -> Optional[str]:
    stripped = text.strip()
    if not stripped.startswith("/"):
        return None
    head = stripped.split(maxsplit=1)[0]
    return head.split("@", maxsplit=1)[0]


def trim_output(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    marker = "\n\n[output truncated]"
    return text[: max(0, limit - len(marker))] + marker


def compact_progress_text(text: str, max_chars: int = 120) -> str:
    cleaned = " ".join(text.replace("\n", " ").split())
    cleaned = cleaned.replace("**", "").replace("`", "")
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[: max_chars - 3].rstrip() + "..."


class ProgressReporter:
    def __init__(
        self,
        client: TelegramClient,
        chat_id: int,
        reply_to_message_id: Optional[int],
    ) -> None:
        self.client = client
        self.chat_id = chat_id
        self.reply_to_message_id = reply_to_message_id
        self.started_at = time.time()
        self.progress_message_id: Optional[int] = None
        self.phase = "Starting request."
        self.commands_started = 0
        self.commands_completed = 0
        self.pending_update = True
        self.last_edit_at = 0.0
        self.last_rendered_text = ""
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._worker: Optional[threading.Thread] = None

    def start(self) -> None:
        text = self._render_progress_text()
        try:
            self.progress_message_id = self.client.send_message_get_id(
                self.chat_id,
                text,
                reply_to_message_id=self.reply_to_message_id,
            )
        except Exception:
            logging.exception("Failed to send initial progress message for chat_id=%s", self.chat_id)
            self.progress_message_id = None

        self.last_rendered_text = text
        self.last_edit_at = time.time()
        self._worker = threading.Thread(target=self._heartbeat_loop, daemon=True)
        self._worker.start()

    def close(self) -> None:
        self._stop_event.set()
        if self._worker:
            self._worker.join(timeout=2.0)
        self._maybe_edit(force=True)

    def mark_success(self) -> None:
        self.set_phase("Finalizing response.", immediate=True)

    def mark_failure(self, detail: str) -> None:
        self.set_phase(detail, immediate=True)

    def set_phase(self, phase: str, immediate: bool = False) -> None:
        with self._lock:
            self.phase = phase
            self.pending_update = True
        if immediate:
            self._maybe_edit(force=True)

    def handle_executor_event(self, event: ExecutorProgressEvent) -> None:
        if event.kind == "turn_started":
            self.set_phase("Architect started reasoning.", immediate=False)
            return
        if event.kind == "reasoning":
            detail = compact_progress_text(event.detail) if event.detail else "Architect is reasoning."
            self.set_phase(detail, immediate=False)
            return
        if event.kind == "agent_message":
            self.set_phase("Architect is preparing the reply.", immediate=False)
            return
        if event.kind == "command_started":
            with self._lock:
                self.commands_started += 1
            command_text = compact_progress_text(event.detail) if event.detail else "shell command"
            self.set_phase(f"Running command: {command_text}", immediate=False)
            return
        if event.kind == "command_completed":
            with self._lock:
                self.commands_completed += 1
            if event.exit_code is None:
                self.set_phase("A command finished.", immediate=False)
            elif event.exit_code == 0:
                self.set_phase("A command finished successfully.", immediate=False)
            else:
                self.set_phase(
                    f"A command finished with exit code {event.exit_code}.",
                    immediate=False,
                )

    def _heartbeat_loop(self) -> None:
        next_typing_at = 0.0
        next_progress_at = 0.0
        while not self._stop_event.is_set():
            now = time.time()
            if now >= next_typing_at:
                self._send_typing()
                next_typing_at = now + PROGRESS_TYPING_INTERVAL_SECONDS
            self._maybe_edit(force=False)
            if now >= next_progress_at:
                self._maybe_edit(force=True)
                next_progress_at = now + PROGRESS_HEARTBEAT_EDIT_SECONDS
            self._stop_event.wait(1.0)

    def _send_typing(self) -> None:
        try:
            self.client.send_chat_action(self.chat_id, action="typing")
        except Exception:
            logging.debug("Failed to send typing action for chat_id=%s", self.chat_id)

    def _render_progress_text(self) -> str:
        elapsed = max(1, int(time.time() - self.started_at))
        with self._lock:
            phase = self.phase
            started = self.commands_started
            completed = self.commands_completed
        text = f"Architect is working... {elapsed}s elapsed.\n{phase}"
        if started > 0:
            text += f"\nCommands done: {completed}/{started}"
        return trim_output(text, TELEGRAM_LIMIT)

    def _maybe_edit(self, force: bool = False) -> None:
        message_id = self.progress_message_id
        if message_id is None:
            return

        with self._lock:
            pending_update = self.pending_update
        if not force and not pending_update:
            return

        now = time.time()
        if not force and now - self.last_edit_at < PROGRESS_EDIT_MIN_INTERVAL_SECONDS:
            return

        text = self._render_progress_text()
        if not force and text == self.last_rendered_text:
            with self._lock:
                self.pending_update = False
            return

        try:
            self.client.edit_message(self.chat_id, message_id, text)
        except RuntimeError as exc:
            if "message is not modified" in str(exc).lower():
                with self._lock:
                    self.pending_update = False
                return
            logging.debug("Failed to edit progress message for chat_id=%s: %s", self.chat_id, exc)
            return
        except Exception:
            logging.debug("Failed to edit progress message for chat_id=%s", self.chat_id)
            return

        self.last_rendered_text = text
        self.last_edit_at = now
        with self._lock:
            self.pending_update = False


def pick_largest_photo_file_id(photo_items: List[object]) -> Optional[str]:
    best_file_id: Optional[str] = None
    best_size = -1
    for item in photo_items:
        if not isinstance(item, dict):
            continue
        file_id = item.get("file_id")
        if not isinstance(file_id, str) or not file_id.strip():
            continue
        file_size = item.get("file_size")
        size_score = file_size if isinstance(file_size, int) else 0
        if size_score >= best_size:
            best_size = size_score
            best_file_id = file_id.strip()
    return best_file_id


def extract_prompt_and_media(
    message: Dict[str, object]
) -> tuple[Optional[str], Optional[str], Optional[str], Optional[DocumentPayload]]:
    text = message.get("text")
    if isinstance(text, str):
        return text, None, None, None

    photo_items = message.get("photo")
    if isinstance(photo_items, list) and photo_items:
        file_id = pick_largest_photo_file_id(photo_items)
        if not file_id:
            return None, None, None, None

        caption = message.get("caption")
        if isinstance(caption, str) and caption.strip():
            return caption, file_id, None, None
        return "Please analyze this image.", file_id, None, None

    voice = message.get("voice")
    if isinstance(voice, dict):
        voice_file_id = voice.get("file_id")
        if not isinstance(voice_file_id, str) or not voice_file_id.strip():
            return None, None, None, None
        caption = message.get("caption")
        if isinstance(caption, str):
            return caption, None, voice_file_id.strip(), None
        return "", None, voice_file_id.strip(), None

    document = message.get("document")
    if isinstance(document, dict):
        file_id = document.get("file_id")
        if not isinstance(file_id, str) or not file_id.strip():
            return None, None, None, None
        file_name = document.get("file_name")
        mime_type = document.get("mime_type")
        payload = DocumentPayload(
            file_id=file_id.strip(),
            file_name=file_name.strip() if isinstance(file_name, str) and file_name.strip() else "unnamed",
            mime_type=mime_type.strip() if isinstance(mime_type, str) and mime_type.strip() else "unknown",
        )
        caption = message.get("caption")
        if isinstance(caption, str) and caption.strip():
            return caption, None, None, payload
        return "Please analyze this file.", None, None, payload

    return None, None, None, None


def download_photo_to_temp(
    client: TelegramClient,
    config,
    photo_file_id: str,
) -> str:
    spec = TelegramFileDownloadSpec(
        file_id=photo_file_id,
        max_bytes=config.max_image_bytes,
        size_label="Image",
        temp_prefix="telegram-bridge-photo-",
        default_suffix=".jpg",
        too_large_label="Image",
    )
    tmp_path, _ = download_telegram_file_to_temp(client, spec)
    return tmp_path


def download_voice_to_temp(
    client: TelegramClient,
    config,
    voice_file_id: str,
) -> str:
    spec = TelegramFileDownloadSpec(
        file_id=voice_file_id,
        max_bytes=config.max_voice_bytes,
        size_label="Voice file",
        temp_prefix="telegram-bridge-voice-",
        default_suffix=".ogg",
        too_large_label="Voice file",
    )
    tmp_path, _ = download_telegram_file_to_temp(client, spec)
    return tmp_path


def download_document_to_temp(
    client: TelegramClient,
    config,
    document: DocumentPayload,
) -> tuple[str, int]:
    spec = TelegramFileDownloadSpec(
        file_id=document.file_id,
        max_bytes=config.max_document_bytes,
        size_label="File",
        temp_prefix="telegram-bridge-file-",
        default_suffix=".bin",
        too_large_label="File",
        suffix_hint=document.file_name,
    )
    return download_telegram_file_to_temp(client, spec)


def build_document_analysis_context(
    document_path: str,
    document: DocumentPayload,
    size_bytes: int,
) -> str:
    return (
        "Attached file context:\n"
        f"- Local path: {document_path}\n"
        f"- Original filename: {document.file_name}\n"
        f"- MIME type: {document.mime_type}\n"
        f"- Size bytes: {size_bytes}\n\n"
        "Read and analyze the file from the local path."
    )


def build_voice_transcribe_command(cmd_template: List[str], voice_path: str) -> List[str]:
    cmd: List[str] = []
    used_placeholder = False
    for arg in cmd_template:
        if "{file}" in arg:
            cmd.append(arg.replace("{file}", voice_path))
            used_placeholder = True
        else:
            cmd.append(arg)
    if not used_placeholder:
        cmd.append(voice_path)
    return cmd


def transcribe_voice(config, voice_path: str) -> str:
    if not config.voice_transcribe_cmd:
        raise RuntimeError("Voice transcription is not configured")

    cmd = build_voice_transcribe_command(config.voice_transcribe_cmd, voice_path)
    logging.info("Running voice transcription command: %s", cmd)
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=config.voice_transcribe_timeout_seconds,
        check=False,
    )
    if result.returncode != 0:
        logging.error(
            "Voice transcription failed returncode=%s stderr=%r",
            result.returncode,
            (result.stderr or "")[-1000:],
        )
        raise RuntimeError("Voice transcription failed")

    transcript = (result.stdout or "").strip()
    if not transcript:
        raise ValueError("Voice transcription output was empty")
    return transcript


def transcribe_voice_for_chat(
    config,
    client: TelegramClient,
    chat_id: int,
    message_id: Optional[int],
    voice_file_id: str,
    echo_transcript: bool = True,
) -> Optional[str]:
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
            voice_path = download_voice_to_temp(client, config, voice_file_id)
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
            transcript = transcribe_voice(config, voice_path)
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

        if echo_transcript:
            try:
                client.send_message(
                    chat_id,
                    f"Voice transcript:\n{transcript}",
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


def build_help_text() -> str:
    return (
        "Available commands:\n"
        "/start - verify bridge connectivity\n"
        "/help or /h - show this message\n"
        "/status - show bridge status and context\n"
        "/reset - clear saved context for this chat\n"
        "/restart - queue a safe bridge restart\n\n"
        "Send text, images, voice notes, or files and Architect will process them."
    )


def build_status_text(state: State, config, chat_id: Optional[int] = None) -> str:
    with state.lock:
        busy_count = len(state.busy_chats)
        restart_requested = state.restart_requested
        restart_in_progress = state.restart_in_progress
        if state.canonical_sessions_enabled:
            thread_count = sum(
                1 for session in state.chat_sessions.values() if session.thread_id.strip()
            )
            worker_count = sum(
                1
                for session in state.chat_sessions.values()
                if session.worker_created_at is not None and session.worker_last_used_at is not None
            )
            has_thread = False
            has_worker = False
            if chat_id is not None:
                session = state.chat_sessions.get(chat_id)
                if session is not None:
                    has_thread = bool(session.thread_id.strip())
                    has_worker = (
                        session.worker_created_at is not None
                        and session.worker_last_used_at is not None
                    )
        else:
            thread_count = len(state.chat_threads)
            worker_count = len(state.worker_sessions)
            has_thread = chat_id in state.chat_threads if chat_id is not None else False
            has_worker = chat_id in state.worker_sessions if chat_id is not None else False

    lines = [
        "Bridge status: online",
        f"Allowed chats: {len(config.allowed_chat_ids)}",
        f"Busy chats: {busy_count}",
        f"Saved contexts: {thread_count}",
        (
            "Persistent workers: "
            f"enabled={config.persistent_workers_enabled} "
            f"active={worker_count}/{config.persistent_workers_max} "
            f"idle_timeout={config.persistent_workers_idle_timeout_seconds}s"
        ),
        f"Safe restart queued: {restart_requested}",
        f"Safe restart in progress: {restart_in_progress}",
    ]

    if chat_id is not None:
        lines.append(f"This chat has saved context: {has_thread}")
        lines.append(f"This chat has worker session: {has_worker}")

    return "\n".join(lines)


def prepare_prompt_input(
    config,
    client: TelegramClient,
    chat_id: int,
    message_id: Optional[int],
    prompt: str,
    photo_file_id: Optional[str],
    voice_file_id: Optional[str],
    document: Optional[DocumentPayload],
    progress: ProgressReporter,
) -> Optional[PreparedPromptInput]:
    prompt_text = prompt.strip()
    image_path: Optional[str] = None
    document_path: Optional[str] = None

    if photo_file_id:
        progress.set_phase("Downloading image from Telegram.")
        try:
            image_path = download_photo_to_temp(client, config, photo_file_id)
        except ValueError as exc:
            logging.warning("Photo rejected for chat_id=%s: %s", chat_id, exc)
            progress.mark_failure("Image request rejected.")
            client.send_message(chat_id, str(exc), reply_to_message_id=message_id)
            return None
        except Exception:
            logging.exception("Photo download failed for chat_id=%s", chat_id)
            progress.mark_failure("Image download failed.")
            client.send_message(
                chat_id,
                config.image_download_error_message,
                reply_to_message_id=message_id,
            )
            return None

    if voice_file_id:
        progress.set_phase("Transcribing voice message.")
        transcript = transcribe_voice_for_chat(
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
        if prompt_text:
            prompt_text = f"{prompt_text}\n\nVoice transcript:\n{transcript}"
        else:
            prompt_text = transcript

    if document:
        progress.set_phase("Downloading file from Telegram.")
        try:
            document_path, file_size = download_document_to_temp(client, config, document)
        except ValueError as exc:
            logging.warning("Document rejected for chat_id=%s: %s", chat_id, exc)
            progress.mark_failure("File request rejected.")
            client.send_message(chat_id, str(exc), reply_to_message_id=message_id)
            return None
        except Exception:
            logging.exception("Document download failed for chat_id=%s", chat_id)
            progress.mark_failure("File download failed.")
            client.send_message(
                chat_id,
                config.document_download_error_message,
                reply_to_message_id=message_id,
            )
            return None

        context = build_document_analysis_context(document_path, document, file_size)
        if prompt_text:
            prompt_text = f"{prompt_text}\n\n{context}"
        else:
            prompt_text = context

    if not prompt_text:
        progress.mark_failure("No prompt content to execute.")
        return None

    if len(prompt_text) > config.max_input_chars:
        progress.mark_failure("Input rejected as too long.")
        client.send_message(
            chat_id,
            f"Input too long ({len(prompt_text)} chars). Max is {config.max_input_chars}.",
            reply_to_message_id=message_id,
        )
        return None

    return PreparedPromptInput(
        prompt_text=prompt_text,
        image_path=image_path,
        document_path=document_path,
    )


def execute_prompt_with_retry(
    state_repo: StateRepository,
    config,
    client: TelegramClient,
    chat_id: int,
    message_id: Optional[int],
    prompt_text: str,
    previous_thread_id: Optional[str],
    image_path: Optional[str],
    progress: ProgressReporter,
) -> Optional[subprocess.CompletedProcess[str]]:
    allow_automatic_retry = config.persistent_workers_enabled
    retry_attempted = False
    attempt_thread_id: Optional[str] = previous_thread_id

    while True:
        try:
            result = run_executor(
                config,
                prompt_text,
                attempt_thread_id,
                image_path=image_path,
                progress_callback=progress.handle_executor_event,
            )
        except subprocess.TimeoutExpired:
            logging.warning("Executor timeout for chat_id=%s", chat_id)
            progress.mark_failure("Execution timed out.")
            client.send_message(chat_id, config.timeout_message, reply_to_message_id=message_id)
            return None
        except FileNotFoundError:
            logging.exception("Executor command not found: %s", config.executor_cmd)
            progress.mark_failure("Executor command not found.")
            client.send_message(
                chat_id,
                config.generic_error_message,
                reply_to_message_id=message_id,
            )
            return None
        except Exception:
            logging.exception("Unexpected executor error for chat_id=%s", chat_id)
            if allow_automatic_retry and not retry_attempted:
                retry_attempted = True
                state_repo.clear_thread_id(chat_id)
                attempt_thread_id = None
                progress.set_phase("Execution failed. Retrying once with a new session.")
                continue
            progress.mark_failure("Execution failed before completion.")
            if allow_automatic_retry:
                client.send_message(
                    chat_id,
                    "Execution failed after an automatic retry. Please resend your request.",
                    reply_to_message_id=message_id,
                )
            else:
                client.send_message(
                    chat_id,
                    config.generic_error_message,
                    reply_to_message_id=message_id,
                )
            return None

        if result.returncode == 0:
            return result

        reset_and_retry_new = False
        if attempt_thread_id and should_reset_thread_after_resume_failure(
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
            progress.set_phase("Retrying as a new Architect session.")
        elif allow_automatic_retry and not retry_attempted:
            logging.warning(
                "Executor failed for chat_id=%s; retrying once as new. returncode=%s stderr=%r",
                chat_id,
                result.returncode,
                (result.stderr or "")[-1000:],
            )
            reset_and_retry_new = True
            retry_attempted = True
            progress.set_phase("Execution failed. Retrying once with a new session.")

        if reset_and_retry_new:
            state_repo.clear_thread_id(chat_id)
            attempt_thread_id = None
            retry_attempted = True
            continue

        logging.error(
            "Executor failed for chat_id=%s returncode=%s stderr=%r",
            chat_id,
            result.returncode,
            (result.stderr or "")[-1000:],
        )
        progress.mark_failure("Execution failed.")
        if allow_automatic_retry:
            client.send_message(
                chat_id,
                "Execution failed after an automatic retry. Please resend your request.",
                reply_to_message_id=message_id,
            )
        else:
            client.send_message(
                chat_id,
                config.generic_error_message,
                reply_to_message_id=message_id,
            )
        return None


def finalize_prompt_success(
    state_repo: StateRepository,
    config,
    client: TelegramClient,
    chat_id: int,
    message_id: Optional[int],
    result: subprocess.CompletedProcess[str],
    progress: ProgressReporter,
) -> None:
    new_thread_id, output = parse_executor_output(result.stdout or "")
    if new_thread_id:
        state_repo.set_thread_id(chat_id, new_thread_id)
    if not output:
        output = config.empty_output_message
    output = trim_output(output, config.max_output_chars)
    progress.mark_success()
    client.send_message(chat_id, output, reply_to_message_id=message_id)


def process_prompt(
    state: State,
    config,
    client: TelegramClient,
    chat_id: int,
    message_id: Optional[int],
    prompt: str,
    photo_file_id: Optional[str],
    voice_file_id: Optional[str],
    document: Optional[DocumentPayload],
) -> None:
    state_repo = StateRepository(state)
    previous_thread_id = state_repo.get_thread_id(chat_id)
    image_path: Optional[str] = None
    document_path: Optional[str] = None
    progress = ProgressReporter(client, chat_id, message_id)
    try:
        progress.start()
        prepared = prepare_prompt_input(
            config=config,
            client=client,
            chat_id=chat_id,
            message_id=message_id,
            prompt=prompt,
            photo_file_id=photo_file_id,
            voice_file_id=voice_file_id,
            document=document,
            progress=progress,
        )
        if prepared is None:
            return
        image_path = prepared.image_path
        document_path = prepared.document_path
        progress.set_phase("Sending request to Architect.")
        result = execute_prompt_with_retry(
            state_repo=state_repo,
            config=config,
            client=client,
            chat_id=chat_id,
            message_id=message_id,
            prompt_text=prepared.prompt_text,
            previous_thread_id=previous_thread_id,
            image_path=image_path,
            progress=progress,
        )
        if result is None:
            return
        finalize_prompt_success(
            state_repo=state_repo,
            config=config,
            client=client,
            chat_id=chat_id,
            message_id=message_id,
            result=result,
            progress=progress,
        )
    finally:
        progress.close()
        if image_path:
            try:
                os.remove(image_path)
            except OSError:
                logging.warning("Failed to remove temp image file: %s", image_path)
        if document_path:
            try:
                os.remove(document_path)
            except OSError:
                logging.warning("Failed to remove temp file: %s", document_path)
        finalize_chat_work(state, client, chat_id)


def process_message_worker(
    state: State,
    config,
    client: TelegramClient,
    chat_id: int,
    message_id: Optional[int],
    prompt: str,
    photo_file_id: Optional[str],
    voice_file_id: Optional[str],
    document: Optional[DocumentPayload],
) -> None:
    try:
        process_prompt(
            state,
            config,
            client,
            chat_id,
            message_id,
            prompt,
            photo_file_id,
            voice_file_id,
            document,
        )
    except Exception:
        logging.exception("Unexpected message worker error for chat_id=%s", chat_id)
        try:
            client.send_message(
                chat_id,
                config.generic_error_message,
                reply_to_message_id=message_id,
            )
        except Exception:
            logging.exception("Failed to send worker error response for chat_id=%s", chat_id)


def handle_reset_command(
    state: State,
    config,
    client: TelegramClient,
    chat_id: int,
    message_id: Optional[int],
) -> None:
    state_repo = StateRepository(state)
    removed_thread = state_repo.clear_thread_id(chat_id)
    removed_worker = state_repo.clear_worker_session(chat_id) if config.persistent_workers_enabled else False
    if removed_thread or removed_worker:
        client.send_message(
            chat_id,
            "Context reset. Your next message starts a new conversation.",
            reply_to_message_id=message_id,
        )
        return
    client.send_message(
        chat_id,
        "No saved context was found for this chat.",
        reply_to_message_id=message_id,
    )


def handle_restart_command(
    state: State,
    client: TelegramClient,
    chat_id: int,
    message_id: Optional[int],
) -> None:
    status, busy_count = request_safe_restart(state, chat_id, message_id)
    if status == "in_progress":
        client.send_message(
            chat_id,
            "Restart is already in progress.",
            reply_to_message_id=message_id,
        )
        return
    if status == "already_queued":
        client.send_message(
            chat_id,
            "Restart is already queued and will run after current work completes.",
            reply_to_message_id=message_id,
        )
        return
    if status == "queued":
        client.send_message(
            chat_id,
            f"Safe restart queued. Waiting for {busy_count} active request(s) to finish.",
            reply_to_message_id=message_id,
        )
        return

    client.send_message(
        chat_id,
        "No active request. Restarting bridge now.",
        reply_to_message_id=message_id,
    )
    trigger_restart_async(state, client, chat_id, message_id)


def handle_update(
    state: State,
    config,
    client: TelegramClient,
    update: Dict[str, object],
) -> None:
    state_repo = StateRepository(state)
    message = update.get("message")
    if not isinstance(message, dict):
        return

    chat = message.get("chat")
    if not isinstance(chat, dict):
        return

    chat_id = chat.get("id")
    if not isinstance(chat_id, int):
        return

    message_id = message.get("message_id")
    if not isinstance(message_id, int):
        message_id = None

    if chat_id not in config.allowed_chat_ids:
        logging.warning("Denied non-allowlisted chat_id=%s", chat_id)
        client.send_message(chat_id, config.denied_message, reply_to_message_id=message_id)
        return

    prompt_input, photo_file_id, voice_file_id, document = extract_prompt_and_media(message)
    if prompt_input is None and voice_file_id is None and document is None:
        return

    command = normalize_command(prompt_input or "")
    if command == "/start":
        client.send_message(
            chat_id,
            "Telegram Architect bridge is online. Send a prompt to begin.",
            reply_to_message_id=message_id,
        )
        return
    if command in ("/help", "/h"):
        client.send_message(
            chat_id,
            build_help_text(),
            reply_to_message_id=message_id,
        )
        return
    if command == "/status":
        client.send_message(
            chat_id,
            build_status_text(state, config, chat_id=chat_id),
            reply_to_message_id=message_id,
        )
        return
    if command == "/restart":
        handle_restart_command(state, client, chat_id, message_id)
        return
    if command == "/reset":
        handle_reset_command(state, config, client, chat_id, message_id)
        return

    prompt = (prompt_input or "").strip()
    if not prompt and not voice_file_id and document is None:
        return

    if prompt and len(prompt) > config.max_input_chars:
        client.send_message(
            chat_id,
            f"Input too long ({len(prompt)} chars). Max is {config.max_input_chars}.",
            reply_to_message_id=message_id,
        )
        return

    if is_rate_limited(state, config, chat_id):
        client.send_message(
            chat_id,
            "Rate limit exceeded. Please wait a minute and retry.",
            reply_to_message_id=message_id,
        )
        return

    if not ensure_chat_worker_session(state, config, client, chat_id, message_id):
        return

    if not mark_busy(state, chat_id):
        client.send_message(
            chat_id,
            config.busy_message,
            reply_to_message_id=message_id,
        )
        return
    state_repo.mark_in_flight_request(chat_id, message_id)

    worker = threading.Thread(
        target=process_message_worker,
        args=(
            state,
            config,
            client,
            chat_id,
            message_id,
            prompt,
            photo_file_id,
            voice_file_id,
            document,
        ),
        daemon=True,
    )
    worker.start()
