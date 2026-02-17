#!/usr/bin/env python3
"""Telegram long-poll bridge to local Architect/Codex CLI."""

import argparse
import json
import logging
import os
import secrets
import shlex
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from ha_control import (
    HAConfig,
    HAControlError,
    HomeAssistantClient,
    build_pending_message,
    execute_action,
    is_ha_network_error,
    load_ha_config,
    now_ts,
    parse_approval_command,
    plan_action_from_text,
)

TELEGRAM_LIMIT = 4096
OUTPUT_BEGIN_MARKER = "OUTPUT_BEGIN"


@dataclass
class Config:
    token: str
    allowed_chat_ids: Set[int]
    api_base: str
    poll_timeout_seconds: int
    retry_sleep_seconds: float
    exec_timeout_seconds: int
    max_input_chars: int
    max_output_chars: int
    max_image_bytes: int
    max_voice_bytes: int
    rate_limit_per_minute: int
    executor_cmd: List[str]
    voice_transcribe_cmd: List[str]
    voice_transcribe_timeout_seconds: int
    state_dir: str
    ha_config: Optional[HAConfig]
    busy_message: str = "Another request is still running. Please wait."
    denied_message: str = "Access denied for this chat."
    timeout_message: str = "Request timed out. Please try a shorter prompt."
    generic_error_message: str = "Execution failed. Please try again later."
    image_download_error_message: str = "Image download failed. Please send another image."
    voice_download_error_message: str = "Voice download failed. Please send another voice message."
    voice_not_configured_message: str = (
        "Voice transcription is not configured. Please ask admin to set TELEGRAM_VOICE_TRANSCRIBE_CMD."
    )
    voice_transcribe_error_message: str = "Voice transcription failed. Please send clearer audio."
    voice_transcribe_empty_message: str = (
        "Voice transcription was empty. Please send clearer audio."
    )
    empty_output_message: str = "(No output from Architect)"
    thinking_message: str = "💭🤔💭.....thinking.....💭🤔💭"


@dataclass
class State:
    started_at: float = field(default_factory=time.time)
    busy_chats: Set[int] = field(default_factory=set)
    recent_requests: Dict[int, List[float]] = field(default_factory=dict)
    chat_threads: Dict[int, str] = field(default_factory=dict)
    chat_thread_path: str = ""
    pending_actions: Dict[int, Dict[str, object]] = field(default_factory=dict)
    pending_action_path: str = ""
    lock: threading.Lock = field(default_factory=threading.Lock)


def parse_int_env(name: str, default: int, minimum: int = 1) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if parsed < minimum:
        raise ValueError(f"{name} must be >= {minimum}")
    return parsed


def parse_allowed_chat_ids(raw: str) -> Set[int]:
    values = [item.strip() for item in raw.split(",") if item.strip()]
    if not values:
        raise ValueError("TELEGRAM_ALLOWED_CHAT_IDS is empty")
    parsed: Set[int] = set()
    for value in values:
        try:
            parsed.add(int(value))
        except ValueError as exc:
            raise ValueError(
                f"Invalid TELEGRAM_ALLOWED_CHAT_IDS value: {value!r}"
            ) from exc
    return parsed


def build_default_executor() -> str:
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    return os.path.join(repo_root, "src", "telegram_bridge", "executor.sh")


def parse_executor_cmd() -> List[str]:
    raw = os.getenv("TELEGRAM_EXECUTOR_CMD", "").strip()
    if raw:
        cmd = shlex.split(raw)
        if not cmd:
            raise ValueError("TELEGRAM_EXECUTOR_CMD cannot be blank")
        return cmd
    return [build_default_executor()]


def parse_optional_cmd_env(name: str) -> List[str]:
    raw = os.getenv(name, "").strip()
    if not raw:
        return []
    cmd = shlex.split(raw)
    if not cmd:
        raise ValueError(f"{name} cannot be blank")
    return cmd


def load_config() -> Config:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN is required")

    raw_chat_ids = os.getenv("TELEGRAM_ALLOWED_CHAT_IDS", "").strip()
    if not raw_chat_ids:
        raise ValueError("TELEGRAM_ALLOWED_CHAT_IDS is required")
    state_dir = os.getenv(
        "TELEGRAM_BRIDGE_STATE_DIR",
        "/home/architect/.local/state/telegram-architect-bridge",
    ).strip()
    if not state_dir:
        raise ValueError("TELEGRAM_BRIDGE_STATE_DIR cannot be empty")
    ha_config = load_ha_config(state_dir)

    return Config(
        token=token,
        allowed_chat_ids=parse_allowed_chat_ids(raw_chat_ids),
        api_base=os.getenv("TELEGRAM_API_BASE", "https://api.telegram.org").rstrip("/"),
        poll_timeout_seconds=parse_int_env("TELEGRAM_POLL_TIMEOUT_SECONDS", 30),
        retry_sleep_seconds=float(os.getenv("TELEGRAM_RETRY_SLEEP_SECONDS", "3")),
        exec_timeout_seconds=parse_int_env("TELEGRAM_EXEC_TIMEOUT_SECONDS", 300),
        max_input_chars=parse_int_env("TELEGRAM_MAX_INPUT_CHARS", TELEGRAM_LIMIT),
        max_output_chars=parse_int_env("TELEGRAM_MAX_OUTPUT_CHARS", 20000),
        max_image_bytes=parse_int_env("TELEGRAM_MAX_IMAGE_BYTES", 10 * 1024 * 1024, minimum=1024),
        max_voice_bytes=parse_int_env("TELEGRAM_MAX_VOICE_BYTES", 20 * 1024 * 1024, minimum=1024),
        rate_limit_per_minute=parse_int_env("TELEGRAM_RATE_LIMIT_PER_MINUTE", 12),
        executor_cmd=parse_executor_cmd(),
        voice_transcribe_cmd=parse_optional_cmd_env("TELEGRAM_VOICE_TRANSCRIBE_CMD"),
        voice_transcribe_timeout_seconds=parse_int_env(
            "TELEGRAM_VOICE_TRANSCRIBE_TIMEOUT_SECONDS",
            120,
        ),
        state_dir=state_dir,
        ha_config=ha_config,
    )


class TelegramClient:
    def __init__(self, config: Config) -> None:
        self.config = config

    def _request(self, method: str, payload: Dict[str, object]) -> Dict[str, object]:
        endpoint = f"{self.config.api_base}/bot{self.config.token}/{method}"
        data = urlencode(payload).encode("utf-8")
        request = Request(endpoint, data=data, method="POST")
        with urlopen(request, timeout=self.config.poll_timeout_seconds + 10) as response:
            body = response.read().decode("utf-8")
        decoded = json.loads(body)
        if not decoded.get("ok"):
            description = decoded.get("description", "unknown Telegram error")
            raise RuntimeError(f"Telegram API {method} failed: {description}")
        return decoded

    def get_updates(
        self,
        offset: int,
        timeout_seconds: Optional[int] = None,
    ) -> List[Dict[str, object]]:
        timeout = self.config.poll_timeout_seconds if timeout_seconds is None else timeout_seconds
        payload: Dict[str, object] = {
            "offset": offset,
            "timeout": timeout,
            "allowed_updates": json.dumps(["message"]),
        }
        response = self._request("getUpdates", payload)
        result = response.get("result", [])
        if not isinstance(result, list):
            raise RuntimeError("Invalid getUpdates response: result is not a list")
        return result

    def send_message(
        self,
        chat_id: int,
        text: str,
        reply_to_message_id: Optional[int] = None,
    ) -> None:
        for chunk in to_telegram_chunks(text):
            payload: Dict[str, object] = {
                "chat_id": str(chat_id),
                "text": chunk,
                "disable_web_page_preview": "true",
            }
            if reply_to_message_id is not None:
                payload["reply_to_message_id"] = str(reply_to_message_id)
            self._request("sendMessage", payload)

    def get_file(self, file_id: str) -> Dict[str, object]:
        response = self._request("getFile", {"file_id": file_id})
        result = response.get("result")
        if not isinstance(result, dict):
            raise RuntimeError("Invalid getFile response: result is not an object")
        return result

    def download_file_to_path(
        self,
        file_path: str,
        target_path: str,
        max_bytes: int,
        size_label: str = "File",
    ) -> None:
        cleaned = file_path.lstrip("/")
        if not cleaned:
            raise RuntimeError("Invalid Telegram file_path")
        encoded = quote(cleaned, safe="/")
        endpoint = f"{self.config.api_base}/file/bot{self.config.token}/{encoded}"
        request = Request(endpoint, method="GET")

        total = 0
        with (
            urlopen(request, timeout=self.config.poll_timeout_seconds + 10) as response,
            open(target_path, "wb") as handle,
        ):
            while True:
                chunk = response.read(64 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise ValueError(
                        f"{size_label} too large (> {max_bytes} bytes)."
                    )
                handle.write(chunk)


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


def split_for_limit(text: str, limit: int) -> List[str]:
    if not text:
        return [""]
    chunks: List[str] = []
    remaining = text
    while remaining:
        if len(remaining) <= limit:
            chunks.append(remaining)
            break
        split_at = remaining.rfind("\n", 0, limit)
        if split_at <= 0:
            split_at = limit
        chunks.append(remaining[:split_at])
        remaining = remaining[split_at:].lstrip("\n")
    return chunks


def to_telegram_chunks(text: str) -> List[str]:
    stripped = text.strip()
    if not stripped:
        return [""]

    # Reserve room for a multipart prefix like [2/7]\n
    base_chunks = split_for_limit(stripped, TELEGRAM_LIMIT - 16)
    if len(base_chunks) == 1:
        return base_chunks

    total = len(base_chunks)
    output: List[str] = []
    for index, chunk in enumerate(base_chunks, start=1):
        output.append(f"[{index}/{total}]\n{chunk}")
    return output


def run_executor(
    config: Config,
    prompt: str,
    thread_id: Optional[str],
    image_path: Optional[str] = None,
) -> subprocess.CompletedProcess[str]:
    cmd = list(config.executor_cmd)
    if thread_id:
        cmd.extend(["resume", thread_id])
    else:
        cmd.append("new")
    if image_path:
        cmd.extend(["--image", image_path])
    logging.info("Running executor command: %s", cmd)
    return subprocess.run(
        cmd,
        input=prompt,
        capture_output=True,
        text=True,
        timeout=config.exec_timeout_seconds,
        check=False,
    )


def is_rate_limited(state: State, config: Config, chat_id: int) -> bool:
    now = time.time()
    with state.lock:
        entries = state.recent_requests.setdefault(chat_id, [])
        threshold = now - 60
        entries[:] = [t for t in entries if t >= threshold]
        if len(entries) >= config.rate_limit_per_minute:
            return True
        entries.append(now)
    return False


def mark_busy(state: State, chat_id: int) -> bool:
    with state.lock:
        if chat_id in state.busy_chats:
            return False
        state.busy_chats.add(chat_id)
    return True


def clear_busy(state: State, chat_id: int) -> None:
    with state.lock:
        state.busy_chats.discard(chat_id)


def ensure_state_dir(path: str) -> None:
    Path(path).mkdir(parents=True, exist_ok=True)


def load_chat_threads(path: str) -> Dict[int, str]:
    data_path = Path(path)
    if not data_path.exists():
        return {}
    try:
        raw = json.loads(data_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"Failed to parse chat thread state {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError(f"Invalid chat thread state {path}: root is not object")
    parsed: Dict[int, str] = {}
    for key, value in raw.items():
        if not isinstance(value, str) or not value.strip():
            continue
        try:
            chat_id = int(key)
        except ValueError:
            continue
        parsed[chat_id] = value.strip()
    return parsed


def persist_chat_threads(state: State) -> None:
    if not state.chat_thread_path:
        return
    path = Path(state.chat_thread_path)
    tmp_path = path.with_suffix(".tmp")
    with state.lock:
        serialized = {str(chat_id): thread_id for chat_id, thread_id in state.chat_threads.items()}
    tmp_path.write_text(json.dumps(serialized, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp_path.replace(path)


def get_thread_id(state: State, chat_id: int) -> Optional[str]:
    with state.lock:
        return state.chat_threads.get(chat_id)


def set_thread_id(state: State, chat_id: int, thread_id: str) -> None:
    with state.lock:
        state.chat_threads[chat_id] = thread_id
    persist_chat_threads(state)


def clear_thread_id(state: State, chat_id: int) -> bool:
    removed = False
    with state.lock:
        if chat_id in state.chat_threads:
            del state.chat_threads[chat_id]
            removed = True
    if removed:
        persist_chat_threads(state)
    return removed


def load_pending_actions(path: str) -> Dict[int, Dict[str, object]]:
    data_path = Path(path)
    if not data_path.exists():
        return {}
    try:
        raw = json.loads(data_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"Failed to parse pending action state {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError(f"Invalid pending action state {path}: root is not object")

    out: Dict[int, Dict[str, object]] = {}
    now = now_ts()
    for key, value in raw.items():
        if not isinstance(value, dict):
            continue
        try:
            chat_id = int(key)
        except ValueError:
            continue
        code = value.get("code")
        summary = value.get("summary")
        action = value.get("action")
        expires_at = value.get("expires_at")
        if not isinstance(code, str) or not code:
            continue
        if not isinstance(summary, str) or not summary:
            continue
        if not isinstance(action, dict):
            continue
        if not isinstance(expires_at, (int, float)) or float(expires_at) <= now:
            continue
        out[chat_id] = {
            "code": code.upper(),
            "summary": summary,
            "action": action,
            "created_at": float(value.get("created_at", now)),
            "expires_at": float(expires_at),
        }
    return out


def persist_pending_actions(state: State) -> None:
    if not state.pending_action_path:
        return
    path = Path(state.pending_action_path)
    tmp_path = path.with_suffix(".tmp")
    with state.lock:
        serialized = {
            str(chat_id): payload
            for chat_id, payload in state.pending_actions.items()
        }
    tmp_path.write_text(
        json.dumps(serialized, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    tmp_path.replace(path)


def get_pending_action(state: State, chat_id: int) -> Optional[Dict[str, object]]:
    with state.lock:
        payload = state.pending_actions.get(chat_id)
        if not payload:
            return None
        return dict(payload)


def set_pending_action(state: State, chat_id: int, payload: Dict[str, object]) -> None:
    with state.lock:
        state.pending_actions[chat_id] = dict(payload)
    persist_pending_actions(state)


def clear_pending_action(state: State, chat_id: int) -> bool:
    removed = False
    with state.lock:
        if chat_id in state.pending_actions:
            del state.pending_actions[chat_id]
            removed = True
    if removed:
        persist_pending_actions(state)
    return removed


def prune_expired_pending_actions(state: State) -> None:
    now = now_ts()
    changed = False
    with state.lock:
        expired = [
            chat_id
            for chat_id, payload in state.pending_actions.items()
            if not isinstance(payload.get("expires_at"), (int, float))
            or float(payload.get("expires_at")) <= now
        ]
        for chat_id in expired:
            del state.pending_actions[chat_id]
            changed = True
    if changed:
        persist_pending_actions(state)


def generate_approval_code(length: int = 6) -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(length))


def parse_executor_output(stdout: str) -> tuple[Optional[str], str]:
    lines = (stdout or "").splitlines()
    thread_id: Optional[str] = None
    output_lines: List[str] = []
    seen_output = False
    for line in lines:
        if not seen_output:
            if line.startswith("THREAD_ID="):
                thread_id = line[len("THREAD_ID="):].strip()
                continue
            if line.strip() == OUTPUT_BEGIN_MARKER:
                seen_output = True
                continue
        else:
            output_lines.append(line)

    if seen_output:
        output = "\n".join(output_lines).strip()
    else:
        output = (stdout or "").strip()
    return thread_id, output


def should_reset_thread_after_resume_failure(
    stderr: str,
    stdout: str,
) -> bool:
    combined = f"{stderr}\n{stdout}".lower()
    reset_markers = (
        "thread not found",
        "unknown thread",
        "invalid thread",
        "thread id not found",
        "conversation not found",
        "session not found",
        "no such thread",
        "could not find thread",
    )
    return any(marker in combined for marker in reset_markers)


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
) -> tuple[Optional[str], Optional[str], Optional[str]]:
    text = message.get("text")
    if isinstance(text, str):
        return text, None, None

    photo_items = message.get("photo")
    if isinstance(photo_items, list) and photo_items:
        file_id = pick_largest_photo_file_id(photo_items)
        if not file_id:
            return None, None, None

        caption = message.get("caption")
        if isinstance(caption, str) and caption.strip():
            return caption, file_id, None
        return "Please analyze this image.", file_id, None

    voice = message.get("voice")
    if isinstance(voice, dict):
        voice_file_id = voice.get("file_id")
        if not isinstance(voice_file_id, str) or not voice_file_id.strip():
            return None, None, None
        caption = message.get("caption")
        if isinstance(caption, str):
            return caption, None, voice_file_id.strip()
        return "", None, voice_file_id.strip()

    return None, None, None


def download_photo_to_temp(
    client: TelegramClient,
    config: Config,
    photo_file_id: str,
) -> str:
    file_meta = client.get_file(photo_file_id)
    file_path = file_meta.get("file_path")
    if not isinstance(file_path, str) or not file_path.strip():
        raise RuntimeError("Telegram getFile response missing file_path")

    file_size = file_meta.get("file_size")
    if isinstance(file_size, int) and file_size > config.max_image_bytes:
        raise ValueError(
            f"Image too large ({file_size} bytes). Max is {config.max_image_bytes} bytes."
        )

    suffix = Path(file_path).suffix or ".jpg"
    fd, tmp_path = tempfile.mkstemp(prefix="telegram-bridge-photo-", suffix=suffix)
    os.close(fd)
    try:
        client.download_file_to_path(
            file_path,
            tmp_path,
            config.max_image_bytes,
            size_label="Image",
        )
    except Exception:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise
    return tmp_path


def download_voice_to_temp(
    client: TelegramClient,
    config: Config,
    voice_file_id: str,
) -> str:
    file_meta = client.get_file(voice_file_id)
    file_path = file_meta.get("file_path")
    if not isinstance(file_path, str) or not file_path.strip():
        raise RuntimeError("Telegram getFile response missing file_path")

    file_size = file_meta.get("file_size")
    if isinstance(file_size, int) and file_size > config.max_voice_bytes:
        raise ValueError(
            f"Voice file too large ({file_size} bytes). Max is {config.max_voice_bytes} bytes."
        )

    suffix = Path(file_path).suffix or ".ogg"
    fd, tmp_path = tempfile.mkstemp(prefix="telegram-bridge-voice-", suffix=suffix)
    os.close(fd)
    try:
        client.download_file_to_path(
            file_path,
            tmp_path,
            config.max_voice_bytes,
            size_label="Voice file",
        )
    except Exception:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise
    return tmp_path


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


def transcribe_voice(config: Config, voice_path: str) -> str:
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


def build_help_text() -> str:
    return (
        "Commands:\n"
        "/start - bridge intro\n"
        "/help - show commands\n"
        "/status - show bridge health\n"
        "/reset - clear chat context\n\n"
        "Home Assistant confirmations:\n"
        "APPROVE <code> - execute pending HA action\n"
        "CANCEL <code> - cancel pending HA action\n\n"
        "Any other text, photo, or voice message is sent to Architect."
    )


def build_status_text(state: State) -> str:
    uptime = int(time.time() - state.started_at)
    with state.lock:
        busy_count = len(state.busy_chats)
        pending_count = len(state.pending_actions)
    return (
        "Bridge status: healthy\n"
        f"Uptime: {uptime}s\n"
        f"Busy chats: {busy_count}\n"
        f"Pending HA approvals: {pending_count}"
    )


def process_prompt(
    state: State,
    config: Config,
    client: TelegramClient,
    chat_id: int,
    message_id: Optional[int],
    prompt: str,
    photo_file_id: Optional[str],
    voice_file_id: Optional[str],
) -> None:
    previous_thread_id = get_thread_id(state, chat_id)
    prompt_text = prompt.strip()
    image_path: Optional[str] = None
    voice_path: Optional[str] = None
    try:
        if photo_file_id:
            try:
                image_path = download_photo_to_temp(client, config, photo_file_id)
            except ValueError as exc:
                logging.warning("Photo rejected for chat_id=%s: %s", chat_id, exc)
                client.send_message(chat_id, str(exc), reply_to_message_id=message_id)
                return
            except Exception:
                logging.exception("Photo download failed for chat_id=%s", chat_id)
                client.send_message(
                    chat_id,
                    config.image_download_error_message,
                    reply_to_message_id=message_id,
                )
                return

        if voice_file_id:
            if not config.voice_transcribe_cmd:
                client.send_message(
                    chat_id,
                    config.voice_not_configured_message,
                    reply_to_message_id=message_id,
                )
                return
            try:
                voice_path = download_voice_to_temp(client, config, voice_file_id)
            except ValueError as exc:
                logging.warning("Voice rejected for chat_id=%s: %s", chat_id, exc)
                client.send_message(chat_id, str(exc), reply_to_message_id=message_id)
                return
            except Exception:
                logging.exception("Voice download failed for chat_id=%s", chat_id)
                client.send_message(
                    chat_id,
                    config.voice_download_error_message,
                    reply_to_message_id=message_id,
                )
                return

            try:
                transcript = transcribe_voice(config, voice_path)
            except subprocess.TimeoutExpired:
                logging.warning("Voice transcription timeout for chat_id=%s", chat_id)
                client.send_message(
                    chat_id,
                    config.timeout_message,
                    reply_to_message_id=message_id,
                )
                return
            except ValueError:
                logging.warning("Voice transcription was empty for chat_id=%s", chat_id)
                client.send_message(
                    chat_id,
                    config.voice_transcribe_empty_message,
                    reply_to_message_id=message_id,
                )
                return
            except RuntimeError:
                client.send_message(
                    chat_id,
                    config.voice_transcribe_error_message,
                    reply_to_message_id=message_id,
                )
                return
            except Exception:
                logging.exception("Unexpected voice transcription error for chat_id=%s", chat_id)
                client.send_message(
                    chat_id,
                    config.voice_transcribe_error_message,
                    reply_to_message_id=message_id,
                )
                return

            if prompt_text:
                prompt_text = f"{prompt_text}\n\nVoice transcript:\n{transcript}"
            else:
                prompt_text = transcript

        if not prompt_text:
            return

        if len(prompt_text) > config.max_input_chars:
            client.send_message(
                chat_id,
                f"Input too long ({len(prompt_text)} chars). Max is {config.max_input_chars}.",
                reply_to_message_id=message_id,
            )
            return

        try:
            result = run_executor(config, prompt_text, previous_thread_id, image_path=image_path)
        except subprocess.TimeoutExpired:
            logging.warning("Executor timeout for chat_id=%s", chat_id)
            client.send_message(chat_id, config.timeout_message, reply_to_message_id=message_id)
            return
        except FileNotFoundError:
            logging.exception("Executor command not found: %s", config.executor_cmd)
            client.send_message(
                chat_id,
                config.generic_error_message,
                reply_to_message_id=message_id,
            )
            return
        except Exception:
            logging.exception("Unexpected executor error for chat_id=%s", chat_id)
            client.send_message(
                chat_id,
                config.generic_error_message,
                reply_to_message_id=message_id,
            )
            return

        if result.returncode != 0:
            if previous_thread_id:
                if should_reset_thread_after_resume_failure(
                    result.stderr or "",
                    result.stdout or "",
                ):
                    logging.warning(
                        "Executor failed for chat_id=%s on resume due to invalid thread; "
                        "clearing thread and retrying as new. stderr=%r",
                        chat_id,
                        (result.stderr or "")[-1000:],
                    )
                    clear_thread_id(state, chat_id)
                    try:
                        retry = run_executor(config, prompt_text, None, image_path=image_path)
                    except subprocess.TimeoutExpired:
                        logging.warning("Executor retry timeout for chat_id=%s", chat_id)
                        client.send_message(
                            chat_id,
                            config.timeout_message,
                            reply_to_message_id=message_id,
                        )
                        return
                    except Exception:
                        logging.exception("Executor retry error for chat_id=%s", chat_id)
                        client.send_message(
                            chat_id,
                            config.generic_error_message,
                            reply_to_message_id=message_id,
                        )
                        return
                    if retry.returncode != 0:
                        logging.error(
                            "Executor retry failed for chat_id=%s returncode=%s stderr=%r",
                            chat_id,
                            retry.returncode,
                            retry.stderr[-1000:],
                        )
                        client.send_message(
                            chat_id,
                            config.generic_error_message,
                            reply_to_message_id=message_id,
                        )
                        return
                    result = retry
                else:
                    logging.error(
                        "Executor failed for chat_id=%s on resume; preserving saved thread_id. "
                        "returncode=%s stderr=%r",
                        chat_id,
                        result.returncode,
                        (result.stderr or "")[-1000:],
                    )
                    client.send_message(
                        chat_id,
                        config.generic_error_message,
                        reply_to_message_id=message_id,
                    )
                    return
            else:
                logging.error(
                    "Executor failed for chat_id=%s returncode=%s stderr=%r",
                    chat_id,
                    result.returncode,
                    result.stderr[-1000:],
                )
                client.send_message(
                    chat_id,
                    config.generic_error_message,
                    reply_to_message_id=message_id,
                )
                return

        new_thread_id, output = parse_executor_output(result.stdout or "")
        if new_thread_id:
            set_thread_id(state, chat_id, new_thread_id)
        if not output:
            output = config.empty_output_message
        output = trim_output(output, config.max_output_chars)
        client.send_message(chat_id, output, reply_to_message_id=message_id)
    finally:
        if image_path:
            try:
                os.remove(image_path)
            except OSError:
                logging.warning("Failed to remove temp image file: %s", image_path)
        if voice_path:
            try:
                os.remove(voice_path)
            except OSError:
                logging.warning("Failed to remove temp voice file: %s", voice_path)
        clear_busy(state, chat_id)


def handle_reset_command(
    state: State,
    client: TelegramClient,
    chat_id: int,
    message_id: Optional[int],
) -> None:
    if clear_thread_id(state, chat_id):
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


def handle_ha_control_text(
    state: State,
    config: Config,
    client: TelegramClient,
    chat_id: int,
    message_id: Optional[int],
    text: str,
) -> bool:
    if not config.ha_config:
        return False

    cleaned = text.strip()
    if not cleaned:
        return False

    prune_expired_pending_actions(state)

    approval_cmd = parse_approval_command(cleaned)
    if approval_cmd:
        action, code = approval_cmd
        pending = get_pending_action(state, chat_id)
        if not pending:
            client.send_message(
                chat_id,
                "No pending HA action for this chat.",
                reply_to_message_id=message_id,
            )
            return True

        pending_code = str(pending.get("code", "")).upper()
        if not code:
            client.send_message(
                chat_id,
                f"Please include the approval code. Example: APPROVE {pending_code}",
                reply_to_message_id=message_id,
            )
            return True
        if code.upper() != pending_code:
            client.send_message(
                chat_id,
                "Approval code mismatch. Please use the latest code shown in summary.",
                reply_to_message_id=message_id,
            )
            return True

        expires_at = pending.get("expires_at")
        if not isinstance(expires_at, (int, float)) or float(expires_at) <= now_ts():
            clear_pending_action(state, chat_id)
            client.send_message(
                chat_id,
                "That pending HA action expired. Send the command again to generate a new approval code.",
                reply_to_message_id=message_id,
            )
            return True

        if action == "cancel":
            clear_pending_action(state, chat_id)
            client.send_message(
                chat_id,
                f"Cancelled pending HA action ({pending_code}).",
                reply_to_message_id=message_id,
            )
            return True

        action_payload = pending.get("action")
        if not isinstance(action_payload, dict):
            clear_pending_action(state, chat_id)
            client.send_message(
                chat_id,
                "Pending HA action payload was invalid and has been cleared.",
                reply_to_message_id=message_id,
            )
            return True

        ha_client = HomeAssistantClient(config.ha_config, timeout_seconds=config.poll_timeout_seconds + 10)
        try:
            result = execute_action(action_payload, ha_client, config.ha_config)
        except HAControlError as exc:
            clear_pending_action(state, chat_id)
            client.send_message(
                chat_id,
                f"HA action failed: {exc}",
                reply_to_message_id=message_id,
            )
            return True
        except Exception as exc:
            logging.exception("Unexpected HA execution error for chat_id=%s", chat_id)
            clear_pending_action(state, chat_id)
            if is_ha_network_error(exc):
                msg = "HA action failed due to network/API error. Please retry."
            else:
                msg = "HA action failed due to unexpected error. Please retry."
            client.send_message(chat_id, msg, reply_to_message_id=message_id)
            return True

        clear_pending_action(state, chat_id)
        client.send_message(chat_id, result, reply_to_message_id=message_id)
        return True

    ha_client = HomeAssistantClient(config.ha_config, timeout_seconds=config.poll_timeout_seconds + 10)
    try:
        planned = plan_action_from_text(cleaned, ha_client, config.ha_config)
    except HAControlError as exc:
        client.send_message(chat_id, f"HA request rejected: {exc}", reply_to_message_id=message_id)
        return True
    except Exception as exc:
        logging.exception("Unexpected HA planning error for chat_id=%s", chat_id)
        if is_ha_network_error(exc):
            msg = "Unable to reach Home Assistant right now. Please retry."
        else:
            msg = "Failed to parse/plan Home Assistant action. Please retry."
        client.send_message(chat_id, msg, reply_to_message_id=message_id)
        return True

    if planned is None:
        return False

    code = generate_approval_code()
    now = now_ts()
    payload = {
        "code": code,
        "summary": str(planned.get("summary", "HA action")),
        "action": planned,
        "created_at": now,
        "expires_at": now + config.ha_config.approval_ttl_seconds,
    }
    previous = get_pending_action(state, chat_id)
    set_pending_action(state, chat_id, payload)

    prefix = ""
    if previous:
        prefix = "Replaced previous pending HA action.\n\n"
    client.send_message(
        chat_id,
        prefix + build_pending_message(payload["summary"], code, config.ha_config.approval_ttl_seconds),
        reply_to_message_id=message_id,
    )
    return True


def handle_update(
    state: State,
    config: Config,
    client: TelegramClient,
    update: Dict[str, object],
) -> None:
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

    prompt_input, photo_file_id, voice_file_id = extract_prompt_and_media(message)
    if prompt_input is None and voice_file_id is None:
        return

    command = normalize_command(prompt_input or "")
    if command == "/start":
        client.send_message(
            chat_id,
            "Telegram Architect bridge is online. Send a prompt to begin.",
            reply_to_message_id=message_id,
        )
        return
    if command == "/help":
        client.send_message(chat_id, build_help_text(), reply_to_message_id=message_id)
        return
    if command == "/status":
        prune_expired_pending_actions(state)
        client.send_message(chat_id, build_status_text(state), reply_to_message_id=message_id)
        return
    if command == "/reset":
        handle_reset_command(state, client, chat_id, message_id)
        return

    prompt = (prompt_input or "").strip()
    if not prompt and not voice_file_id:
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

    if (
        prompt
        and photo_file_id is None
        and voice_file_id is None
        and handle_ha_control_text(state, config, client, chat_id, message_id, prompt)
    ):
        return

    if not mark_busy(state, chat_id):
        client.send_message(
            chat_id,
            config.busy_message,
            reply_to_message_id=message_id,
        )
        return

    try:
        client.send_message(
            chat_id,
            config.thinking_message,
            reply_to_message_id=message_id,
        )
    except Exception:
        logging.exception("Failed to send thinking ack for chat_id=%s", chat_id)
        clear_busy(state, chat_id)
        return

    worker = threading.Thread(
        target=process_prompt,
        args=(state, config, client, chat_id, message_id, prompt, photo_file_id, voice_file_id),
        daemon=True,
    )
    worker.start()


def run_self_test() -> int:
    sample = "x" * (TELEGRAM_LIMIT + 50)
    chunks = to_telegram_chunks(sample)
    if len(chunks) < 2:
        raise RuntimeError("Chunking self-test failed")
    parsed = parse_approval_command("APPROVE A1B2C3")
    if parsed != ("approve", "A1B2C3"):
        raise RuntimeError("Approval parser self-test failed")
    if len(generate_approval_code()) != 6:
        raise RuntimeError("Approval code self-test failed")
    print("self-test: ok")
    return 0


def drop_pending_updates(client: TelegramClient) -> int:
    offset = 0
    dropped = 0

    while True:
        updates = client.get_updates(offset, timeout_seconds=0)
        if not updates:
            break

        dropped += len(updates)
        next_offset = offset
        for update in updates:
            update_id = update.get("update_id")
            if isinstance(update_id, int):
                next_offset = max(next_offset, update_id + 1)

        if next_offset == offset:
            logging.warning(
                "Startup backlog discard could not advance offset; stopping discard loop."
            )
            break

        offset = next_offset

    if dropped:
        logging.info("Dropped %s queued Telegram update(s) at startup.", dropped)
    else:
        logging.info("No queued Telegram updates found at startup.")
    return offset


def run_bridge(config: Config) -> int:
    ensure_state_dir(config.state_dir)
    chat_thread_path = os.path.join(config.state_dir, "chat_threads.json")
    pending_action_path = os.path.join(config.state_dir, "pending_actions.json")
    loaded_threads = load_chat_threads(chat_thread_path)
    loaded_pending = load_pending_actions(pending_action_path)
    state = State(
        chat_threads=loaded_threads,
        chat_thread_path=chat_thread_path,
        pending_actions=loaded_pending,
        pending_action_path=pending_action_path,
    )
    client = TelegramClient(config)
    try:
        offset = drop_pending_updates(client)
    except Exception:
        logging.exception("Failed to discard queued startup updates; defaulting to offset=0")
        offset = 0

    logging.info("Bridge started. Allowed chats=%s", sorted(config.allowed_chat_ids))
    logging.info("Executor command=%s", config.executor_cmd)
    logging.info("Loaded %s chat thread mappings from %s", len(loaded_threads), chat_thread_path)
    logging.info("Loaded %s pending HA action(s) from %s", len(loaded_pending), pending_action_path)
    if config.ha_config:
        logging.info("Home Assistant control integration is enabled.")
    else:
        logging.info("Home Assistant control integration is disabled.")

    while True:
        try:
            updates = client.get_updates(offset)
            for update in updates:
                update_id = update.get("update_id")
                if isinstance(update_id, int):
                    offset = max(offset, update_id + 1)
                handle_update(state, config, client, update)
        except (HTTPError, URLError, TimeoutError):
            logging.exception("Network/API error while polling Telegram")
            time.sleep(config.retry_sleep_seconds)
        except Exception:
            logging.exception("Unexpected loop error")
            time.sleep(config.retry_sleep_seconds)


def main() -> int:
    parser = argparse.ArgumentParser(description="Telegram Architect bridge")
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="run local self test and exit",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=os.getenv("TELEGRAM_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(message)s",
    )

    if args.self_test:
        return run_self_test()

    try:
        config = load_config()
    except Exception as exc:
        logging.error("Configuration error: %s", exc)
        return 1

    return run_bridge(config)


if __name__ == "__main__":
    raise SystemExit(main())
