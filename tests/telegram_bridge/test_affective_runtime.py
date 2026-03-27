import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
BRIDGE_DIR = ROOT / "src" / "telegram_bridge"


def load_module(module_name: str, path: Path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Failed to load module spec for {module_name}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


if str(BRIDGE_DIR) not in sys.path:
    sys.path.insert(0, str(BRIDGE_DIR))

bridge_main = load_module("telegram_bridge_main_affective_tests", BRIDGE_DIR / "main.py")
bridge_handlers = sys.modules["handlers"]
bridge_state_store = sys.modules["state_store"]
bridge_affective_runtime = sys.modules["affective_runtime"]


class FakeClient:
    channel_name = "telegram"
    supports_message_edits = False

    def __init__(self) -> None:
        self.messages = []
        self.chat_actions = []

    def send_message_get_id(self, chat_id, text, reply_to_message_id=None):
        self.send_message(chat_id, text, reply_to_message_id=reply_to_message_id)
        return len(self.messages)

    def send_message(self, chat_id, text, reply_to_message_id=None):
        self.messages.append((chat_id, text, reply_to_message_id))

    def send_chat_action(self, chat_id, action="typing"):
        self.chat_actions.append((chat_id, action))


class RecordingEngine:
    engine_name = "recording"

    def __init__(self, *, returncode: int = 0, output_text: str = "ok") -> None:
        self.returncode = returncode
        self.output_text = output_text
        self.prompts = []

    def run(
        self,
        config,
        prompt: str,
        thread_id,
        session_key=None,
        channel_name=None,
        image_path=None,
        progress_callback=None,
        cancel_event=None,
    ) -> subprocess.CompletedProcess[str]:
        del config, thread_id, session_key, channel_name, image_path, progress_callback, cancel_event
        self.prompts.append(prompt)
        if self.returncode == 0:
            stdout = json.dumps(
                {
                    "type": "item.completed",
                    "item": {"type": "agent_message", "text": self.output_text},
                }
            )
            return subprocess.CompletedProcess(args=["recording"], returncode=0, stdout=stdout, stderr="")
        return subprocess.CompletedProcess(
            args=["recording"],
            returncode=self.returncode,
            stdout="",
            stderr="forced failure",
        )


def make_config(**overrides):
    base = {
        "token": "token",
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
        "attachment_retention_seconds": 3600,
        "attachment_max_total_bytes": 1024 * 1024,
        "rate_limit_per_minute": 12,
        "executor_cmd": ["/bin/echo"],
        "voice_transcribe_cmd": [],
        "voice_transcribe_timeout_seconds": 10,
        "voice_alias_replacements": [],
        "voice_alias_learning_enabled": False,
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
        "memory_sqlite_path": "/tmp/memory.sqlite3",
        "memory_max_messages_per_key": 4000,
        "memory_max_summaries_per_key": 80,
        "memory_prune_interval_seconds": 300,
        "required_prefixes": [],
        "required_prefix_ignore_case": True,
        "require_prefix_in_private": False,
        "allow_private_chats_unlisted": False,
        "allow_group_chats_unlisted": False,
        "assistant_name": "Trinity",
        "shared_memory_key": "",
        "channel_plugin": "telegram",
        "engine_plugin": "codex",
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
        "affective_runtime_enabled": False,
        "affective_runtime_db_path": "",
        "affective_runtime_ping_target": "1.1.1.1",
        "empty_output_message": "(No output from Trinity)",
    }
    base.update(overrides)
    return bridge_main.Config(**base)


class AffectiveRuntimeTests(unittest.TestCase):
    def test_state_persists_across_restart(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "affective.sqlite3")
            runtime = bridge_affective_runtime.AffectiveRuntime(db_path, ping_target="")
            runtime.begin_turn("thanks this is excellent")
            runtime.finish_turn(success=True)
            snapshot = runtime.telemetry()["state"]

            restored = bridge_affective_runtime.AffectiveRuntime(db_path, ping_target="")
            restored_snapshot = restored.telemetry()["state"]

        self.assertAlmostEqual(restored_snapshot["valence"], snapshot["valence"], places=5)
        self.assertAlmostEqual(restored_snapshot["confidence"], snapshot["confidence"], places=5)
        self.assertAlmostEqual(restored_snapshot["trust_user"], snapshot["trust_user"], places=5)

    def test_failure_path_raises_stress_and_reduces_confidence(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime = bridge_affective_runtime.AffectiveRuntime(
                str(Path(tmpdir) / "affective-failure-test.sqlite3"),
                ping_target="",
            )
            runtime.begin_turn("this is broken and wrong")
            runtime.finish_turn(success=False)
            state = runtime.telemetry()["state"]
        self.assertGreater(state["stress"], 0.0)
        self.assertLess(state["confidence"], 0.0)

    def test_process_prompt_includes_affective_block_when_enabled(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = make_config(
                state_dir=tmpdir,
                affective_runtime_enabled=True,
                affective_runtime_db_path=str(Path(tmpdir) / "affective.sqlite3"),
                affective_runtime_ping_target="",
            )
            state = bridge_state_store.State(
                affective_runtime=bridge_affective_runtime.build_affective_runtime(config)
            )
            client = FakeClient()
            engine = RecordingEngine(output_text="first response")

            bridge_handlers.process_prompt(
                state=state,
                config=config,
                client=client,
                engine=engine,
                scope_key="tg:1",
                chat_id=1,
                message_thread_id=None,
                message_id=101,
                prompt="Thanks, can you help me think this through?",
                photo_file_id=None,
                voice_file_id=None,
                document=None,
            )
            bridge_handlers.process_prompt(
                state=state,
                config=config,
                client=client,
                engine=engine,
                scope_key="tg:1",
                chat_id=1,
                message_thread_id=None,
                message_id=102,
                prompt="This still matters, give me the next step.",
                photo_file_id=None,
                voice_file_id=None,
                document=None,
            )

        self.assertEqual(len(engine.prompts), 2)
        self.assertIn("Affective runtime context", engine.prompts[0])
        self.assertIn("User request:\nThanks, can you help me think this through?", engine.prompts[0])
        self.assertIn("Affective runtime context", engine.prompts[1])
        self.assertEqual(client.messages[-1][1], "first response")

    def test_disabled_mode_keeps_legacy_prompt_path(self):
        config = make_config(affective_runtime_enabled=False)
        state = bridge_state_store.State()
        client = FakeClient()
        engine = RecordingEngine(output_text="plain response")

        bridge_handlers.process_prompt(
            state=state,
            config=config,
            client=client,
            engine=engine,
            scope_key="tg:1",
            chat_id=1,
            message_thread_id=None,
            message_id=201,
            prompt="Plain request",
            photo_file_id=None,
            voice_file_id=None,
            document=None,
        )

        self.assertEqual(engine.prompts, ["Plain request"])
        self.assertEqual(client.messages[-1][1], "plain response")

    def test_db_or_ping_failure_fails_open(self):
        config = make_config(
            state_dir="/tmp",
            affective_runtime_enabled=True,
            affective_runtime_db_path="/proc/does-not-exist/affective.sqlite3",
            affective_runtime_ping_target="invalid.invalid",
        )
        state = bridge_state_store.State(
            affective_runtime=bridge_affective_runtime.build_affective_runtime(config)
        )
        client = FakeClient()
        engine = RecordingEngine(output_text="still works")

        bridge_handlers.process_prompt(
            state=state,
            config=config,
            client=client,
            engine=engine,
            scope_key="tg:1",
            chat_id=1,
            message_thread_id=None,
            message_id=301,
            prompt="Can you still answer if storage is broken?",
            photo_file_id=None,
            voice_file_id=None,
            document=None,
        )

        self.assertEqual(client.messages[-1][1], "still works")
        self.assertIn("Affective runtime context", engine.prompts[0])



if __name__ == "__main__":
    unittest.main()
