import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
BRIDGE_MAIN = ROOT / "src" / "telegram_bridge" / "main.py"
BRIDGE_DIR = BRIDGE_MAIN.parent

spec = importlib.util.spec_from_file_location("telegram_bridge_main_phase_timing", BRIDGE_MAIN)
if spec is None or spec.loader is None:
    raise RuntimeError("Failed to load telegram bridge module spec")
bridge = importlib.util.module_from_spec(spec)
if str(BRIDGE_DIR) not in sys.path:
    sys.path.insert(0, str(BRIDGE_DIR))
sys.modules[spec.name] = bridge
spec.loader.exec_module(bridge)
import handlers as bridge_handlers


class FakeTelegramClient:
    channel_name = "telegram"
    supports_message_edits = False

    def __init__(self) -> None:
        self.messages = []
        self.progress_messages = []
        self.chat_actions = []

    def send_message_get_id(self, chat_id, text, reply_to_message_id=None, message_thread_id=None):
        self.progress_messages.append((chat_id, text, reply_to_message_id, message_thread_id))
        return len(self.progress_messages)

    def send_message(self, chat_id, text, reply_to_message_id=None, message_thread_id=None):
        self.messages.append((chat_id, text, reply_to_message_id, message_thread_id))

    def send_chat_action(self, chat_id, action="typing", message_thread_id=None):
        self.chat_actions.append((chat_id, action, message_thread_id))


class FakeEngine:
    engine_name = "fake"

    def run(
        self,
        config,
        prompt,
        thread_id,
        session_key=None,
        channel_name=None,
        actor_chat_id=None,
        actor_user_id=None,
        image_path=None,
        image_paths=None,
        progress_callback=None,
        cancel_event=None,
    ):
        del config, prompt, thread_id, session_key, channel_name, actor_chat_id, actor_user_id
        del image_path, image_paths, progress_callback, cancel_event
        return subprocess.CompletedProcess(
            args=["fake"],
            returncode=0,
            stdout="THREAD_ID=test-thread\nOUTPUT_BEGIN\nhello from fake engine",
            stderr="",
        )


def make_config(**overrides):
    tmpdir = tempfile.mkdtemp(prefix="phase-timing-test-")
    base = {
        "token": "x",
        "allowed_chat_ids": {1},
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
        "attachment_max_total_bytes": 10 * 1024 * 1024,
        "rate_limit_per_minute": 100,
        "executor_cmd": ["/bin/echo"],
        "voice_transcribe_cmd": [],
        "voice_transcribe_timeout_seconds": 10,
        "voice_not_configured_message": "Voice transcription is not configured.",
        "voice_download_error_message": "Voice download failed.",
        "voice_transcribe_error_message": "Voice transcription failed.",
        "voice_transcribe_empty_message": "Voice transcription was empty.",
        "image_download_error_message": "Image download failed.",
        "document_download_error_message": "Document download failed.",
        "voice_alias_replacements": [],
        "voice_alias_learning_enabled": False,
        "voice_alias_learning_path": str(Path(tmpdir) / "voice_alias_learning.json"),
        "voice_alias_learning_min_examples": 2,
        "voice_alias_learning_confirmation_window_seconds": 900,
        "voice_low_confidence_confirmation_enabled": False,
        "voice_low_confidence_threshold": 0.45,
        "voice_low_confidence_message": "Voice transcript confidence is low.",
        "state_dir": tmpdir,
        "persistent_workers_enabled": False,
        "persistent_workers_max": 2,
        "persistent_workers_idle_timeout_seconds": 120,
        "persistent_workers_policy_files": [],
        "canonical_sessions_enabled": False,
        "canonical_legacy_mirror_enabled": False,
        "canonical_sqlite_enabled": False,
        "canonical_sqlite_path": str(Path(tmpdir) / "chat_sessions.sqlite3"),
        "canonical_json_mirror_enabled": False,
        "memory_sqlite_path": str(Path(tmpdir) / "memory.sqlite3"),
        "memory_max_messages_per_key": 4000,
        "memory_max_summaries_per_key": 80,
        "memory_prune_interval_seconds": 300,
        "required_prefixes": [],
        "required_prefix_ignore_case": True,
        "require_prefix_in_private": True,
        "allow_private_chats_unlisted": False,
        "allow_group_chats_unlisted": False,
        "assistant_name": "Architect",
        "shared_memory_key": "",
        "channel_plugin": "telegram",
        "engine_plugin": "codex",
        "selectable_engine_plugins": ["codex", "gemma", "pi"],
        "gemma_provider": "ollama_ssh",
        "gemma_model": "gemma4:26b",
        "gemma_base_url": "http://127.0.0.1:11434",
        "gemma_ssh_host": "server4-beast",
        "gemma_request_timeout_seconds": 180,
        "pi_provider": "ollama",
        "pi_model": "gemma4:26b",
        "pi_ssh_host": "server4-beast",
        "pi_remote_cwd": "/tmp",
        "pi_tools_mode": "default",
        "pi_tools_allowlist": "",
        "pi_extra_args": "",
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
        "diary_local_root": str(Path(tmpdir) / "diary"),
        "diary_nextcloud_enabled": False,
        "denied_message": "Denied",
        "busy_message": "Busy",
        "timeout_message": "Timed out.",
        "generic_error_message": "Something went wrong.",
        "empty_output_message": "(empty output)",
        "progress_label": "",
        "progress_elapsed_prefix": "Already",
        "progress_elapsed_suffix": "s",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


class PhaseTimingTests(unittest.TestCase):
    def test_handle_update_emits_phase_timing_events(self) -> None:
        state = bridge.State()
        client = FakeTelegramClient()
        config = make_config()
        update = {
            "update_id": 1,
            "message": {
                "message_id": 10,
                "chat": {"id": 1, "type": "private"},
                "from": {"id": 42, "first_name": "User"},
                "text": "hello",
            },
        }

        def sync_start_message_worker(*args, **kwargs):
            return bridge_handlers.process_message_worker(*args, **kwargs)

        with (
            mock.patch.object(bridge_handlers, "start_message_worker", side_effect=sync_start_message_worker),
            mock.patch.object(bridge_handlers, "emit_event") as emit_mock,
        ):
            bridge.handle_update(state, config, client, update, engine=FakeEngine())

        phase_events = [
            call.kwargs["fields"]["phase"]
            for call in emit_mock.call_args_list
            if call.args
            and call.args[0] == "bridge.request_phase_timing"
            and "phase" in call.kwargs.get("fields", {})
        ]
        self.assertIn("handle_update_pre_worker", phase_events)
        self.assertIn("prepare_prompt_input", phase_events)
        self.assertIn("begin_memory_turn", phase_events)
        self.assertIn("begin_affective_turn", phase_events)
        self.assertIn("engine_run", phase_events)
        self.assertIn("execute_prompt_with_retry", phase_events)
        self.assertIn("finalize_prompt_success", phase_events)
        self.assertIn("process_prompt_total", phase_events)


if __name__ == "__main__":
    unittest.main()
