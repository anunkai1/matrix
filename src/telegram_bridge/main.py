#!/usr/bin/env python3
"""Telegram long-poll bridge to local Architect/Codex CLI."""

import argparse
import json
import logging
import os
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
    extract_conversation_id,
    extract_conversation_reply,
    is_ha_network_error,
    load_ha_config,
)

TELEGRAM_LIMIT = 4096
OUTPUT_BEGIN_MARKER = "OUTPUT_BEGIN"


@dataclass
class Config:
    token: str
    allowed_chat_ids: Set[int]
    architect_chat_ids: Set[int]
    ha_chat_ids: Set[int]
    chat_routing_enabled: bool
    api_base: str
    poll_timeout_seconds: int
    retry_sleep_seconds: float
    exec_timeout_seconds: int
    max_input_chars: int
    max_output_chars: int
    max_image_bytes: int
    max_voice_bytes: int
    max_document_bytes: int
    rate_limit_per_minute: int
    executor_cmd: List[str]
    voice_transcribe_cmd: List[str]
    voice_transcribe_timeout_seconds: int
    state_dir: str
    busy_message: str = "Another request is still running. Please wait."
    denied_message: str = "Access denied for this chat."
    timeout_message: str = "Request timed out. Please try a shorter prompt."
    generic_error_message: str = "Execution failed. Please try again later."
    image_download_error_message: str = "Image download failed. Please send another image."
    voice_download_error_message: str = "Voice download failed. Please send another voice message."
    document_download_error_message: str = "File download failed. Please send another file."
    ha_only_message: str = "This chat is Home Assistant-only. Send a Home Assistant control request here."
    architect_only_message: str = "This chat is Architect-only. Use your HA chat for Home Assistant control."
    unassigned_chat_message: str = (
        "Access denied for this chat. Chat routing is enabled and this chat is not assigned."
    )
    voice_not_configured_message: str = (
        "Voice transcription is not configured. Please ask admin to set TELEGRAM_VOICE_TRANSCRIBE_CMD."
    )
    voice_transcribe_error_message: str = "Voice transcription failed. Please send clearer audio."
    voice_transcribe_empty_message: str = (
        "Voice transcription was empty. Please send clearer audio."
    )
    empty_output_message: str = "(No output from Architect)"
    thinking_message: str = "💭🤔💭.....thinking.....💭🤔💭 (/h)"


@dataclass
class State:
    started_at: float = field(default_factory=time.time)
    busy_chats: Set[int] = field(default_factory=set)
    recent_requests: Dict[int, List[float]] = field(default_factory=dict)
    chat_threads: Dict[int, str] = field(default_factory=dict)
    chat_thread_path: str = ""
    ha_conversations: Dict[int, str] = field(default_factory=dict)
    ha_conversation_path: str = ""
    in_flight_requests: Dict[int, Dict[str, object]] = field(default_factory=dict)
    in_flight_path: str = ""
    restart_requested: bool = False
    restart_in_progress: bool = False
    restart_chat_id: Optional[int] = None
    restart_reply_to_message_id: Optional[int] = None
    lock: threading.Lock = field(default_factory=threading.Lock)


@dataclass
class DocumentPayload:
    file_id: str
    file_name: str
    mime_type: str


@dataclass
class HARuntime:
    config: Optional[HAConfig]
    client: Optional[HomeAssistantClient]


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


def parse_optional_chat_ids_env(name: str) -> Set[int]:
    raw = os.getenv(name)
    if raw is None:
        return set()
    cleaned = raw.strip()
    if not cleaned:
        return set()
    values = [item.strip() for item in cleaned.split(",") if item.strip()]
    parsed: Set[int] = set()
    for value in values:
        try:
            parsed.add(int(value))
        except ValueError as exc:
            raise ValueError(f"Invalid {name} value: {value!r}") from exc
    return parsed


def resolve_chat_routing(allowed_chat_ids: Set[int]) -> tuple[Set[int], Set[int], bool]:
    architect_chat_ids = parse_optional_chat_ids_env("TELEGRAM_ARCHITECT_CHAT_IDS")
    ha_chat_ids = parse_optional_chat_ids_env("TELEGRAM_HA_CHAT_IDS")

    routing_enabled = bool(architect_chat_ids or ha_chat_ids)
    if not routing_enabled:
        return set(), set(), False

    overlap = architect_chat_ids & ha_chat_ids
    if overlap:
        raise ValueError(
            "TELEGRAM_ARCHITECT_CHAT_IDS and TELEGRAM_HA_CHAT_IDS overlap: "
            f"{sorted(overlap)}"
        )

    unknown = (architect_chat_ids | ha_chat_ids) - allowed_chat_ids
    if unknown:
        raise ValueError(
            "Chat IDs in TELEGRAM_ARCHITECT_CHAT_IDS/TELEGRAM_HA_CHAT_IDS must be in "
            f"TELEGRAM_ALLOWED_CHAT_IDS. Unknown IDs: {sorted(unknown)}"
        )

    if not architect_chat_ids:
        architect_chat_ids = set(allowed_chat_ids - ha_chat_ids)
    if not ha_chat_ids:
        ha_chat_ids = set(allowed_chat_ids - architect_chat_ids)

    if not architect_chat_ids:
        raise ValueError("TELEGRAM_ARCHITECT_CHAT_IDS resolves to an empty set.")
    if not ha_chat_ids:
        raise ValueError("TELEGRAM_HA_CHAT_IDS resolves to an empty set.")

    unassigned = allowed_chat_ids - (architect_chat_ids | ha_chat_ids)
    if unassigned:
        raise ValueError(
            "Some TELEGRAM_ALLOWED_CHAT_IDS are unassigned while chat routing is enabled: "
            f"{sorted(unassigned)}"
        )

    return architect_chat_ids, ha_chat_ids, True


def get_chat_mode(config: Config, chat_id: int) -> str:
    if not config.chat_routing_enabled:
        return "mixed"
    if chat_id in config.architect_chat_ids:
        return "architect"
    if chat_id in config.ha_chat_ids:
        return "ha"
    return "unassigned"


def build_default_executor() -> str:
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    return os.path.join(repo_root, "src", "telegram_bridge", "executor.sh")


def build_restart_script_path() -> str:
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    return os.path.join(repo_root, "ops", "telegram-bridge", "restart_and_verify.sh")


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

    allowed_chat_ids = parse_allowed_chat_ids(raw_chat_ids)
    architect_chat_ids, ha_chat_ids, chat_routing_enabled = resolve_chat_routing(allowed_chat_ids)

    return Config(
        token=token,
        allowed_chat_ids=allowed_chat_ids,
        architect_chat_ids=architect_chat_ids,
        ha_chat_ids=ha_chat_ids,
        chat_routing_enabled=chat_routing_enabled,
        api_base=os.getenv("TELEGRAM_API_BASE", "https://api.telegram.org").rstrip("/"),
        poll_timeout_seconds=parse_int_env("TELEGRAM_POLL_TIMEOUT_SECONDS", 30),
        retry_sleep_seconds=float(os.getenv("TELEGRAM_RETRY_SLEEP_SECONDS", "3")),
        exec_timeout_seconds=parse_int_env("TELEGRAM_EXEC_TIMEOUT_SECONDS", 36000),
        max_input_chars=parse_int_env("TELEGRAM_MAX_INPUT_CHARS", TELEGRAM_LIMIT),
        max_output_chars=parse_int_env("TELEGRAM_MAX_OUTPUT_CHARS", 20000),
        max_image_bytes=parse_int_env("TELEGRAM_MAX_IMAGE_BYTES", 10 * 1024 * 1024, minimum=1024),
        max_voice_bytes=parse_int_env("TELEGRAM_MAX_VOICE_BYTES", 20 * 1024 * 1024, minimum=1024),
        max_document_bytes=parse_int_env("TELEGRAM_MAX_DOCUMENT_BYTES", 50 * 1024 * 1024, minimum=1024),
        rate_limit_per_minute=parse_int_env("TELEGRAM_RATE_LIMIT_PER_MINUTE", 12),
        executor_cmd=parse_executor_cmd(),
        voice_transcribe_cmd=parse_optional_cmd_env("TELEGRAM_VOICE_TRANSCRIBE_CMD"),
        voice_transcribe_timeout_seconds=parse_int_env(
            "TELEGRAM_VOICE_TRANSCRIBE_TIMEOUT_SECONDS",
            120,
        ),
        state_dir=state_dir,
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


def quarantine_corrupt_state_file(path: str) -> Optional[str]:
    data_path = Path(path)
    if not data_path.exists():
        return None
    timestamp = time.strftime("%Y%m%d%H%M%S", time.gmtime())
    quarantined = data_path.with_name(f"{data_path.name}.corrupt.{timestamp}")
    data_path.replace(quarantined)
    return str(quarantined)


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


def load_ha_conversations(path: str) -> Dict[int, str]:
    data_path = Path(path)
    if not data_path.exists():
        return {}
    try:
        raw = json.loads(data_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"Failed to parse HA conversation state {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError(f"Invalid HA conversation state {path}: root is not object")

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


def persist_ha_conversations(state: State) -> None:
    if not state.ha_conversation_path:
        return
    path = Path(state.ha_conversation_path)
    tmp_path = path.with_suffix(".tmp")
    with state.lock:
        serialized = {
            str(chat_id): conversation_id
            for chat_id, conversation_id in state.ha_conversations.items()
        }
    tmp_path.write_text(json.dumps(serialized, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp_path.replace(path)


def get_ha_conversation_id(state: State, chat_id: int) -> Optional[str]:
    with state.lock:
        return state.ha_conversations.get(chat_id)


def set_ha_conversation_id(state: State, chat_id: int, conversation_id: str) -> None:
    with state.lock:
        state.ha_conversations[chat_id] = conversation_id
    persist_ha_conversations(state)


def clear_ha_conversation_id(state: State, chat_id: int) -> bool:
    removed = False
    with state.lock:
        if chat_id in state.ha_conversations:
            del state.ha_conversations[chat_id]
            removed = True
    if removed:
        persist_ha_conversations(state)
    return removed


def load_in_flight_requests(path: str) -> Dict[int, Dict[str, object]]:
    data_path = Path(path)
    if not data_path.exists():
        return {}
    try:
        raw = json.loads(data_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"Failed to parse in-flight state {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError(f"Invalid in-flight state {path}: root is not object")

    out: Dict[int, Dict[str, object]] = {}
    for key, value in raw.items():
        if not isinstance(value, dict):
            continue
        try:
            chat_id = int(key)
        except ValueError:
            continue
        payload: Dict[str, object] = {}
        started_at = value.get("started_at")
        if isinstance(started_at, (int, float)):
            payload["started_at"] = float(started_at)
        message_id = value.get("message_id")
        if isinstance(message_id, int):
            payload["message_id"] = message_id
        out[chat_id] = payload
    return out


def persist_in_flight_requests(state: State) -> None:
    if not state.in_flight_path:
        return
    path = Path(state.in_flight_path)
    tmp_path = path.with_suffix(".tmp")
    with state.lock:
        serialized = {
            str(chat_id): payload
            for chat_id, payload in state.in_flight_requests.items()
        }
    tmp_path.write_text(
        json.dumps(serialized, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    tmp_path.replace(path)


def mark_in_flight_request(state: State, chat_id: int, message_id: Optional[int]) -> None:
    payload: Dict[str, object] = {"started_at": time.time()}
    if isinstance(message_id, int):
        payload["message_id"] = message_id
    with state.lock:
        state.in_flight_requests[chat_id] = payload
    persist_in_flight_requests(state)


def clear_in_flight_request(state: State, chat_id: int) -> None:
    removed = False
    with state.lock:
        if chat_id in state.in_flight_requests:
            del state.in_flight_requests[chat_id]
            removed = True
    if removed:
        persist_in_flight_requests(state)


def pop_interrupted_requests(state: State) -> Dict[int, Dict[str, object]]:
    with state.lock:
        if not state.in_flight_requests:
            return {}
        interrupted = dict(state.in_flight_requests)
        state.in_flight_requests = {}
    persist_in_flight_requests(state)
    return interrupted


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


def download_document_to_temp(
    client: TelegramClient,
    config: Config,
    document: DocumentPayload,
) -> tuple[str, int]:
    file_meta = client.get_file(document.file_id)
    file_path = file_meta.get("file_path")
    if not isinstance(file_path, str) or not file_path.strip():
        raise RuntimeError("Telegram getFile response missing file_path")

    file_size = file_meta.get("file_size")
    if isinstance(file_size, int) and file_size > config.max_document_bytes:
        raise ValueError(
            f"File too large ({file_size} bytes). Max is {config.max_document_bytes} bytes."
        )

    suffix = Path(document.file_name).suffix or Path(file_path).suffix or ".bin"
    fd, tmp_path = tempfile.mkstemp(prefix="telegram-bridge-file-", suffix=suffix)
    os.close(fd)
    try:
        client.download_file_to_path(
            file_path,
            tmp_path,
            config.max_document_bytes,
            size_label="File",
        )
    except Exception:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise

    final_size = file_size if isinstance(file_size, int) else os.path.getsize(tmp_path)
    return tmp_path, final_size


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


def transcribe_voice_for_chat(
    config: Config,
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


def build_help_text(chat_mode: str, ha_enabled: bool) -> str:
    mode_line = "Chat mode: mixed (HA + Architect in same chat)"
    if chat_mode == "architect":
        mode_line = "Chat mode: Architect-only"
    elif chat_mode == "ha":
        mode_line = "Chat mode: HA-only"

    mode_note = "Any other text, photo, voice, or file message is sent to Architect."
    if chat_mode == "ha":
        mode_note = "HA-only chat: Home Assistant text/voice requests are handled here."
    elif chat_mode == "architect":
        mode_note = "Architect-only chat: Home Assistant control is handled in your HA chat."

    if not ha_enabled:
        return (
            "Commands:\n"
            "/start - bridge intro\n"
            "/help - show commands\n"
            "/h - short help alias\n"
            "/status - show bridge health\n"
            "/restart - safe restart (queued until current work completes)\n"
            "/reset - clear chat context\n"
            "Chat mode: mixed (Architect-only; HA routing disabled)\n\n"
            "HA handling:\n"
            "- Home Assistant conversation routing is disabled in current runtime.\n"
            "- All text/photo/voice/file messages are sent to Architect."
        )

    return (
        "Commands:\n"
        "/start - bridge intro\n"
        "/help - show commands\n"
        "/h - short help alias\n"
        "/status - show bridge health\n"
        "/restart - safe restart (queued until current work completes)\n"
        "/reset - clear chat context\n"
        f"{mode_line}\n\n"
        "HA handling:\n"
        "- HA text/voice requests are sent to Home Assistant Conversation Agent.\n\n"
        f"{mode_note}"
    )


def build_status_text(state: State) -> str:
    uptime = int(time.time() - state.started_at)
    with state.lock:
        busy_count = len(state.busy_chats)
        restart_queued = state.restart_requested
        restart_running = state.restart_in_progress
    return (
        "Bridge status: healthy\n"
        f"Uptime: {uptime}s\n"
        f"Busy chats: {busy_count}\n"
        f"Restart queued: {'yes' if restart_queued else 'no'}\n"
        f"Restart in progress: {'yes' if restart_running else 'no'}"
    )


def request_safe_restart(
    state: State,
    chat_id: int,
    reply_to_message_id: Optional[int],
) -> tuple[str, int]:
    with state.lock:
        busy_count = len(state.busy_chats)
        if state.restart_in_progress:
            return "in_progress", busy_count
        if state.restart_requested:
            return "already_queued", busy_count

        state.restart_chat_id = chat_id
        state.restart_reply_to_message_id = reply_to_message_id
        if busy_count > 0:
            state.restart_requested = True
            return "queued", busy_count

        state.restart_in_progress = True
        return "run_now", busy_count


def pop_ready_restart_request(state: State) -> Optional[tuple[int, Optional[int]]]:
    with state.lock:
        if state.restart_in_progress:
            return None
        if not state.restart_requested:
            return None
        if state.busy_chats:
            return None
        if state.restart_chat_id is None:
            return None

        state.restart_requested = False
        state.restart_in_progress = True
        return state.restart_chat_id, state.restart_reply_to_message_id


def finish_restart_attempt(state: State) -> None:
    with state.lock:
        state.restart_in_progress = False


def run_restart_script(
    state: State,
    client: TelegramClient,
    chat_id: int,
    reply_to_message_id: Optional[int],
) -> None:
    script_path = build_restart_script_path()
    try:
        result = subprocess.run(
            ["bash", script_path],
            capture_output=True,
            text=True,
            timeout=90,
            check=False,
        )
    except subprocess.TimeoutExpired:
        logging.error("Bridge restart command timed out.")
        client.send_message(
            chat_id,
            "Restart command timed out. Please run restart manually.",
            reply_to_message_id=reply_to_message_id,
        )
        finish_restart_attempt(state)
        return
    except Exception:
        logging.exception("Bridge restart command failed to execute.")
        client.send_message(
            chat_id,
            "Restart command failed to execute. Please run restart manually.",
            reply_to_message_id=reply_to_message_id,
        )
        finish_restart_attempt(state)
        return

    if result.returncode != 0:
        logging.error(
            "Bridge restart command failed returncode=%s stderr=%r",
            result.returncode,
            (result.stderr or "")[-1000:],
        )
        client.send_message(
            chat_id,
            "Restart failed. Please run `bash ops/telegram-bridge/restart_and_verify.sh`.",
            reply_to_message_id=reply_to_message_id,
        )
        finish_restart_attempt(state)
        return

    # If this process survives a successful restart command invocation,
    # clear restart state so future restart requests are not blocked.
    finish_restart_attempt(state)


def trigger_restart_async(
    state: State,
    client: TelegramClient,
    chat_id: int,
    reply_to_message_id: Optional[int],
) -> None:
    worker = threading.Thread(
        target=run_restart_script,
        args=(state, client, chat_id, reply_to_message_id),
        daemon=True,
    )
    worker.start()


def finalize_chat_work(
    state: State,
    client: TelegramClient,
    chat_id: int,
) -> None:
    clear_in_flight_request(state, chat_id)
    clear_busy(state, chat_id)
    ready_restart = pop_ready_restart_request(state)
    if not ready_restart:
        return

    restart_chat_id, restart_reply_to = ready_restart
    try:
        client.send_message(
            restart_chat_id,
            "Current request completed. Restarting bridge now.",
            reply_to_message_id=restart_reply_to,
        )
    except Exception:
        logging.exception(
            "Failed to send queued restart acknowledgement for chat_id=%s",
            restart_chat_id,
        )
    trigger_restart_async(state, client, restart_chat_id, restart_reply_to)


def build_ha_runtime(config: Config) -> HARuntime:
    try:
        ha_config = load_ha_config(config.state_dir)
    except Exception:
        logging.exception("Failed to load HA runtime config; HA conversation handling disabled.")
        return HARuntime(config=None, client=None)

    if ha_config is None:
        return HARuntime(config=None, client=None)

    return HARuntime(config=ha_config, client=HomeAssistantClient(ha_config))


def handle_ha_request_text(
    state: State,
    config: Config,
    runtime: HARuntime,
    client: TelegramClient,
    chat_id: int,
    message_id: Optional[int],
    prompt: str,
) -> bool:
    cleaned = (prompt or "").strip()
    if not cleaned:
        return False

    if runtime.client is None or runtime.config is None:
        return False

    try:
        conversation_id = get_ha_conversation_id(state, chat_id)
        response = runtime.client.process_conversation(
            cleaned,
            conversation_id=conversation_id,
        )
    except HAControlError as exc:
        client.send_message(chat_id, str(exc), reply_to_message_id=message_id)
        return True
    except Exception as exc:
        if is_ha_network_error(exc):
            client.send_message(
                chat_id,
                "Home Assistant is unavailable right now. Please try again.",
                reply_to_message_id=message_id,
            )
            return True
        logging.exception("Unexpected HA conversation error for chat_id=%s", chat_id)
        client.send_message(chat_id, config.generic_error_message, reply_to_message_id=message_id)
        return True

    next_id = extract_conversation_id(response)
    if next_id:
        set_ha_conversation_id(state, chat_id, next_id)
    reply_text = extract_conversation_reply(response)
    client.send_message(chat_id, reply_text, reply_to_message_id=message_id)
    return True


def process_prompt(
    state: State,
    config: Config,
    client: TelegramClient,
    chat_id: int,
    message_id: Optional[int],
    prompt: str,
    photo_file_id: Optional[str],
    voice_file_id: Optional[str],
    document: Optional[DocumentPayload],
) -> None:
    previous_thread_id = get_thread_id(state, chat_id)
    prompt_text = prompt.strip()
    image_path: Optional[str] = None
    document_path: Optional[str] = None
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
            transcript = transcribe_voice_for_chat(
                config=config,
                client=client,
                chat_id=chat_id,
                message_id=message_id,
                voice_file_id=voice_file_id,
                echo_transcript=True,
            )
            if transcript is None:
                return

            if prompt_text:
                prompt_text = f"{prompt_text}\n\nVoice transcript:\n{transcript}"
            else:
                prompt_text = transcript

        if document:
            try:
                document_path, file_size = download_document_to_temp(client, config, document)
            except ValueError as exc:
                logging.warning("Document rejected for chat_id=%s: %s", chat_id, exc)
                client.send_message(chat_id, str(exc), reply_to_message_id=message_id)
                return
            except Exception:
                logging.exception("Document download failed for chat_id=%s", chat_id)
                client.send_message(
                    chat_id,
                    config.document_download_error_message,
                    reply_to_message_id=message_id,
                )
                return

            context = build_document_analysis_context(document_path, document, file_size)
            if prompt_text:
                prompt_text = f"{prompt_text}\n\n{context}"
            else:
                prompt_text = context

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
        if document_path:
            try:
                os.remove(document_path)
            except OSError:
                logging.warning("Failed to remove temp file: %s", document_path)
        finalize_chat_work(state, client, chat_id)


def process_message_worker(
    state: State,
    config: Config,
    client: TelegramClient,
    chat_id: int,
    message_id: Optional[int],
    prompt: str,
    photo_file_id: Optional[str],
    voice_file_id: Optional[str],
    document: Optional[DocumentPayload],
) -> None:
    delegated_to_prompt = False
    try:
        try:
            client.send_message(
                chat_id,
                config.thinking_message,
                reply_to_message_id=message_id,
            )
        except Exception:
            logging.exception("Failed to send thinking ack for chat_id=%s", chat_id)
            return

        delegated_to_prompt = True
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
    finally:
        if not delegated_to_prompt:
            finalize_chat_work(state, client, chat_id)


def handle_reset_command(
    state: State,
    client: TelegramClient,
    chat_id: int,
    message_id: Optional[int],
) -> None:
    reset_architect = clear_thread_id(state, chat_id)
    reset_ha = clear_ha_conversation_id(state, chat_id)
    if reset_architect or reset_ha:
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
    config: Config,
    client: TelegramClient,
    ha_runtime: HARuntime,
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

    chat_mode = get_chat_mode(config, chat_id)
    if chat_mode == "unassigned":
        logging.warning("Denied unassigned routed chat_id=%s", chat_id)
        client.send_message(chat_id, config.unassigned_chat_message, reply_to_message_id=message_id)
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
        ha_enabled = bool(ha_runtime.client is not None and ha_runtime.config is not None)
        client.send_message(
            chat_id,
            build_help_text(chat_mode, ha_enabled),
            reply_to_message_id=message_id,
        )
        return
    if command == "/status":
        client.send_message(chat_id, build_status_text(state), reply_to_message_id=message_id)
        return
    if command == "/restart":
        handle_restart_command(state, client, chat_id, message_id)
        return
    if command == "/reset":
        handle_reset_command(state, client, chat_id, message_id)
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

    text_only = bool(prompt and photo_file_id is None and voice_file_id is None and document is None)
    if chat_mode == "ha":
        if photo_file_id is not None or document is not None:
            client.send_message(
                chat_id,
                config.ha_only_message,
                reply_to_message_id=message_id,
            )
            return

        ha_prompt = prompt
        if voice_file_id is not None:
            transcript = transcribe_voice_for_chat(
                config=config,
                client=client,
                chat_id=chat_id,
                message_id=message_id,
                voice_file_id=voice_file_id,
                echo_transcript=True,
            )
            if transcript is None:
                return
            if ha_prompt:
                ha_prompt = f"{ha_prompt}\n{transcript}"
            else:
                ha_prompt = transcript
            ha_prompt = ha_prompt.strip()

        if ha_prompt and len(ha_prompt) > config.max_input_chars:
            client.send_message(
                chat_id,
                f"Input too long ({len(ha_prompt)} chars). Max is {config.max_input_chars}.",
                reply_to_message_id=message_id,
            )
            return

        if (
            ha_prompt
            and handle_ha_request_text(
                state=state,
                config=config,
                runtime=ha_runtime,
                client=client,
                chat_id=chat_id,
                message_id=message_id,
                prompt=ha_prompt,
            )
        ):
            return
        client.send_message(
            chat_id,
            config.ha_only_message,
            reply_to_message_id=message_id,
        )
        return

    if (
        chat_mode == "mixed"
        and text_only
        and handle_ha_request_text(
            state=state,
            config=config,
            runtime=ha_runtime,
            client=client,
            chat_id=chat_id,
            message_id=message_id,
            prompt=prompt,
        )
    ):
        return

    if is_rate_limited(state, config, chat_id):
        client.send_message(
            chat_id,
            "Rate limit exceeded. Please wait a minute and retry.",
            reply_to_message_id=message_id,
        )
        return

    if not mark_busy(state, chat_id):
        client.send_message(
            chat_id,
            config.busy_message,
            reply_to_message_id=message_id,
        )
        return
    mark_in_flight_request(state, chat_id, message_id)

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


def run_self_test() -> int:
    sample = "x" * (TELEGRAM_LIMIT + 50)
    chunks = to_telegram_chunks(sample)
    if len(chunks) < 2:
        raise RuntimeError("Chunking self-test failed")

    prompt, _, _, document = extract_prompt_and_media(
        {"document": {"file_id": "f1", "file_name": "sample.txt", "mime_type": "text/plain"}}
    )
    if prompt != "Please analyze this file." or not document or document.file_id != "f1":
        raise RuntimeError("Document parsing self-test failed")

    restart_state = State()
    status, _ = request_safe_restart(restart_state, chat_id=1, reply_to_message_id=None)
    if status != "run_now":
        raise RuntimeError("Restart self-test failed (run_now)")
    finish_restart_attempt(restart_state)
    with restart_state.lock:
        restart_state.busy_chats.add(1)
    status, _ = request_safe_restart(restart_state, chat_id=1, reply_to_message_id=None)
    if status != "queued":
        raise RuntimeError("Restart self-test failed (queued)")
    clear_busy(restart_state, 1)
    ready = pop_ready_restart_request(restart_state)
    if not ready or ready[0] != 1:
        raise RuntimeError("Restart self-test failed (pop_ready)")
    finish_restart_attempt(restart_state)

    routing_config = Config(
        token="t",
        allowed_chat_ids={1, 2},
        architect_chat_ids={1},
        ha_chat_ids={2},
        chat_routing_enabled=True,
        api_base="https://api.telegram.org",
        poll_timeout_seconds=30,
        retry_sleep_seconds=1.0,
        exec_timeout_seconds=30,
        max_input_chars=100,
        max_output_chars=100,
        max_image_bytes=1024,
        max_voice_bytes=1024,
        max_document_bytes=1024,
        rate_limit_per_minute=10,
        executor_cmd=["/bin/echo"],
        voice_transcribe_cmd=[],
        voice_transcribe_timeout_seconds=10,
        state_dir="/tmp",
    )
    if get_chat_mode(routing_config, 1) != "architect":
        raise RuntimeError("Routing self-test failed (architect)")
    if get_chat_mode(routing_config, 2) != "ha":
        raise RuntimeError("Routing self-test failed (ha)")
    if get_chat_mode(routing_config, 3) != "unassigned":
        raise RuntimeError("Routing self-test failed (unassigned)")

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
    ha_conversation_path = os.path.join(config.state_dir, "ha_conversations.json")
    in_flight_path = os.path.join(config.state_dir, "in_flight_requests.json")
    try:
        loaded_threads = load_chat_threads(chat_thread_path)
    except Exception:
        logging.exception(
            "Failed to load chat thread mappings from %s; starting with empty mappings.",
            chat_thread_path,
        )
        moved = quarantine_corrupt_state_file(chat_thread_path)
        if moved:
            logging.error("Quarantined corrupt chat thread state file to %s", moved)
        loaded_threads = {}

    try:
        loaded_in_flight = load_in_flight_requests(in_flight_path)
    except Exception:
        logging.exception(
            "Failed to load in-flight request state from %s; starting with empty in-flight state.",
            in_flight_path,
        )
        moved = quarantine_corrupt_state_file(in_flight_path)
        if moved:
            logging.error("Quarantined corrupt in-flight state file to %s", moved)
        loaded_in_flight = {}

    try:
        loaded_ha_conversations = load_ha_conversations(ha_conversation_path)
    except Exception:
        logging.exception(
            "Failed to load HA conversation state from %s; starting with empty mappings.",
            ha_conversation_path,
        )
        moved = quarantine_corrupt_state_file(ha_conversation_path)
        if moved:
            logging.error("Quarantined corrupt HA conversation state file to %s", moved)
        loaded_ha_conversations = {}

    state = State(
        chat_threads=loaded_threads,
        chat_thread_path=chat_thread_path,
        ha_conversations=loaded_ha_conversations,
        ha_conversation_path=ha_conversation_path,
        in_flight_requests=loaded_in_flight,
        in_flight_path=in_flight_path,
    )
    client = TelegramClient(config)
    ha_runtime = build_ha_runtime(config)

    interrupted = pop_interrupted_requests(state)
    if interrupted:
        for chat_id in sorted(interrupted):
            if chat_id not in config.allowed_chat_ids:
                continue
            try:
                client.send_message(
                    chat_id,
                    "Your previous request was interrupted because the bridge restarted. "
                    "Please resend it.",
                )
            except Exception:
                logging.exception(
                    "Failed to send restart-interruption notice for chat_id=%s",
                    chat_id,
                )
        logging.warning(
            "Detected %s interrupted in-flight request(s) from previous runtime.",
            len(interrupted),
        )

    try:
        offset = drop_pending_updates(client)
    except Exception:
        logging.exception("Failed to discard queued startup updates; defaulting to offset=0")
        offset = 0

    logging.info("Bridge started. Allowed chats=%s", sorted(config.allowed_chat_ids))
    if config.chat_routing_enabled:
        logging.info(
            "Chat routing enabled. Architect chats=%s HA chats=%s",
            sorted(config.architect_chat_ids),
            sorted(config.ha_chat_ids),
        )
    else:
        logging.info("Chat routing disabled. Mixed HA/Architect behavior is active.")
    logging.info("Executor command=%s", config.executor_cmd)
    if ha_runtime.client is not None and ha_runtime.config is not None:
        logging.info("HA conversation mode enabled; local HA parser is disabled.")
    else:
        logging.info("HA conversation mode disabled by runtime config.")
    logging.info("Loaded %s chat thread mappings from %s", len(loaded_threads), chat_thread_path)
    logging.info(
        "Loaded %s HA conversation mapping(s) from %s",
        len(loaded_ha_conversations),
        ha_conversation_path,
    )
    logging.info("Loaded %s in-flight request marker(s) from %s", len(loaded_in_flight), in_flight_path)

    while True:
        try:
            updates = client.get_updates(offset)
            for update in updates:
                update_id = update.get("update_id")
                if isinstance(update_id, int):
                    offset = max(offset, update_id + 1)
                handle_update(state, config, client, ha_runtime, update)
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
