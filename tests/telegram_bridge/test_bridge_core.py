import importlib.util
import json
import logging
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock


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
import executor as bridge_executor
import handlers as bridge_handlers
import session_manager as bridge_session_manager
import structured_logging as bridge_structured_logging


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
        "canonical_legacy_mirror_enabled": False,
        "canonical_sqlite_enabled": False,
        "canonical_sqlite_path": "/tmp/chat_sessions.sqlite3",
        "canonical_json_mirror_enabled": False,
        "memory_sqlite_path": "/tmp/memory.sqlite3",
        "memory_max_messages_per_key": 4000,
        "memory_max_summaries_per_key": 80,
        "memory_prune_interval_seconds": 300,
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

    def test_to_telegram_chunks_uses_real_newline_prefix(self):
        chunks = bridge.to_telegram_chunks("x" * 5000)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(chunks[0].startswith("[1/2]\n"))
        self.assertNotIn("\\n", chunks[0][:10])

    def test_parse_stream_json_line_rejects_invalid_payloads(self):
        self.assertIsNone(bridge_executor.parse_stream_json_line("not-json"))
        self.assertIsNone(bridge_executor.parse_stream_json_line("[]"))
        self.assertIsNone(bridge_executor.parse_stream_json_line(""))

    def test_should_reset_thread_after_resume_failure_markers(self):
        self.assertTrue(
            bridge_executor.should_reset_thread_after_resume_failure(
                "Thread not found for resume",
                "",
            )
        )
        self.assertFalse(
            bridge_executor.should_reset_thread_after_resume_failure(
                "permission denied",
                "generic error",
            )
        )

    def test_normalize_command_and_trim_output_helpers(self):
        self.assertEqual(bridge_handlers.normalize_command("/h@architect_bot now"), "/h")
        self.assertIsNone(bridge_handlers.normalize_command("hello"))
        trimmed = bridge_handlers.trim_output("x" * 40, 20)
        self.assertTrue(trimmed.endswith("[output truncated]"))
        self.assertLessEqual(len(trimmed), 20)

    def test_json_log_formatter_includes_event_and_fields(self):
        record = logging.LogRecord(
            "telegram_bridge",
            logging.INFO,
            __file__,
            1,
            "bridge.request_succeeded",
            args=(),
            exc_info=None,
        )
        record.event = "bridge.request_succeeded"
        record.fields = {"chat_id": 1, "message_id": 2}
        payload = json.loads(bridge_structured_logging.JsonLogFormatter().format(record))
        self.assertEqual(payload["event"], "bridge.request_succeeded")
        self.assertEqual(payload["chat_id"], 1)
        self.assertEqual(payload["message_id"], 2)

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

    def test_handle_update_routes_help_alias_with_bot_suffix(self):
        state = bridge.State()
        client = FakeTelegramClient()
        config = make_config()
        update = {
            "update_id": 1,
            "message": {
                "message_id": 20,
                "chat": {"id": 1},
                "text": "/h@architect_bot",
            },
        }

        bridge.handle_update(state, config, client, update)
        self.assertTrue(client.messages)
        self.assertIn("Available commands:", client.messages[-1][1])
        self.assertIn("/memory mode", client.messages[-1][1])
        self.assertIn("/ask <prompt>", client.messages[-1][1])

    def test_handle_update_routes_memory_status_command(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state = bridge.State(
                memory_engine=bridge.MemoryEngine(str(Path(tmpdir) / "memory.sqlite3")),
            )
            client = FakeTelegramClient()
            config = make_config()
            update = {
                "update_id": 1,
                "message": {
                    "message_id": 21,
                    "chat": {"id": 1},
                    "text": "/memory status",
                },
            }

            bridge.handle_update(state, config, client, update)
            self.assertTrue(client.messages)
            self.assertIn("Memory status:", client.messages[-1][1])

    def test_handle_update_rejects_too_long_input_before_worker_dispatch(self):
        state = bridge.State()
        client = FakeTelegramClient()
        config = make_config(max_input_chars=10)
        update = {
            "update_id": 2,
            "message": {
                "message_id": 30,
                "chat": {"id": 1},
                "text": "x" * 11,
            },
        }

        bridge.handle_update(state, config, client, update)
        self.assertEqual(len(client.messages), 1)
        self.assertIn("Input too long (11 chars). Max is 10.", client.messages[0][1])

    def test_handle_update_denies_non_allowlisted_chat(self):
        state = bridge.State()
        client = FakeTelegramClient()
        config = make_config(allowed_chat_ids={1})
        update = {
            "update_id": 3,
            "message": {
                "message_id": 31,
                "chat": {"id": 2},
                "text": "hello",
            },
        }

        bridge.handle_update(state, config, client, update)
        self.assertEqual(len(client.messages), 1)
        self.assertEqual(client.messages[0][1], config.denied_message)

    def test_handle_update_rejects_when_chat_busy(self):
        state = bridge.State()
        state.busy_chats.add(1)
        client = FakeTelegramClient()
        config = make_config()
        update = {
            "update_id": 4,
            "message": {
                "message_id": 32,
                "chat": {"id": 1},
                "text": "run now",
            },
        }

        bridge.handle_update(state, config, client, update)
        self.assertEqual(len(client.messages), 1)
        self.assertEqual(client.messages[0][1], config.busy_message)

    def test_request_safe_restart_status_transitions(self):
        state = bridge.State()

        status, busy = bridge_session_manager.request_safe_restart(state, chat_id=1, reply_to_message_id=None)
        self.assertEqual(status, "run_now")
        self.assertEqual(busy, 0)

        status, busy = bridge_session_manager.request_safe_restart(state, chat_id=1, reply_to_message_id=None)
        self.assertEqual(status, "in_progress")
        self.assertEqual(busy, 0)

        bridge_session_manager.finish_restart_attempt(state)
        with state.lock:
            state.busy_chats.add(5)

        status, busy = bridge_session_manager.request_safe_restart(state, chat_id=1, reply_to_message_id=None)
        self.assertEqual(status, "queued")
        self.assertEqual(busy, 1)

        status, busy = bridge_session_manager.request_safe_restart(state, chat_id=1, reply_to_message_id=None)
        self.assertEqual(status, "already_queued")
        self.assertEqual(busy, 1)

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

    def test_state_repository_syncs_canonical_to_sqlite_when_enabled(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sqlite_path = str(Path(tmpdir) / "chat_sessions.sqlite3")
            json_path = str(Path(tmpdir) / "chat_sessions.json")
            state = bridge.State(
                chat_thread_path=str(Path(tmpdir) / "chat_threads.json"),
                worker_sessions_path=str(Path(tmpdir) / "worker_sessions.json"),
                in_flight_path=str(Path(tmpdir) / "in_flight_requests.json"),
                chat_sessions_path=json_path,
                canonical_sessions_enabled=True,
                canonical_sqlite_enabled=True,
                canonical_sqlite_path=sqlite_path,
                canonical_json_mirror_enabled=False,
            )
            repo = bridge.StateRepository(state)
            repo.set_thread_id(12, "thread-12")
            repo.mark_in_flight_request(12, 1200)

            sessions = bridge.load_canonical_sessions_sqlite(sqlite_path)
            self.assertIn(12, sessions)
            self.assertEqual(sessions[12].thread_id, "thread-12")
            self.assertEqual(sessions[12].in_flight_message_id, 1200)
            self.assertFalse(Path(json_path).exists())

    def test_canonical_sqlite_json_mirror_writes_json_when_enabled(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sqlite_path = str(Path(tmpdir) / "chat_sessions.sqlite3")
            json_path = str(Path(tmpdir) / "chat_sessions.json")
            state = bridge.State(
                chat_thread_path=str(Path(tmpdir) / "chat_threads.json"),
                worker_sessions_path=str(Path(tmpdir) / "worker_sessions.json"),
                in_flight_path=str(Path(tmpdir) / "in_flight_requests.json"),
                chat_sessions_path=json_path,
                canonical_sessions_enabled=True,
                canonical_sqlite_enabled=True,
                canonical_sqlite_path=sqlite_path,
                canonical_json_mirror_enabled=True,
            )
            repo = bridge.StateRepository(state)
            repo.set_thread_id(13, "thread-13")

            sqlite_sessions = bridge.load_canonical_sessions_sqlite(sqlite_path)
            json_sessions = bridge.load_canonical_sessions(json_path)
            self.assertEqual(sqlite_sessions[13].thread_id, "thread-13")
            self.assertEqual(json_sessions[13].thread_id, "thread-13")

    def test_load_or_import_canonical_sessions_sqlite_imports_only_when_empty(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sqlite_path = str(Path(tmpdir) / "chat_sessions.sqlite3")
            initial_sessions = {
                1: bridge.CanonicalSession(thread_id="thread-initial"),
            }
            loaded, imported = bridge.load_or_import_canonical_sessions_sqlite(
                sqlite_path,
                import_sessions=initial_sessions,
            )
            self.assertTrue(imported)
            self.assertEqual(loaded[1].thread_id, "thread-initial")

            replacement_sessions = {
                1: bridge.CanonicalSession(thread_id="thread-replacement"),
                2: bridge.CanonicalSession(thread_id="thread-two"),
            }
            loaded_again, imported_again = bridge.load_or_import_canonical_sessions_sqlite(
                sqlite_path,
                import_sessions=replacement_sessions,
            )
            self.assertFalse(imported_again)
            self.assertEqual(loaded_again[1].thread_id, "thread-initial")
            self.assertNotIn(2, loaded_again)

    def test_build_legacy_from_canonical(self):
        canonical = {
            9: bridge.CanonicalSession(
                thread_id="thread-9",
                worker_created_at=1.0,
                worker_last_used_at=2.0,
                worker_policy_fingerprint="fp",
                in_flight_started_at=3.0,
                in_flight_message_id=90,
            )
        }
        chat_threads, worker_sessions, in_flight = bridge.build_legacy_from_canonical(canonical)
        self.assertEqual(chat_threads[9], "thread-9")
        self.assertEqual(worker_sessions[9].policy_fingerprint, "fp")
        self.assertEqual(in_flight[9]["message_id"], 90)

    def test_canonical_first_set_thread_and_clear_worker_mirrors_legacy(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state = bridge.State(
                chat_thread_path=str(Path(tmpdir) / "chat_threads.json"),
                worker_sessions_path=str(Path(tmpdir) / "worker_sessions.json"),
                in_flight_path=str(Path(tmpdir) / "in_flight_requests.json"),
                chat_sessions_path=str(Path(tmpdir) / "chat_sessions.json"),
                canonical_sessions_enabled=True,
                canonical_legacy_mirror_enabled=True,
                chat_sessions={
                    5: bridge.CanonicalSession(
                        thread_id="old-thread",
                        worker_created_at=1.0,
                        worker_last_used_at=1.0,
                        worker_policy_fingerprint="old",
                    )
                },
            )
            bridge.persist_canonical_sessions(state)
            bridge.mirror_legacy_from_canonical(state, persist=True)

            repo = bridge.StateRepository(state)
            repo.set_thread_id(5, "new-thread")
            repo.clear_worker_session(5)

            sessions = bridge.load_canonical_sessions(state.chat_sessions_path)
            self.assertEqual(sessions[5].thread_id, "new-thread")
            self.assertIsNone(sessions[5].worker_created_at)

            threads = json.loads(Path(state.chat_thread_path).read_text(encoding="utf-8"))
            workers = json.loads(Path(state.worker_sessions_path).read_text(encoding="utf-8"))
            self.assertEqual(threads["5"], "new-thread")
            self.assertEqual(workers, {})

    def test_canonical_first_without_legacy_mirror_skips_legacy_persist(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state = bridge.State(
                chat_thread_path=str(Path(tmpdir) / "chat_threads.json"),
                worker_sessions_path=str(Path(tmpdir) / "worker_sessions.json"),
                in_flight_path=str(Path(tmpdir) / "in_flight_requests.json"),
                chat_sessions_path=str(Path(tmpdir) / "chat_sessions.json"),
                canonical_sessions_enabled=True,
                canonical_legacy_mirror_enabled=False,
            )
            repo = bridge.StateRepository(state)
            repo.set_thread_id(11, "thread-11")

            sessions = bridge.load_canonical_sessions(state.chat_sessions_path)
            self.assertEqual(sessions[11].thread_id, "thread-11")
            self.assertFalse(Path(state.chat_thread_path).exists())

    def test_ensure_chat_worker_session_canonical_rejects_when_all_workers_busy(self):
        state = bridge.State(
            canonical_sessions_enabled=True,
            chat_sessions={
                2: bridge.CanonicalSession(
                    thread_id="thread-busy",
                    worker_created_at=1.0,
                    worker_last_used_at=10.0,
                    worker_policy_fingerprint="fp",
                )
            },
        )
        state.busy_chats.add(2)
        client = FakeTelegramClient()
        config = make_config(
            persistent_workers_enabled=True,
            persistent_workers_max=1,
            canonical_sessions_enabled=True,
        )

        allowed = bridge.ensure_chat_worker_session(state, config, client, chat_id=1, message_id=99)
        self.assertFalse(allowed)
        self.assertTrue(client.messages)
        self.assertIn("workers are currently in use", client.messages[-1][1])

    def test_ensure_chat_worker_session_canonical_sends_policy_refresh_notice(self):
        state = bridge.State(
            canonical_sessions_enabled=True,
            chat_sessions={
                1: bridge.CanonicalSession(
                    thread_id="thread-old",
                    worker_created_at=1.0,
                    worker_last_used_at=2.0,
                    worker_policy_fingerprint="stale-fingerprint",
                )
            },
        )
        client = FakeTelegramClient()
        config = make_config(
            persistent_workers_enabled=True,
            persistent_workers_max=2,
            canonical_sessions_enabled=True,
        )

        allowed = bridge.ensure_chat_worker_session(state, config, client, chat_id=1, message_id=88)
        self.assertTrue(allowed)
        self.assertTrue(client.messages)
        self.assertIn("Policy/context files changed", client.messages[-1][1])
        self.assertIn(1, state.chat_sessions)
        self.assertEqual(state.chat_sessions[1].thread_id, "")

    def test_state_repository_concurrent_inflight_persistence_is_safe(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state = bridge.State(
                chat_thread_path=str(Path(tmpdir) / "chat_threads.json"),
                worker_sessions_path=str(Path(tmpdir) / "worker_sessions.json"),
                in_flight_path=str(Path(tmpdir) / "in_flight_requests.json"),
            )
            repo = bridge.StateRepository(state)
            errors = []
            errors_lock = threading.Lock()

            def worker(seed: int) -> None:
                for i in range(120):
                    chat_id = ((seed * 7) + i) % 12 + 1
                    try:
                        repo.mark_in_flight_request(chat_id, i)
                        repo.clear_in_flight_request(chat_id)
                    except Exception as exc:  # pragma: no cover - regression guard
                        with errors_lock:
                            errors.append(repr(exc))
                        return

            threads = [threading.Thread(target=worker, args=(idx,)) for idx in range(16)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

            self.assertEqual(errors, [])

    def test_finalize_chat_work_clears_busy_when_inflight_clear_fails(self):
        state = bridge.State()
        state.busy_chats.add(1)
        client = FakeTelegramClient()

        class FailingStateRepo:
            def __init__(self, _state):
                pass

            def clear_in_flight_request(self, _chat_id):
                raise RuntimeError("boom")

        with mock.patch.object(bridge_session_manager, "StateRepository", FailingStateRepo):
            bridge_session_manager.finalize_chat_work(state, client, chat_id=1)
        self.assertNotIn(1, state.busy_chats)


if __name__ == "__main__":
    unittest.main()
