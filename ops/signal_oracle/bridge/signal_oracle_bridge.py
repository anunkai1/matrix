#!/usr/bin/env python3
"""Local Signal transport bridge for the shared Python chat runtime."""

import base64
import hashlib
import json
import logging
import mimetypes
import os
import signal
import subprocess
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen


def parse_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean")


def parse_int(name: str, default: int, minimum: int = 1) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    value = int(raw)
    if value < minimum:
        raise ValueError(f"{name} must be >= {minimum}")
    return value


def normalize_phone(value: str) -> str:
    text = (value or "").strip()
    if not text:
        return ""
    digits = []
    for index, char in enumerate(text):
        if char == "+" and index == 0:
            digits.append(char)
        elif char.isdigit():
            digits.append(char)
    normalized = "".join(digits)
    if normalized.startswith("00"):
        normalized = f"+{normalized[2:]}"
    return normalized


def infer_mime_type(file_name: str, fallback: str = "application/octet-stream") -> str:
    guessed, _ = mimetypes.guess_type(file_name)
    return guessed or fallback


def detect_media_kind(content_type: str, file_name: str) -> str:
    normalized = (content_type or "").lower()
    suffix = Path(file_name or "").suffix.lower()
    if normalized.startswith("image/"):
        return "photo"
    if normalized.startswith("audio/"):
        if (
            suffix in {".ogg", ".oga", ".opus", ".aac", ".m4a"}
            or "ogg" in normalized
            or "opus" in normalized
            or normalized in {"audio/aac", "audio/mp4", "audio/x-m4a", "audio/m4a"}
        ):
            return "voice"
        return "document"
    return "document"


@dataclass
class Config:
    api_host: str
    api_port: int
    api_auth_token: str
    state_dir: str
    signal_cli_path: str
    signal_account: str
    signal_account_uuid: str
    signal_http_host: str
    signal_http_port: int
    signal_receive_mode: str
    signal_ignore_attachments: bool
    signal_ignore_stories: bool
    signal_send_read_receipts: bool
    max_updates_per_poll: int
    max_queue_size: int
    max_long_poll_seconds: int
    file_max_bytes: int
    file_total_bytes: int
    daemon_startup_timeout_seconds: int
    log_level: str

    @property
    def signal_base_url(self) -> str:
        return f"http://{self.signal_http_host}:{self.signal_http_port}"


def load_config() -> Config:
    state_dir = os.getenv(
        "SIGNAL_STATE_DIR",
        "/home/oracle/signal-oracle/state",
    ).strip() or "/home/oracle/signal-oracle/state"
    signal_account = os.getenv("SIGNAL_ACCOUNT", "").strip()
    if not signal_account:
        raise ValueError("SIGNAL_ACCOUNT is required")
    return Config(
        api_host=os.getenv("SIGNAL_API_HOST", "127.0.0.1").strip() or "127.0.0.1",
        api_port=parse_int("SIGNAL_API_PORT", 8797),
        api_auth_token=os.getenv("SIGNAL_API_AUTH_TOKEN", "").strip(),
        state_dir=state_dir,
        signal_cli_path=os.getenv("SIGNAL_CLI_PATH", "signal-cli").strip() or "signal-cli",
        signal_account=signal_account,
        signal_account_uuid=os.getenv("SIGNAL_ACCOUNT_UUID", "").strip(),
        signal_http_host=os.getenv("SIGNAL_HTTP_HOST", "127.0.0.1").strip() or "127.0.0.1",
        signal_http_port=parse_int("SIGNAL_HTTP_PORT", 8080),
        signal_receive_mode=os.getenv("SIGNAL_RECEIVE_MODE", "manual").strip() or "manual",
        signal_ignore_attachments=parse_bool("SIGNAL_IGNORE_ATTACHMENTS", False),
        signal_ignore_stories=parse_bool("SIGNAL_IGNORE_STORIES", True),
        signal_send_read_receipts=parse_bool("SIGNAL_SEND_READ_RECEIPTS", False),
        max_updates_per_poll=parse_int("SIGNAL_API_MAX_UPDATES_PER_POLL", 100),
        max_queue_size=parse_int("SIGNAL_API_MAX_QUEUE_SIZE", 2000),
        max_long_poll_seconds=parse_int("SIGNAL_API_MAX_LONG_POLL_SECONDS", 30),
        file_max_bytes=parse_int("SIGNAL_FILE_MAX_BYTES", 50 * 1024 * 1024, minimum=1024),
        file_total_bytes=parse_int(
            "SIGNAL_FILE_MAX_TOTAL_BYTES",
            500 * 1024 * 1024,
            minimum=1024,
        ),
        daemon_startup_timeout_seconds=parse_int(
            "SIGNAL_DAEMON_STARTUP_TIMEOUT_SECONDS",
            30,
        ),
        log_level=os.getenv("LOG_LEVEL", "INFO").strip() or "INFO",
    )


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(message)s",
    )


def rpc_request(config: Config, method: str, params: Dict[str, object]) -> object:
    body = json.dumps(
        {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
            "id": uuid.uuid4().hex,
        }
    ).encode("utf-8")
    request = Request(
        f"{config.signal_base_url}/api/v1/rpc",
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urlopen(request, timeout=20) as response:
            payload = response.read().decode("utf-8")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Signal RPC {method} failed: HTTP {exc.code} {detail}") from exc
    decoded = json.loads(payload) if payload else {}
    if isinstance(decoded, dict) and decoded.get("error"):
        error = decoded["error"]
        if isinstance(error, dict):
            code = error.get("code", "unknown")
            message = error.get("message", "Signal RPC error")
            raise RuntimeError(f"Signal RPC {method} failed: {code} {message}")
    if isinstance(decoded, dict):
        return decoded.get("result")
    return decoded


def signal_check(config: Config) -> bool:
    request = Request(f"{config.signal_base_url}/api/v1/check", method="GET")
    try:
        with urlopen(request, timeout=5) as response:
            return 200 <= response.status < 300
    except Exception:
        return False


def wait_for_daemon_ready(config: Config) -> None:
    deadline = time.time() + config.daemon_startup_timeout_seconds
    while time.time() < deadline:
        if signal_check(config):
            return
        time.sleep(0.25)
    raise RuntimeError("signal-cli daemon did not become ready in time")


class UpdateQueue:
    def __init__(self, max_queue_size: int) -> None:
        self._max_queue_size = max_queue_size
        self._updates: List[Dict[str, object]] = []
        self._next_update_id = 1
        self._condition = threading.Condition()

    def enqueue(self, update: Dict[str, object]) -> None:
        with self._condition:
            update["update_id"] = self._next_update_id
            self._next_update_id += 1
            self._updates.append(update)
            if len(self._updates) > self._max_queue_size:
                overflow = len(self._updates) - self._max_queue_size
                del self._updates[:overflow]
            self._condition.notify_all()

    def poll(self, offset: int, timeout_seconds: int, limit: int) -> List[Dict[str, object]]:
        deadline = time.time() + max(0, timeout_seconds)
        with self._condition:
            while True:
                ready = [item for item in self._updates if int(item.get("update_id", 0)) >= offset]
                if ready:
                    return ready[:limit]
                remaining = deadline - time.time()
                if remaining <= 0:
                    return []
                self._condition.wait(timeout=remaining)


class MappingStore:
    def __init__(self, state_dir: str) -> None:
        self._path = Path(state_dir) / "chat_mappings.json"
        self._lock = threading.Lock()
        self._target_to_chat_id: Dict[str, int] = {}
        self._chat_id_to_target: Dict[int, str] = {}
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            decoded = json.loads(self._path.read_text(encoding="utf-8"))
        except Exception:
            logging.warning("Failed to load chat mapping file %s", self._path)
            return
        if not isinstance(decoded, dict):
            return
        for key, value in decoded.items():
            if isinstance(key, str) and isinstance(value, int):
                self._target_to_chat_id[key] = value
                self._chat_id_to_target[value] = key

    def _persist(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self._path.with_suffix(".tmp")
        temp_path.write_text(
            json.dumps(self._target_to_chat_id, ensure_ascii=True, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        temp_path.replace(self._path)

    def _stable_base_chat_id(self, target: str) -> int:
        digest = hashlib.sha1(target.encode("utf-8")).digest()
        candidate = int.from_bytes(digest[:4], "big") & 0x7FFFFFFF
        return candidate or 1

    def get_or_create_chat_id(self, target: str) -> int:
        with self._lock:
            existing = self._target_to_chat_id.get(target)
            if existing is not None:
                return existing
            candidate = self._stable_base_chat_id(target)
            while candidate in self._chat_id_to_target and self._chat_id_to_target[candidate] != target:
                candidate = (candidate + 1) & 0x7FFFFFFF
                if candidate == 0:
                    candidate = 1
            self._target_to_chat_id[target] = candidate
            self._chat_id_to_target[candidate] = target
            self._persist()
            return candidate

    def get_target(self, chat_id: int) -> Optional[str]:
        with self._lock:
            return self._chat_id_to_target.get(chat_id)


class AttachmentStore:
    def __init__(self, config: Config) -> None:
        self.config = config
        self._lock = threading.Lock()
        self._items: Dict[str, Dict[str, object]] = {}
        self._order: List[str] = []
        self._total_bytes = 0

    def remember(
        self,
        *,
        attachment_id: str,
        sender: str,
        group_id: str,
        content_type: str,
        file_name: str,
        size: int,
    ) -> str:
        item_id = f"sig-{uuid.uuid4().hex}"
        with self._lock:
            self._items[item_id] = {
                "attachment_id": attachment_id,
                "sender": sender,
                "group_id": group_id,
                "content_type": content_type,
                "file_name": file_name,
                "size": size,
                "created_at": time.time(),
            }
            self._order.append(item_id)
            self._total_bytes += max(0, size)
            self._trim()
        return item_id

    def _trim(self) -> None:
        while self._total_bytes > self.config.file_total_bytes and self._order:
            victim = self._order.pop(0)
            data = self._items.pop(victim, None)
            if not data:
                continue
            self._total_bytes -= int(data.get("size", 0) or 0)

    def get_meta(self, file_id: str) -> Dict[str, object]:
        with self._lock:
            item = self._items.get(file_id)
            if item is None:
                raise KeyError(file_id)
            return dict(item)


class ApiError(RuntimeError):
    def __init__(self, status: int, message: str) -> None:
        self.status = status
        super().__init__(message)


class SignalDaemon:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.process: Optional[subprocess.Popen] = None

    def start(self) -> None:
        args = []
        if self.config.signal_account:
            args.extend(["-a", self.config.signal_account])
        args.extend(
            [
                "daemon",
                "--http",
                f"{self.config.signal_http_host}:{self.config.signal_http_port}",
                "--no-receive-stdout",
            ]
        )
        if self.config.signal_receive_mode:
            args.extend(["--receive-mode", self.config.signal_receive_mode])
        if self.config.signal_ignore_attachments:
            args.append("--ignore-attachments")
        if self.config.signal_ignore_stories:
            args.append("--ignore-stories")
        if self.config.signal_send_read_receipts:
            args.append("--send-read-receipts")
        self.process = subprocess.Popen(
            [self.config.signal_cli_path, *args],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        threading.Thread(target=self._log_output, args=(self.process.stdout, logging.info), daemon=True).start()
        threading.Thread(
            target=self._log_output,
            args=(self.process.stderr, logging.warning),
            daemon=True,
        ).start()
        wait_for_daemon_ready(self.config)

    def _log_output(self, stream, log) -> None:
        if stream is None:
            return
        for line in stream:
            text = line.strip()
            if text:
                log("signal-cli: %s", text)

    def stop(self) -> None:
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()


class SignalOracleBridge:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.state_dir = Path(config.state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.updates = UpdateQueue(config.max_queue_size)
        self.mappings = MappingStore(config.state_dir)
        self.attachments = AttachmentStore(config)
        self.daemon = SignalDaemon(config)
        self._stop_event = threading.Event()
        self._sse_thread: Optional[threading.Thread] = None

    def start(self) -> None:
        self.daemon.start()
        self._sse_thread = threading.Thread(target=self._run_event_loop, daemon=True)
        self._sse_thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self.daemon.stop()

    def _is_own_sender(self, envelope: Dict[str, object]) -> bool:
        source_number = normalize_phone(str(envelope.get("sourceNumber") or ""))
        if source_number and source_number == normalize_phone(self.config.signal_account):
            return True
        source_uuid = str(envelope.get("sourceUuid") or "").strip()
        return bool(
            source_uuid
            and self.config.signal_account_uuid
            and source_uuid == self.config.signal_account_uuid
        )

    def _run_event_loop(self) -> None:
        reconnect_delay = 1.0
        while not self._stop_event.is_set():
            try:
                self._stream_events()
                reconnect_delay = 1.0
            except Exception as exc:
                if self._stop_event.is_set():
                    return
                logging.warning("Signal event stream failed: %s", exc)
                time.sleep(reconnect_delay)
                reconnect_delay = min(reconnect_delay * 2, 10.0)

    def _stream_events(self) -> None:
        url = f"{self.config.signal_base_url}/api/v1/events?{urlencode({'account': self.config.signal_account})}"
        request = Request(url, method="GET", headers={"Accept": "text/event-stream"})
        with urlopen(request, timeout=60) as response:
            event_name = ""
            data_lines: List[str] = []
            while not self._stop_event.is_set():
                raw_line = response.readline()
                if not raw_line:
                    raise RuntimeError("Signal SSE stream ended")
                line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
                if not line:
                    self._handle_event(event_name, "\n".join(data_lines))
                    event_name = ""
                    data_lines = []
                    continue
                if line.startswith(":"):
                    continue
                field, _, value = line.partition(":")
                value = value.lstrip(" ")
                if field == "event":
                    event_name = value
                elif field == "data":
                    data_lines.append(value)

    def _handle_event(self, event_name: str, data: str) -> None:
        if event_name != "receive" or not data:
            return
        payload = json.loads(data)
        if not isinstance(payload, dict):
            return
        envelope = payload.get("envelope")
        if not isinstance(envelope, dict):
            return
        if "syncMessage" in envelope:
            return
        if self._is_own_sender(envelope):
            return
        message = self._normalize_envelope(envelope)
        if message is None:
            return
        self.updates.enqueue(message)

    def _normalize_envelope(self, envelope: Dict[str, object]) -> Optional[Dict[str, object]]:
        data_message = envelope.get("dataMessage")
        if not isinstance(data_message, dict):
            edit = envelope.get("editMessage")
            if isinstance(edit, dict):
                candidate = edit.get("dataMessage")
                if isinstance(candidate, dict):
                    data_message = candidate
        if not isinstance(data_message, dict):
            return None

        group_info = data_message.get("groupInfo")
        group_id = ""
        group_name = ""
        if isinstance(group_info, dict):
            group_id = str(group_info.get("groupId") or "").strip()
            group_name = str(group_info.get("groupName") or "").strip()

        sender = normalize_phone(str(envelope.get("sourceNumber") or "")) or str(
            envelope.get("sourceUuid") or ""
        ).strip()
        if not sender:
            return None
        target_key = f"group:{group_id}" if group_id else f"dm:{sender}"
        chat_id = self.mappings.get_or_create_chat_id(target_key)
        timestamp = envelope.get("timestamp") or data_message.get("timestamp")
        if not isinstance(timestamp, int):
            timestamp = int(time.time() * 1000)
        sender_name = str(envelope.get("sourceName") or "").strip() or sender
        raw_text = str(data_message.get("message") or "").strip()

        reply_to_message = None
        quote = data_message.get("quote")
        if isinstance(quote, dict):
            quoted_text = str(quote.get("text") or "").strip()
            if quoted_text:
                reply_to_message = {
                    "text": quoted_text,
                    "from": {"first_name": sender_name},
                }

        message: Dict[str, object] = {
            "message_id": timestamp,
            "date": int(timestamp / 1000),
            "chat": {
                "id": chat_id,
                "type": "group" if group_id else "private",
                "title": group_name or None,
            },
            "from": {
                "first_name": sender_name,
                "username": sender_name,
            },
            "reply_to_message": reply_to_message,
        }

        attachments = data_message.get("attachments")
        if isinstance(attachments, list) and attachments:
            attachment = attachments[0]
            if isinstance(attachment, dict):
                attachment_id = str(attachment.get("id") or "").strip()
                content_type = str(attachment.get("contentType") or "").strip()
                size = int(attachment.get("size") or 0)
                file_name = str(attachment.get("filename") or "").strip() or f"attachment-{attachment_id}"
                if attachment_id:
                    file_id = self.attachments.remember(
                        attachment_id=attachment_id,
                        sender=sender,
                        group_id=group_id,
                        content_type=content_type,
                        file_name=file_name,
                        size=size,
                    )
                    kind = detect_media_kind(content_type, file_name)
                    if kind == "photo":
                        message["photo"] = [{"file_id": file_id, "file_size": size}]
                        if raw_text:
                            message["caption"] = raw_text
                    elif kind == "voice":
                        message["voice"] = {"file_id": file_id}
                        if raw_text:
                            message["caption"] = raw_text
                    else:
                        message["document"] = {
                            "file_id": file_id,
                            "file_name": file_name,
                            "mime_type": content_type or infer_mime_type(file_name),
                        }
                        if raw_text:
                            message["caption"] = raw_text
                    return {"update_id": 0, "message": message}

        if not raw_text:
            return None
        message["text"] = raw_text
        return {"update_id": 0, "message": message}

    def health(self) -> Dict[str, object]:
        daemon_ready = signal_check(self.config)
        return {
            "ready": daemon_ready and not self._stop_event.is_set(),
            "signal_account": self.config.signal_account,
            "signal_base_url": self.config.signal_base_url,
        }

    def get_updates(self, offset: int, timeout_seconds: int) -> List[Dict[str, object]]:
        timeout = min(max(0, timeout_seconds), self.config.max_long_poll_seconds)
        return self.updates.poll(offset, timeout, self.config.max_updates_per_poll)

    def _resolve_target(self, chat_id: int) -> Tuple[str, str]:
        target = self.mappings.get_target(chat_id)
        if not target:
            raise ApiError(HTTPStatus.NOT_FOUND, "unknown_chat_id")
        if target.startswith("group:"):
            return "group", target.split(":", 1)[1]
        if target.startswith("dm:"):
            return "recipient", target.split(":", 1)[1]
        raise ApiError(HTTPStatus.BAD_REQUEST, "invalid_chat_mapping")

    def _send(
        self,
        chat_id: int,
        *,
        text: str,
        attachments: Optional[List[str]] = None,
        media_type: str = "",
    ) -> Dict[str, object]:
        target_kind, target_value = self._resolve_target(chat_id)
        params: Dict[str, object] = {
            "message": text or "",
            "account": self.config.signal_account,
        }
        if target_kind == "group":
            params["groupId"] = target_value
        else:
            params["recipient"] = [target_value]
        if attachments:
            params["attachments"] = attachments
        if not text and not attachments:
            raise ApiError(HTTPStatus.BAD_REQUEST, "empty_message")
        result = rpc_request(self.config, "send", params)
        timestamp = None
        if isinstance(result, dict):
            raw_timestamp = result.get("timestamp")
            if isinstance(raw_timestamp, int):
                timestamp = raw_timestamp
        return {"message_id": int(timestamp or int(time.time() * 1000))}

    def send_message(self, chat_id: int, text: str) -> Dict[str, object]:
        return self._send(chat_id, text=text)

    def _download_media_ref(self, media_ref: str) -> Tuple[str, bool]:
        parsed = urlparse(media_ref)
        if parsed.scheme in {"http", "https"}:
            suffix = Path(parsed.path).suffix or ".bin"
            fd, temp_path = tempfile.mkstemp(prefix="signal-oracle-upload-", suffix=suffix)
            os.close(fd)
            total = 0
            try:
                with urlopen(media_ref, timeout=30) as response, open(temp_path, "wb") as handle:
                    while True:
                        chunk = response.read(64 * 1024)
                        if not chunk:
                            break
                        total += len(chunk)
                        if total > self.config.file_max_bytes:
                            raise ApiError(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "media_file_too_large")
                        handle.write(chunk)
            except Exception:
                Path(temp_path).unlink(missing_ok=True)
                raise
            return temp_path, True

        resolved = Path(media_ref).expanduser().resolve()
        if not resolved.exists() or not resolved.is_file():
            raise ApiError(HTTPStatus.BAD_REQUEST, "unsupported_media_ref")
        if resolved.stat().st_size > self.config.file_max_bytes:
            raise ApiError(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "media_file_too_large")
        return str(resolved), False

    def send_media(
        self,
        chat_id: int,
        media_ref: str,
        caption: str,
        media_type: str,
    ) -> Dict[str, object]:
        local_path, delete_after = self._download_media_ref(media_ref)
        try:
            return self._send(
                chat_id,
                text=caption or "",
                attachments=[local_path],
                media_type=media_type,
            )
        finally:
            if delete_after:
                Path(local_path).unlink(missing_ok=True)

    def send_chat_action(self, chat_id: int, action: str) -> None:
        if action not in {"typing", "record_voice", "upload_voice", "upload_audio", "upload_photo", "upload_document"}:
            return
        target_kind, target_value = self._resolve_target(chat_id)
        params: Dict[str, object] = {"account": self.config.signal_account}
        if target_kind == "group":
            params["groupId"] = target_value
        else:
            params["recipient"] = [target_value]
        try:
            rpc_request(self.config, "sendTyping", params)
        except Exception as exc:
            logging.debug("Signal typing action failed for chat_id=%s: %s", chat_id, exc)

    def get_file_meta(self, file_id: str) -> Dict[str, object]:
        item = self.attachments.get_meta(file_id)
        return {
            "file_path": file_id,
            "file_size": int(item.get("size") or 0),
            "mime_type": item.get("content_type") or "",
            "file_name": item.get("file_name") or "",
        }

    def get_file_content(self, file_id: str) -> Tuple[bytes, str, str]:
        item = self.attachments.get_meta(file_id)
        size = int(item.get("size") or 0)
        if size > self.config.file_max_bytes:
            raise ApiError(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "file_too_large")
        params: Dict[str, object] = {
            "account": self.config.signal_account,
            "id": item["attachment_id"],
        }
        if item.get("group_id"):
            params["groupId"] = item["group_id"]
        elif item.get("sender"):
            params["recipient"] = item["sender"]
        result = rpc_request(self.config, "getAttachment", params)
        if not isinstance(result, dict) or not isinstance(result.get("data"), str):
            raise ApiError(HTTPStatus.NOT_FOUND, "attachment_not_found")
        content = base64.b64decode(result["data"])
        if len(content) > self.config.file_max_bytes:
            raise ApiError(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "file_too_large")
        content_type = str(item.get("content_type") or infer_mime_type(str(item.get("file_name") or "")))
        file_name = str(item.get("file_name") or file_id)
        return content, content_type, file_name


class RequestHandler(BaseHTTPRequestHandler):
    bridge: SignalOracleBridge
    config: Config

    server_version = "SignalOracleBridge/1.0"

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        logging.info("%s - %s", self.address_string(), format % args)

    def _require_auth(self) -> None:
        token = self.config.api_auth_token
        if not token:
            return
        header = self.headers.get("Authorization", "")
        expected = f"Bearer {token}"
        if header.strip() != expected:
            raise ApiError(HTTPStatus.UNAUTHORIZED, "unauthorized")

    def _read_json(self) -> Dict[str, object]:
        length = int(self.headers.get("Content-Length", "0") or "0")
        raw = self.rfile.read(length) if length > 0 else b"{}"
        try:
            decoded = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise ApiError(HTTPStatus.BAD_REQUEST, "invalid_json") from exc
        if not isinstance(decoded, dict):
            raise ApiError(HTTPStatus.BAD_REQUEST, "invalid_json")
        return decoded

    def _send_json(self, status: int, payload: Dict[str, object]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_bytes(self, status: int, body: bytes, content_type: str, file_name: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Content-Disposition", f'attachment; filename="{Path(file_name).name}"')
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        try:
            self._require_auth()
            parsed = urlparse(self.path)
            if parsed.path == "/health":
                self._send_json(HTTPStatus.OK, {"ok": True, "result": self.bridge.health()})
                return
            if parsed.path == "/updates":
                query = parse_qs(parsed.query)
                offset = int((query.get("offset") or ["1"])[0])
                timeout = int((query.get("timeout") or [str(self.config.max_long_poll_seconds)])[0])
                updates = self.bridge.get_updates(offset, timeout)
                self._send_json(HTTPStatus.OK, {"ok": True, "result": updates})
                return
            if parsed.path == "/files/meta":
                query = parse_qs(parsed.query)
                file_id = str((query.get("file_id") or [""])[0]).strip()
                if not file_id:
                    raise ApiError(HTTPStatus.BAD_REQUEST, "file_id_required")
                self._send_json(
                    HTTPStatus.OK,
                    {"ok": True, "result": self.bridge.get_file_meta(file_id)},
                )
                return
            if parsed.path == "/files/content":
                query = parse_qs(parsed.query)
                file_path = str((query.get("file_path") or [""])[0]).strip()
                if not file_path:
                    raise ApiError(HTTPStatus.BAD_REQUEST, "file_path_required")
                body, content_type, file_name = self.bridge.get_file_content(file_path)
                self._send_bytes(HTTPStatus.OK, body, content_type, file_name)
                return
            raise ApiError(HTTPStatus.NOT_FOUND, "not_found")
        except ApiError as exc:
            self._send_json(exc.status, {"ok": False, "description": str(exc)})
        except KeyError:
            self._send_json(HTTPStatus.NOT_FOUND, {"ok": False, "description": "not_found"})
        except Exception as exc:
            logging.exception("GET %s failed", self.path)
            self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"ok": False, "description": str(exc)})

    def do_POST(self) -> None:  # noqa: N802
        try:
            self._require_auth()
            payload = self._read_json()
            if self.path == "/messages":
                chat_id = int(str(payload.get("chat_id") or "0"))
                text = str(payload.get("text") or "")
                result = self.bridge.send_message(chat_id, text)
                self._send_json(HTTPStatus.OK, {"ok": True, "result": result})
                return
            if self.path == "/media":
                chat_id = int(str(payload.get("chat_id") or "0"))
                media_ref = str(payload.get("media_ref") or "").strip()
                media_type = str(payload.get("media_type") or "").strip()
                caption = str(payload.get("caption") or "")
                if not media_ref or not media_type:
                    raise ApiError(HTTPStatus.BAD_REQUEST, "media_ref_and_media_type_required")
                result = self.bridge.send_media(chat_id, media_ref, caption, media_type)
                self._send_json(HTTPStatus.OK, {"ok": True, "result": result})
                return
            if self.path == "/chat-action":
                chat_id = int(str(payload.get("chat_id") or "0"))
                action = str(payload.get("action") or "typing")
                self.bridge.send_chat_action(chat_id, action)
                self._send_json(HTTPStatus.OK, {"ok": True, "result": {}})
                return
            if self.path == "/messages/edit":
                self._send_json(
                    HTTPStatus.NOT_IMPLEMENTED,
                    {"ok": False, "description": "message_edit_not_supported"},
                )
                return
            raise ApiError(HTTPStatus.NOT_FOUND, "not_found")
        except ApiError as exc:
            self._send_json(exc.status, {"ok": False, "description": str(exc)})
        except Exception as exc:
            logging.exception("POST %s failed", self.path)
            self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"ok": False, "description": str(exc)})


def create_server(bridge: SignalOracleBridge, config: Config) -> ThreadingHTTPServer:
    class BoundHandler(RequestHandler):
        pass

    BoundHandler.bridge = bridge
    BoundHandler.config = config
    return ThreadingHTTPServer((config.api_host, config.api_port), BoundHandler)


def main() -> int:
    config = load_config()
    configure_logging(config.log_level)
    bridge = SignalOracleBridge(config)
    bridge.start()
    server = create_server(bridge, config)

    def handle_shutdown(signum, frame) -> None:  # type: ignore[unused-argument]
        logging.info("Shutdown signal received: %s", signum)
        server.shutdown()

    signal.signal(signal.SIGTERM, handle_shutdown)
    signal.signal(signal.SIGINT, handle_shutdown)

    try:
        logging.info("Signal oracle bridge listening on %s:%s", config.api_host, config.api_port)
        server.serve_forever()
    finally:
        bridge.stop()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
