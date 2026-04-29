import importlib.util
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
BRIDGE_MAIN = ROOT / "src" / "telegram_bridge" / "main.py"
BRIDGE_DIR = BRIDGE_MAIN.parent


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

bridge_main = load_module("telegram_bridge_main_diary_tests", BRIDGE_DIR / "main.py")
bridge_handlers = sys.modules["handlers"]
bridge_state_store = sys.modules["state_store"]
diary_store = sys.modules["diary_store"]


class FakeDiaryClient:
    channel_name = "telegram"
    supports_message_edits = False

    def __init__(self) -> None:
        self.messages = []
        self.chat_actions = []

    def send_message_get_id(
        self,
        chat_id,
        text,
        reply_to_message_id=None,
        message_thread_id=None,
    ):
        self.send_message(
            chat_id,
            text,
            reply_to_message_id=reply_to_message_id,
            message_thread_id=message_thread_id,
        )
        return len(self.messages)

    def send_message(self, chat_id, text, reply_to_message_id=None, message_thread_id=None):
        del message_thread_id
        self.messages.append((chat_id, text, reply_to_message_id))

    def send_chat_action(self, chat_id, action="typing", message_thread_id=None):
        del message_thread_id
        self.chat_actions.append((chat_id, action))


def make_config(state_dir: str):
    return bridge_main.Config(
        token="token",
        allowed_chat_ids={1},
        api_base="https://api.telegram.org",
        poll_timeout_seconds=1,
        retry_sleep_seconds=0.1,
        exec_timeout_seconds=3,
        max_input_chars=4096,
        max_output_chars=20000,
        max_image_bytes=4096,
        max_voice_bytes=4096,
        max_document_bytes=4096,
        attachment_retention_seconds=3600,
        attachment_max_total_bytes=1024 * 1024,
        rate_limit_per_minute=120,
        executor_cmd=["/bin/echo"],
        voice_transcribe_cmd=[],
        voice_transcribe_timeout_seconds=10,
        voice_alias_replacements=[],
        voice_alias_learning_enabled=False,
        voice_alias_learning_path=str(Path(state_dir) / "voice_alias_learning.json"),
        voice_alias_learning_min_examples=2,
        voice_alias_learning_confirmation_window_seconds=900,
        voice_low_confidence_confirmation_enabled=False,
        voice_low_confidence_threshold=0.45,
        voice_low_confidence_message="Voice transcript confidence is low, resend",
        state_dir=state_dir,
        persistent_workers_enabled=False,
        persistent_workers_max=2,
        persistent_workers_idle_timeout_seconds=120,
        persistent_workers_policy_files=[],
        canonical_sessions_enabled=False,
        canonical_legacy_mirror_enabled=False,
        canonical_sqlite_enabled=False,
        canonical_sqlite_path=str(Path(state_dir) / "chat_sessions.sqlite3"),
        canonical_json_mirror_enabled=False,
        memory_sqlite_path=str(Path(state_dir) / "memory.sqlite3"),
        memory_max_messages_per_key=4000,
        memory_max_summaries_per_key=80,
        memory_prune_interval_seconds=300,
        required_prefixes=[],
        required_prefix_ignore_case=True,
        require_prefix_in_private=False,
        allow_private_chats_unlisted=False,
        allow_group_chats_unlisted=False,
        assistant_name="Diary",
        shared_memory_key="",
        channel_plugin="telegram",
        engine_plugin="codex",
        selectable_engine_plugins=["codex", "gemma", "pi"],
        codex_model="gpt-5.4-mini",
        codex_reasoning_effort="medium",
        gemma_provider="ollama_ssh",
        gemma_model="gemma4:26b",
        gemma_base_url="http://127.0.0.1:11434",
        gemma_ssh_host="server4-beast",
        gemma_request_timeout_seconds=180,
        venice_api_key="",
        venice_base_url="https://api.venice.ai/api/v1",
        venice_model="mistral-31-24b",
        venice_temperature=0.2,
        venice_request_timeout_seconds=180,
        chatgpt_web_bridge_script=str(ROOT / "ops" / "chatgpt_web_bridge.py"),
        chatgpt_web_python_bin="python3",
        chatgpt_web_browser_brain_url="http://127.0.0.1:47831",
        chatgpt_web_browser_brain_service="server3-browser-brain.service",
        chatgpt_web_url="https://chatgpt.com/",
        chatgpt_web_start_service=True,
        chatgpt_web_request_timeout_seconds=30,
        chatgpt_web_ready_timeout_seconds=45,
        chatgpt_web_response_timeout_seconds=180,
        chatgpt_web_poll_seconds=3.0,
        pi_provider="ollama",
        pi_model="gemma4:26b",
        pi_runner="ssh",
        pi_bin="pi",
        pi_ssh_host="server4-beast",
        pi_local_cwd="/tmp",
        pi_remote_cwd="/tmp",
        pi_session_mode="none",
        pi_session_dir="",
        pi_session_max_bytes=2 * 1024 * 1024,
        pi_session_max_age_seconds=7 * 24 * 60 * 60,
        pi_session_archive_retention_seconds=14 * 24 * 60 * 60,
        pi_session_archive_dir="",
        pi_tools_mode="default",
        pi_tools_allowlist="",
        pi_extra_args="",
        pi_ollama_tunnel_enabled=True,
        pi_ollama_tunnel_local_port=11435,
        pi_ollama_tunnel_remote_host="127.0.0.1",
        pi_ollama_tunnel_remote_port=11434,
        pi_request_timeout_seconds=180,
        whatsapp_plugin_enabled=False,
        whatsapp_bridge_api_base="http://127.0.0.1:8787",
        whatsapp_bridge_auth_token="",
        whatsapp_poll_timeout_seconds=20,
        signal_plugin_enabled=False,
        signal_bridge_api_base="http://127.0.0.1:18797",
        signal_bridge_auth_token="",
        signal_poll_timeout_seconds=20,
        keyword_routing_enabled=False,
        diary_mode_enabled=True,
        diary_capture_quiet_window_seconds=1,
        diary_timezone="Australia/Brisbane",
        diary_local_root=str(Path(state_dir) / "diary"),
        diary_nextcloud_enabled=False,
        diary_nextcloud_base_url="",
        diary_nextcloud_username="",
        diary_nextcloud_app_password="",
        diary_nextcloud_remote_root="/Diary",
        affective_runtime_enabled=False,
        affective_runtime_db_path=str(Path(state_dir) / "affective.sqlite3"),
        affective_runtime_ping_target="",
        policy_reset_memory_on_change=False,
        progress_label="",
        progress_elapsed_prefix="Already",
        progress_elapsed_suffix="s",
        busy_message="Another request is still running. Please wait.",
        denied_message="Access denied for this chat.",
        timeout_message="Request timed out. Please try a shorter prompt.",
        generic_error_message="Execution failed. Please try again later.",
        image_download_error_message="Image download failed. Please send another image.",
        voice_download_error_message="Voice download failed. Please send another voice message.",
        document_download_error_message="File download failed. Please send another file.",
        voice_not_configured_message="Voice transcription is not configured. Please ask admin to set TELEGRAM_VOICE_TRANSCRIBE_CMD.",
        voice_transcribe_error_message="Voice transcription failed. Please send clearer audio.",
        voice_transcribe_empty_message="Voice transcription was empty. Please send clearer audio.",
        empty_output_message="(No output from Diary)",
    )


class DiaryBridgeFlowTests(unittest.TestCase):
    def test_handle_update_saves_text_message_into_daily_docx(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config = make_config(tmpdir)
            state = bridge_state_store.State()
            client = FakeDiaryClient()
            update = {
                "update_id": 1,
                "message": {
                    "message_id": 101,
                    "date": int(time.time()),
                    "chat": {"id": 1, "type": "private"},
                    "from": {"id": 1, "first_name": "User"},
                    "text": "We arrived at the beach and went for a walk.",
                },
            }

            bridge_handlers.handle_update(state, config, client, update)

            deadline = time.time() + 5
            while time.time() < deadline:
                if any("Saved " in text for _, text, _ in client.messages):
                    break
                time.sleep(0.2)

            self.assertTrue(any("Saved " in text for _, text, _ in client.messages))
            today = diary_store.dt.datetime.now(diary_store.diary_timezone(config)).date()
            docx_path = diary_store.diary_day_docx_path(config, today)
            self.assertTrue(docx_path.exists())
            entries = diary_store.read_day_entries(config, today)
            self.assertEqual(len(entries), 1)
            self.assertIn("beach", entries[0].title.lower())

    def test_diary_queue_keeps_later_batches_separate_while_first_is_processing(self) -> None:
        config = make_config(tempfile.mkdtemp())
        state = bridge_state_store.State()
        client = FakeDiaryClient()
        processed = []

        def fake_process_diary_batch(state, config, client, scope_key, pending):
            processed.append([message.get("text") for message in pending.messages])
            time.sleep(2.0)
            bridge_handlers.finalize_chat_work(
                state,
                client,
                chat_id=pending.chat_id,
                scope_key=scope_key,
            )

        with mock.patch.object(bridge_handlers, "process_diary_batch", side_effect=fake_process_diary_batch):
            bridge_handlers.handle_update(
                state,
                config,
                client,
                {
                    "update_id": 1,
                    "message": {
                        "message_id": 1,
                        "date": int(time.time()),
                        "chat": {"id": 1, "type": "private"},
                        "from": {"id": 1, "first_name": "User"},
                        "text": "first batch",
                    },
                },
            )
            time.sleep(1.3)
            bridge_handlers.handle_update(
                state,
                config,
                client,
                {
                    "update_id": 2,
                    "message": {
                        "message_id": 2,
                        "date": int(time.time()),
                        "chat": {"id": 1, "type": "private"},
                        "from": {"id": 1, "first_name": "User"},
                        "text": "second batch",
                    },
                },
            )
            time.sleep(1.3)
            bridge_handlers.handle_update(
                state,
                config,
                client,
                {
                    "update_id": 3,
                    "message": {
                        "message_id": 3,
                        "date": int(time.time()),
                        "chat": {"id": 1, "type": "private"},
                        "from": {"id": 1, "first_name": "User"},
                        "text": "third batch",
                    },
                },
            )
            deadline = time.time() + 8
            while time.time() < deadline:
                if len(processed) >= 3:
                    break
                time.sleep(0.25)

        self.assertEqual(processed, [["first batch"], ["second batch"], ["third batch"]])


if __name__ == "__main__":
    unittest.main()
