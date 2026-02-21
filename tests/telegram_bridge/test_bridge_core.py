import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BRIDGE_MAIN = ROOT / "src" / "telegram_bridge" / "main.py"
BRIDGE_DIR = BRIDGE_MAIN.parent

spec = importlib.util.spec_from_file_location("telegram_bridge_main", BRIDGE_MAIN)
if spec is None or spec.loader is None:
    raise RuntimeError("Failed to load telegram bridge module spec")
bridge = importlib.util.module_from_spec(spec)
import sys
if str(BRIDGE_DIR) not in sys.path:
    sys.path.insert(0, str(BRIDGE_DIR))
spec.loader.exec_module(bridge)


class FakeTelegramClient:
    def __init__(self) -> None:
        self.messages = []

    def send_message(self, chat_id, text, reply_to_message_id=None):
        self.messages.append((chat_id, text, reply_to_message_id))


class FakeDownloadClient:
    def __init__(self, file_meta):
        self.file_meta = file_meta
        self.download_calls = 0

    def get_file(self, file_id):
        return dict(self.file_meta)

    def download_file_to_path(self, file_path, target_path, max_bytes, size_label="File"):
        self.download_calls += 1
        Path(target_path).write_bytes(b"x")


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
        "rate_limit_per_minute": 12,
        "executor_cmd": ["/bin/echo"],
        "voice_transcribe_cmd": [],
        "voice_transcribe_timeout_seconds": 10,
        "state_dir": "/tmp",
        "persistent_workers_enabled": False,
        "persistent_workers_max": 2,
        "persistent_workers_idle_timeout_seconds": 120,
        "persistent_workers_policy_files": [],
        "canonical_sessions_enabled": False,
    }
    base.update(overrides)
    return bridge.Config(**base)


class BridgeCoreTests(unittest.TestCase):
    def test_parse_executor_output_json_stream(self):
        sample_stream = (
            '{"type":"thread.started","thread_id":"thread-123"}\n'
            '{"type":"item.completed","item":{"type":"agent_message","text":"hello"}}\n'
        )
        thread_id, output = bridge.parse_executor_output(sample_stream)
        self.assertEqual(thread_id, "thread-123")
        self.assertEqual(output, "hello")

    def test_bounded_text_buffer_marks_truncation(self):
        buffer = bridge.BoundedTextBuffer(
            64,
            head_chars=12,
            truncation_marker="\n...[truncated]...\n",
        )
        buffer.append("HEAD-SECTION-")
        buffer.append("x" * 200)
        rendered = buffer.render()
        self.assertLessEqual(len(rendered), 64)
        self.assertIn("...[truncated]...", rendered)
        self.assertTrue(rendered.startswith("HEAD-SECTION"))

    def test_download_helper_rejects_oversize(self):
        client = FakeDownloadClient({"file_path": "files/example.jpg", "file_size": 9999})
        spec = bridge.TelegramFileDownloadSpec(
            file_id="abc",
            max_bytes=1024,
            size_label="Image",
            temp_prefix="telegram-bridge-photo-",
            default_suffix=".jpg",
            too_large_label="Image",
        )
        with self.assertRaises(ValueError):
            bridge.download_telegram_file_to_temp(client, spec)
        self.assertEqual(client.download_calls, 0)

    def test_state_repository_persists_thread_and_inflight_state(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state = bridge.State(
                chat_thread_path=str(Path(tmpdir) / "chat_threads.json"),
                worker_sessions_path=str(Path(tmpdir) / "worker_sessions.json"),
                in_flight_path=str(Path(tmpdir) / "in_flight_requests.json"),
                worker_sessions={
                    1: bridge.WorkerSession(
                        created_at=1.0,
                        last_used_at=1.0,
                        thread_id="",
                        policy_fingerprint="",
                    )
                },
            )
            repo = bridge.StateRepository(state)

            repo.set_thread_id(1, "thread-xyz")
            threads = json.loads(Path(state.chat_thread_path).read_text(encoding="utf-8"))
            sessions = json.loads(Path(state.worker_sessions_path).read_text(encoding="utf-8"))
            self.assertEqual(threads, {"1": "thread-xyz"})
            self.assertEqual(sessions["1"]["thread_id"], "thread-xyz")

            repo.mark_in_flight_request(1, 55)
            in_flight = json.loads(Path(state.in_flight_path).read_text(encoding="utf-8"))
            self.assertEqual(in_flight["1"]["message_id"], 55)

            repo.clear_in_flight_request(1)
            cleared = json.loads(Path(state.in_flight_path).read_text(encoding="utf-8"))
            self.assertEqual(cleared, {})

            repo.clear_thread_id(1)
            threads_after = json.loads(Path(state.chat_thread_path).read_text(encoding="utf-8"))
            self.assertEqual(threads_after, {})

    def test_ensure_chat_worker_session_rejects_when_all_workers_busy(self):
        state = bridge.State(
            chat_threads={2: "thread-busy"},
            worker_sessions={
                2: bridge.WorkerSession(
                    created_at=1.0,
                    last_used_at=10.0,
                    thread_id="thread-busy",
                    policy_fingerprint="fp",
                )
            },
        )
        state.busy_chats.add(2)
        client = FakeTelegramClient()
        config = make_config(
            persistent_workers_enabled=True,
            persistent_workers_max=1,
            persistent_workers_idle_timeout_seconds=3600,
        )

        allowed = bridge.ensure_chat_worker_session(state, config, client, chat_id=1, message_id=99)
        self.assertFalse(allowed)
        self.assertTrue(client.messages)
        self.assertIn("workers are currently in use", client.messages[-1][1])

    def test_handle_update_routes_status_command(self):
        state = bridge.State()
        client = FakeTelegramClient()
        config = make_config()
        update = {
            "update_id": 1,
            "message": {
                "message_id": 10,
                "chat": {"id": 1},
                "text": "/status",
            },
        }

        bridge.handle_update(state, config, client, update)
        self.assertTrue(client.messages)
        self.assertIn("Bridge status: online", client.messages[-1][1])

    def test_build_canonical_sessions_from_legacy(self):
        worker = bridge.WorkerSession(
            created_at=1.0,
            last_used_at=2.0,
            thread_id="thread-2",
            policy_fingerprint="fp",
        )
        sessions = bridge.build_canonical_sessions_from_legacy(
            chat_threads={1: "thread-1", 2: "thread-2"},
            worker_sessions={2: worker},
            in_flight_requests={3: {"started_at": 9.0, "message_id": 88}},
        )
        self.assertIn(1, sessions)
        self.assertIn(2, sessions)
        self.assertIn(3, sessions)
        self.assertEqual(sessions[1].thread_id, "thread-1")
        self.assertEqual(sessions[2].worker_policy_fingerprint, "fp")
        self.assertEqual(sessions[3].in_flight_message_id, 88)

    def test_state_repository_syncs_canonical_when_enabled(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state = bridge.State(
                chat_thread_path=str(Path(tmpdir) / "chat_threads.json"),
                worker_sessions_path=str(Path(tmpdir) / "worker_sessions.json"),
                in_flight_path=str(Path(tmpdir) / "in_flight_requests.json"),
                chat_sessions_path=str(Path(tmpdir) / "chat_sessions.json"),
                canonical_sessions_enabled=True,
            )
            repo = bridge.StateRepository(state)
            repo.set_thread_id(7, "thread-7")
            repo.mark_in_flight_request(7, 700)

            sessions = bridge.load_canonical_sessions(state.chat_sessions_path)
            self.assertIn(7, sessions)
            self.assertEqual(sessions[7].thread_id, "thread-7")
            self.assertEqual(sessions[7].in_flight_message_id, 700)


if __name__ == "__main__":
    unittest.main()
