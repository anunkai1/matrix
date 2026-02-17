#!/usr/bin/env python3
"""Telegram long-poll bridge to local Architect/Codex CLI."""

import argparse
import json
import logging
import os
import shlex
import subprocess
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

TELEGRAM_LIMIT = 4096


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
    rate_limit_per_minute: int
    executor_cmd: List[str]
    busy_message: str = "Another request is still running. Please wait."
    denied_message: str = "Access denied for this chat."
    timeout_message: str = "Request timed out. Please try a shorter prompt."
    generic_error_message: str = "Execution failed. Please try again later."
    empty_output_message: str = "(No output from Architect)"


@dataclass
class State:
    started_at: float = field(default_factory=time.time)
    busy_chats: Set[int] = field(default_factory=set)
    recent_requests: Dict[int, List[float]] = field(default_factory=dict)
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


def load_config() -> Config:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN is required")

    raw_chat_ids = os.getenv("TELEGRAM_ALLOWED_CHAT_IDS", "").strip()
    if not raw_chat_ids:
        raise ValueError("TELEGRAM_ALLOWED_CHAT_IDS is required")

    return Config(
        token=token,
        allowed_chat_ids=parse_allowed_chat_ids(raw_chat_ids),
        api_base=os.getenv("TELEGRAM_API_BASE", "https://api.telegram.org").rstrip("/"),
        poll_timeout_seconds=parse_int_env("TELEGRAM_POLL_TIMEOUT_SECONDS", 30),
        retry_sleep_seconds=float(os.getenv("TELEGRAM_RETRY_SLEEP_SECONDS", "3")),
        exec_timeout_seconds=parse_int_env("TELEGRAM_EXEC_TIMEOUT_SECONDS", 300),
        max_input_chars=parse_int_env("TELEGRAM_MAX_INPUT_CHARS", 4000),
        max_output_chars=parse_int_env("TELEGRAM_MAX_OUTPUT_CHARS", 20000),
        rate_limit_per_minute=parse_int_env("TELEGRAM_RATE_LIMIT_PER_MINUTE", 12),
        executor_cmd=parse_executor_cmd(),
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

    def get_updates(self, offset: int) -> List[Dict[str, object]]:
        payload: Dict[str, object] = {
            "offset": offset,
            "timeout": self.config.poll_timeout_seconds,
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


def run_executor(config: Config, prompt: str) -> subprocess.CompletedProcess[str]:
    logging.info("Running executor command: %s", config.executor_cmd)
    return subprocess.run(
        config.executor_cmd,
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


def build_help_text() -> str:
    return (
        "Commands:\n"
        "/start - bridge intro\n"
        "/help - show commands\n"
        "/status - show bridge health\n\n"
        "Any other message is sent to Architect."
    )


def build_status_text(state: State) -> str:
    uptime = int(time.time() - state.started_at)
    with state.lock:
        busy_count = len(state.busy_chats)
    return (
        "Bridge status: healthy\n"
        f"Uptime: {uptime}s\n"
        f"Busy chats: {busy_count}"
    )


def process_prompt(
    state: State,
    config: Config,
    client: TelegramClient,
    chat_id: int,
    message_id: Optional[int],
    prompt: str,
) -> None:
    try:
        try:
            result = run_executor(config, prompt)
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

        output = (result.stdout or "").strip()
        if not output:
            output = config.empty_output_message
        output = trim_output(output, config.max_output_chars)
        client.send_message(chat_id, output, reply_to_message_id=message_id)
    finally:
        clear_busy(state, chat_id)


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

    text = message.get("text")
    if not isinstance(text, str):
        return

    if chat_id not in config.allowed_chat_ids:
        logging.warning("Denied non-allowlisted chat_id=%s", chat_id)
        client.send_message(chat_id, config.denied_message, reply_to_message_id=message_id)
        return

    command = normalize_command(text)
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
        client.send_message(chat_id, build_status_text(state), reply_to_message_id=message_id)
        return

    prompt = text.strip()
    if not prompt:
        return

    if len(prompt) > config.max_input_chars:
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

    if not mark_busy(state, chat_id):
        client.send_message(
            chat_id,
            config.busy_message,
            reply_to_message_id=message_id,
        )
        return

    worker = threading.Thread(
        target=process_prompt,
        args=(state, config, client, chat_id, message_id, prompt),
        daemon=True,
    )
    worker.start()


def run_self_test() -> int:
    sample = "x" * (TELEGRAM_LIMIT + 50)
    chunks = to_telegram_chunks(sample)
    if len(chunks) < 2:
        raise RuntimeError("Chunking self-test failed")
    print("self-test: ok")
    return 0


def run_bridge(config: Config) -> int:
    state = State()
    client = TelegramClient(config)
    offset = 0

    logging.info("Bridge started. Allowed chats=%s", sorted(config.allowed_chat_ids))
    logging.info("Executor command=%s", config.executor_cmd)

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
