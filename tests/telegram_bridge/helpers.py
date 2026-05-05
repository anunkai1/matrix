import io
import json
import logging
import os
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import sys

ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

import telegram_bridge.executor as bridge_executor
import telegram_bridge.handlers as bridge_handlers
import telegram_bridge.prompt_execution as bridge_prompt_execution
import telegram_bridge.special_request_processing as bridge_special_request_processing
import telegram_bridge.auth_state as bridge_auth_state
import telegram_bridge.channel_adapter as bridge_channel_adapter
import telegram_bridge.command_routing as bridge_command_routing
import telegram_bridge.control_commands as bridge_control_commands
import telegram_bridge.engine_adapter as bridge_engine_adapter
import telegram_bridge.main as bridge
import telegram_bridge.http_channel as bridge_http_channel
import telegram_bridge.plugin_registry as bridge_plugin_registry
import telegram_bridge.signal_channel as bridge_signal_channel
import telegram_bridge.whatsapp_channel as bridge_whatsapp_channel
import telegram_bridge.session_manager as bridge_session_manager
import telegram_bridge.structured_logging as bridge_structured_logging
import telegram_bridge.transport as bridge_transport
import telegram_bridge.voice_alias_commands as bridge_voice_alias_commands

class FakeTelegramClient:
    def __init__(self, channel_name: str = "telegram") -> None:
        self.channel_name = channel_name
        self.messages = []
        self.edits = []
        self.callback_answers = []
        self.photos = []
        self.documents = []
        self.audios = []
        self.voices = []
        self.chat_actions = []
        self.raise_on_voice = None

    def send_message_get_id(
        self,
        chat_id,
        text,
        reply_to_message_id=None,
        message_thread_id=None,
        reply_markup=None,
    ):
        self.send_message(
            chat_id,
            text,
            reply_to_message_id=reply_to_message_id,
            message_thread_id=message_thread_id,
            reply_markup=reply_markup,
        )
        return len(self.messages)

    def send_message(
        self,
        chat_id,
        text,
        reply_to_message_id=None,
        message_thread_id=None,
        reply_markup=None,
    ):
        del message_thread_id
        self.messages.append((chat_id, text, reply_to_message_id, reply_markup))

    def edit_message(self, chat_id, message_id, text, reply_markup=None):
        self.edits.append((chat_id, message_id, text, reply_markup))

    def answer_callback_query(self, callback_query_id, text=None):
        self.callback_answers.append((callback_query_id, text))

    def send_photo(
        self,
        chat_id,
        photo,
        caption=None,
        reply_to_message_id=None,
        message_thread_id=None,
    ):
        del message_thread_id
        self.photos.append((chat_id, photo, caption, reply_to_message_id))

    def send_document(
        self,
        chat_id,
        document,
        caption=None,
        reply_to_message_id=None,
        message_thread_id=None,
    ):
        del message_thread_id
        self.documents.append((chat_id, document, caption, reply_to_message_id))

    def send_audio(
        self,
        chat_id,
        audio,
        caption=None,
        reply_to_message_id=None,
        message_thread_id=None,
    ):
        del message_thread_id
        self.audios.append((chat_id, audio, caption, reply_to_message_id))

    def send_voice(
        self,
        chat_id,
        voice,
        caption=None,
        reply_to_message_id=None,
        message_thread_id=None,
    ):
        del message_thread_id
        if self.raise_on_voice is not None:
            raise self.raise_on_voice
        self.voices.append((chat_id, voice, caption, reply_to_message_id))

    def send_chat_action(self, chat_id, action="typing", message_thread_id=None):
        del message_thread_id
        self.chat_actions.append((chat_id, action))

class FakeDownloadClient:
    def __init__(self, file_meta):
        self.file_meta = file_meta
        self.download_calls = 0

    def get_file(self, file_id):
        return dict(self.file_meta)

    def download_file_to_path(self, file_path, target_path, max_bytes, size_label="File"):
        self.download_calls += 1
        Path(target_path).write_bytes(b"x")

class FakeProgressEditClient:
    channel_name = "whatsapp"
    supports_message_edits = True

    def __init__(self) -> None:
        self.last_thread_id = None

    def send_message_get_id(
        self,
        chat_id,
        text,
        reply_to_message_id=None,
        message_thread_id=None,
    ):
        self.last_thread_id = message_thread_id
        return 101

    def edit_message(self, chat_id, message_id, text, reply_markup=None):
        del reply_markup
        raise RuntimeError("WhatsApp bridge HTTP 502: message edit failed")

    def send_chat_action(self, chat_id, action="typing", message_thread_id=None):
        self.last_thread_id = message_thread_id
        return None

class FakeSignalProgressClient:
    channel_name = "signal"
    supports_message_edits = False

    def send_message_get_id(
        self,
        chat_id,
        text,
        reply_to_message_id=None,
        message_thread_id=None,
    ):
        return 202

    def edit_message(self, chat_id, message_id, text, reply_markup=None):
        del reply_markup
        raise AssertionError("edit_message should not be called for signal")

    def send_chat_action(self, chat_id, action="typing", message_thread_id=None):
        return None

def make_config(**overrides):
    base = {
        "token": "x",
        "allowed_chat_ids": {1, 2, 3},
        "api_base": "https://api.telegram.org",
        "poll_timeout_seconds": 1,
        "retry_sleep_seconds": 0.1,
        "exec_timeout_seconds": 3,
        "max_input_chars": 4096,
        "max_output_chars": 20000,
        "max_image_bytes": 4096,
        "max_voice_bytes": 4096,
        "max_document_bytes": 4096,
        "attachment_retention_seconds": 14 * 24 * 60 * 60,
        "attachment_max_total_bytes": 10 * 1024 * 1024 * 1024,
        "rate_limit_per_minute": 12,
        "executor_cmd": ["/bin/echo"],
        "voice_transcribe_cmd": [],
        "voice_transcribe_timeout_seconds": 10,
        "voice_alias_replacements": [],
        "voice_alias_learning_enabled": True,
        "voice_alias_learning_path": "/tmp/voice_alias_learning.json",
        "voice_alias_learning_min_examples": 2,
        "voice_alias_learning_confirmation_window_seconds": 900,
        "voice_low_confidence_confirmation_enabled": True,
        "voice_low_confidence_threshold": 0.45,
        "voice_low_confidence_message": "Voice transcript confidence is low, resend",
        "state_dir": "/tmp",
        "persistent_workers_enabled": False,
        "persistent_workers_max": 2,
        "persistent_workers_idle_timeout_seconds": 120,
        "persistent_workers_policy_files": [],
        "canonical_sessions_enabled": False,
        "canonical_legacy_mirror_enabled": False,
        "canonical_sqlite_enabled": False,
        "canonical_sqlite_path": "/tmp/chat_sessions.sqlite3",
        "canonical_json_mirror_enabled": False,
        "required_prefixes": [],
        "required_prefix_ignore_case": True,
        "require_prefix_in_private": True,
        "allow_private_chats_unlisted": False,
        "allow_group_chats_unlisted": False,
        "assistant_name": "Architect",
        "channel_plugin": "telegram",
        "engine_plugin": "codex",
        "selectable_engine_plugins": ["codex", "gemma", "pi"],
        "codex_model": "gpt-5.4-mini",
        "codex_reasoning_effort": "medium",
        "gemma_provider": "ollama_ssh",
        "gemma_model": "gemma4:26b",
        "gemma_base_url": "http://127.0.0.1:11434",
        "gemma_ssh_host": "server4-beast",
        "gemma_request_timeout_seconds": 180,
        "venice_api_key": "",
        "venice_base_url": "https://api.venice.ai/api/v1",
        "venice_model": "mistral-31-24b",
        "venice_temperature": 0.2,
        "venice_request_timeout_seconds": 180,
        "chatgpt_web_bridge_script": "/home/architect/matrix/ops/chatgpt_web_bridge.py",
        "chatgpt_web_python_bin": "python3",
        "chatgpt_web_browser_brain_url": "http://127.0.0.1:47831",
        "chatgpt_web_browser_brain_service": "server3-browser-brain.service",
        "chatgpt_web_url": "https://chatgpt.com/",
        "chatgpt_web_start_service": True,
        "chatgpt_web_request_timeout_seconds": 30,
        "chatgpt_web_ready_timeout_seconds": 45,
        "chatgpt_web_response_timeout_seconds": 180,
        "chatgpt_web_poll_seconds": 3.0,
        "pi_provider": "ollama",
        "pi_model": "qwen3-coder:30b",
        "pi_runner": "ssh",
        "pi_bin": "pi",
        "pi_ssh_host": "server4-beast",
        "pi_local_cwd": "/tmp",
        "pi_remote_cwd": "/tmp",
        "pi_session_mode": "none",
        "pi_session_dir": "",
        "pi_session_max_bytes": 2 * 1024 * 1024,
        "pi_session_max_age_seconds": 7 * 24 * 60 * 60,
        "pi_session_archive_retention_seconds": 14 * 24 * 60 * 60,
        "pi_session_archive_dir": "",
        "pi_tools_mode": "default",
        "pi_tools_allowlist": "",
        "pi_extra_args": "",
        "pi_ollama_tunnel_enabled": True,
        "pi_ollama_tunnel_local_port": 11435,
        "pi_ollama_tunnel_remote_host": "127.0.0.1",
        "pi_ollama_tunnel_remote_port": 11434,
        "pi_request_timeout_seconds": 180,
        "whatsapp_plugin_enabled": False,
        "whatsapp_bridge_api_base": "http://127.0.0.1:8787",
        "whatsapp_bridge_auth_token": "",
        "whatsapp_poll_timeout_seconds": 20,
        "signal_plugin_enabled": False,
        "signal_bridge_api_base": "http://127.0.0.1:18797",
        "signal_bridge_auth_token": "",
        "signal_poll_timeout_seconds": 20,
        "keyword_routing_enabled": True,
        "diary_mode_enabled": False,
        "diary_capture_quiet_window_seconds": 75,
        "diary_timezone": "Australia/Brisbane",
        "diary_local_root": "/tmp/diary",
        "diary_nextcloud_enabled": False,
        "diary_nextcloud_base_url": "",
        "diary_nextcloud_username": "",
        "diary_nextcloud_app_password": "",
        "diary_nextcloud_remote_root": "/Diary",
    }
    base.update(overrides)
    return bridge.Config(**base)
