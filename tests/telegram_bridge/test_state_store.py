import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
BRIDGE_DIR = ROOT / "src" / "telegram_bridge"
if str(BRIDGE_DIR) not in sys.path:
    sys.path.insert(0, str(BRIDGE_DIR))

import state_store
import canonical_state_store
import request_runtime_state_store


class StateStoreUnitTests(unittest.TestCase):
    def setUp(self) -> None:
        request_runtime_state_store._IN_FLIGHT_WRITE_ACTIVE.clear()
        request_runtime_state_store._IN_FLIGHT_WRITE_CONTENDED.clear()
        request_runtime_state_store._IN_FLIGHT_WRITE_PENDING.clear()
        request_runtime_state_store._IN_FLIGHT_WRITE_LAST_PERSISTED.clear()
        canonical_state_store._CANONICAL_SQLITE_SCHEMA_CACHE.clear()

    def test_persist_in_flight_requests_skips_per_write_fsync(self):
        state = request_runtime_state_store.State(
            in_flight_path="/tmp/in_flight_requests.json",
            in_flight_requests={"tg:1": {"started_at": 1.0, "message_id": 2}},
        )

        with mock.patch.object(
            request_runtime_state_store,
            "_persist_in_flight_snapshot",
        ) as persist_in_flight_snapshot:
            request_runtime_state_store.persist_in_flight_requests(state)

        persist_in_flight_snapshot.assert_called_once_with(
            "/tmp/in_flight_requests.json",
            {"tg:1": {"started_at": 1.0, "message_id": 2}},
        )

    def test_persist_in_flight_snapshot_skips_per_write_fsync(self):
        with mock.patch.object(
            request_runtime_state_store,
            "persist_json_state_file",
        ) as persist_json_state_file:
            request_runtime_state_store._persist_in_flight_snapshot(
                "/tmp/in_flight_requests.json",
                {"tg:1": {"started_at": 1.0, "message_id": 2}},
            )

        persist_json_state_file.assert_called_once_with(
            "/tmp/in_flight_requests.json",
            {"tg:1": {"started_at": 1.0, "message_id": 2}},
            fsync_file=False,
            pretty=False,
            delete_when_empty=True,
        )

    def test_persist_in_flight_snapshot_skips_idle_wait_when_uncontended(self):
        with mock.patch.object(
            request_runtime_state_store,
            "persist_json_state_file",
        ) as persist_json_state_file, mock.patch.object(
            request_runtime_state_store._IN_FLIGHT_WRITE_CONDITION,
            "wait",
            side_effect=AssertionError("wait should not be used without contention"),
        ):
            request_runtime_state_store._persist_in_flight_snapshot(
                "/tmp/in_flight_requests.json",
                {"tg:1": {"started_at": 1.0, "message_id": 2}},
            )

        persist_json_state_file.assert_called_once_with(
            "/tmp/in_flight_requests.json",
            {"tg:1": {"started_at": 1.0, "message_id": 2}},
            fsync_file=False,
            pretty=False,
            delete_when_empty=True,
        )

    def test_persist_in_flight_snapshot_skips_rewriting_identical_snapshot(self):
        with mock.patch.object(
            request_runtime_state_store,
            "persist_json_state_file",
        ) as persist_json_state_file:
            payload = {"tg:1": {"started_at": 1.0, "message_id": 2}}
            request_runtime_state_store._persist_in_flight_snapshot(
                "/tmp/in_flight_requests.json",
                payload,
            )
            request_runtime_state_store._persist_in_flight_snapshot(
                "/tmp/in_flight_requests.json",
                {"tg:1": {"started_at": 1.0, "message_id": 2}},
            )

        persist_json_state_file.assert_called_once_with(
            "/tmp/in_flight_requests.json",
            payload,
            fsync_file=False,
            pretty=False,
            delete_when_empty=True,
        )

    def test_persist_in_flight_snapshot_skips_idle_wait_after_deduped_contention(self):
        payload = {"tg:1": {"started_at": 1.0, "message_id": 2}}
        release_write = request_runtime_state_store.threading.Event()
        write_started = request_runtime_state_store.threading.Event()

        def blocking_persist(path_value, serialized, *, fsync_file, pretty, delete_when_empty):
            self.assertEqual(path_value, "/tmp/in_flight_requests.json")
            self.assertEqual(serialized, payload)
            self.assertFalse(fsync_file)
            self.assertFalse(pretty)
            self.assertTrue(delete_when_empty)
            write_started.set()
            release_write.wait(timeout=5.0)

        worker = request_runtime_state_store.threading.Thread(
            target=request_runtime_state_store._persist_in_flight_snapshot,
            args=("/tmp/in_flight_requests.json", payload),
        )

        with mock.patch.object(
            request_runtime_state_store,
            "persist_json_state_file",
            side_effect=blocking_persist,
        ), mock.patch.object(
            request_runtime_state_store._IN_FLIGHT_WRITE_CONDITION,
            "wait",
            side_effect=AssertionError("idle wait should be skipped when contention adds no distinct payload"),
        ):
            worker.start()
            self.assertTrue(write_started.wait(timeout=5.0))
            request_runtime_state_store._persist_in_flight_snapshot(
                "/tmp/in_flight_requests.json",
                {"tg:1": {"started_at": 1.0, "message_id": 2}},
            )
            release_write.set()
            worker.join(timeout=5.0)

        self.assertFalse(worker.is_alive())

    def test_canonical_sqlite_connection_uses_wal_and_normal_sync(self):
        real_connect = state_store.sqlite3.connect

        with tempfile.TemporaryDirectory() as tmpdir:
            sqlite_path = str(Path(tmpdir) / "chat_sessions.sqlite3")
            with mock.patch.object(
                state_store.sqlite3,
                "connect",
                wraps=real_connect,
            ) as connect_mock:
                state_store.persist_canonical_sessions_sqlite(
                    sqlite_path,
                    {"tg:1": state_store.CanonicalSession(thread_id="thread-1")},
                )

            self.assertGreaterEqual(connect_mock.call_count, 1)
            with real_connect(sqlite_path) as conn:
                journal_mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
                synchronous = conn.execute("PRAGMA synchronous").fetchone()[0]

            self.assertEqual(str(journal_mode).lower(), "wal")
            self.assertEqual(int(synchronous), 2)

    def test_ensure_canonical_sqlite_skips_reinitializing_unchanged_db(self):
        real_connect = state_store.sqlite3.connect

        with tempfile.TemporaryDirectory() as tmpdir:
            sqlite_path = str(Path(tmpdir) / "chat_sessions.sqlite3")
            with mock.patch.object(
                state_store.sqlite3,
                "connect",
                wraps=real_connect,
            ) as connect_mock:
                state_store.ensure_canonical_sessions_sqlite(sqlite_path)
                state_store.ensure_canonical_sessions_sqlite(sqlite_path)

            self.assertEqual(connect_mock.call_count, 1)

    def test_ensure_canonical_sqlite_reinitializes_after_db_replacement(self):
        real_connect = state_store.sqlite3.connect

        with tempfile.TemporaryDirectory() as tmpdir:
            sqlite_path = Path(tmpdir) / "chat_sessions.sqlite3"
            with mock.patch.object(
                state_store.sqlite3,
                "connect",
                wraps=real_connect,
            ) as connect_mock:
                state_store.ensure_canonical_sessions_sqlite(str(sqlite_path))
                sqlite_path.unlink()
                state_store.ensure_canonical_sessions_sqlite(str(sqlite_path))

            self.assertEqual(connect_mock.call_count, 2)

    def test_canonical_sqlite_skips_schema_reinit_after_normal_write_on_same_file(self):
        real_connect = state_store.sqlite3.connect

        with tempfile.TemporaryDirectory() as tmpdir:
            sqlite_path = str(Path(tmpdir) / "chat_sessions.sqlite3")
            with mock.patch.object(
                state_store.sqlite3,
                "connect",
                wraps=real_connect,
            ) as connect_mock:
                state_store.persist_canonical_session_sqlite(
                    sqlite_path,
                    "tg:1",
                    state_store.CanonicalSession(thread_id="thread-1"),
                )
                state_store.persist_canonical_session_sqlite(
                    sqlite_path,
                    "tg:1",
                    state_store.CanonicalSession(thread_id="thread-2"),
                )

            self.assertEqual(connect_mock.call_count, 3)

    def test_canonical_sqlite_expands_tilde_for_reads_and_writes(self):
        home_dir = Path.home()
        with tempfile.TemporaryDirectory(dir=home_dir) as tmpdir:
            sqlite_path = Path(tmpdir) / "chat_sessions.sqlite3"
            tilde_path = f"~/{sqlite_path.relative_to(home_dir)}"

            state_store.persist_canonical_session_sqlite(
                tilde_path,
                "tg:1",
                state_store.CanonicalSession(thread_id="thread-tilde"),
            )

            self.assertTrue(sqlite_path.exists())
            loaded = state_store.load_canonical_sessions_sqlite(tilde_path)
            self.assertEqual(loaded["tg:1"].thread_id, "thread-tilde")

    def test_set_thread_id_updates_legacy_worker_session_and_persists_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state = state_store.State(
                chat_thread_path=str(Path(tmpdir) / "chat_threads.json"),
                worker_sessions_path=str(Path(tmpdir) / "worker_sessions.json"),
                in_flight_path=str(Path(tmpdir) / "in_flight_requests.json"),
                worker_sessions={
                    "tg:1": state_store.WorkerSession(
                        created_at=10.0,
                        last_used_at=11.0,
                        thread_id="",
                        policy_fingerprint="fp",
                    )
                },
            )

            with mock.patch.object(state_store.time, "time", return_value=55.0):
                state_store.set_thread_id(state, 1, "  thread-1  ")

            self.assertEqual(state.chat_threads["tg:1"], "thread-1")
            self.assertEqual(state.worker_sessions["tg:1"].thread_id, "thread-1")
            self.assertEqual(state.worker_sessions["tg:1"].last_used_at, 55.0)

            threads_payload = json.loads(Path(state.chat_thread_path).read_text(encoding="utf-8"))
            workers_payload = json.loads(
                Path(state.worker_sessions_path).read_text(encoding="utf-8")
            )
            self.assertEqual(threads_payload, {"tg:1": "thread-1"})
            self.assertEqual(workers_payload["tg:1"]["thread_id"], "thread-1")
            self.assertEqual(workers_payload["tg:1"]["last_used_at"], 55.0)

    def test_sync_canonical_session_removes_empty_stale_session(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state = state_store.State(
                chat_sessions_path=str(Path(tmpdir) / "chat_sessions.json"),
                canonical_sessions_enabled=True,
                chat_sessions={
                    "tg:7": state_store.CanonicalSession(thread_id="stale-thread"),
                },
            )
            state_store.persist_canonical_sessions(state)

            state_store.sync_canonical_session(state, 7)

            self.assertEqual(state.chat_sessions, {})
            payload = json.loads(Path(state.chat_sessions_path).read_text(encoding="utf-8"))
            self.assertEqual(payload, {})

    def test_canonical_mark_and_clear_inflight_does_not_persist_legacy_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state = state_store.State(
                chat_thread_path=str(Path(tmpdir) / "chat_threads.json"),
                worker_sessions_path=str(Path(tmpdir) / "worker_sessions.json"),
                in_flight_path=str(Path(tmpdir) / "in_flight_requests.json"),
                chat_sessions_path=str(Path(tmpdir) / "chat_sessions.json"),
                canonical_sessions_enabled=True,
            )

            with mock.patch.object(state_store.time, "time", return_value=123.0):
                state_store.mark_in_flight_request(state, 9, 90)

            canonical_payload = json.loads(
                Path(state.chat_sessions_path).read_text(encoding="utf-8")
            )
            self.assertEqual(canonical_payload["tg:9"]["in_flight_message_id"], 90)
            self.assertFalse(Path(state.in_flight_path).exists())

            state_store.clear_in_flight_request(state, 9)

            canonical_cleared = json.loads(Path(state.chat_sessions_path).read_text(encoding="utf-8"))
            self.assertEqual(canonical_cleared, {})
            self.assertFalse(Path(state.in_flight_path).exists())

    def test_pop_interrupted_requests_canonical_preserves_thread_without_legacy_mirror(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state = state_store.State(
                chat_thread_path=str(Path(tmpdir) / "chat_threads.json"),
                worker_sessions_path=str(Path(tmpdir) / "worker_sessions.json"),
                in_flight_path=str(Path(tmpdir) / "in_flight_requests.json"),
                chat_sessions_path=str(Path(tmpdir) / "chat_sessions.json"),
                canonical_sessions_enabled=True,
                chat_sessions={
                    "tg:4": state_store.CanonicalSession(
                        thread_id="thread-4",
                        in_flight_started_at=44.0,
                        in_flight_message_id=400,
                    )
                },
            )
            state_store.persist_canonical_sessions(state)

            interrupted = state_store.pop_interrupted_requests(state)

            self.assertEqual(
                interrupted,
                {"tg:4": {"started_at": 44.0, "message_id": 400}},
            )
            self.assertEqual(state.chat_sessions["tg:4"].thread_id, "thread-4")
            self.assertIsNone(state.chat_sessions["tg:4"].in_flight_started_at)
            self.assertEqual(state.chat_threads, {})
            self.assertEqual(state.in_flight_requests, {})

            canonical_payload = json.loads(
                Path(state.chat_sessions_path).read_text(encoding="utf-8")
            )
            self.assertEqual(canonical_payload["tg:4"]["thread_id"], "thread-4")
            self.assertIsNone(canonical_payload["tg:4"]["in_flight_started_at"])
            self.assertFalse(Path(state.in_flight_path).exists())

    def test_load_canonical_sessions_sanitizes_values_and_preserves_custom_scope_keys(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            payload = {
                "1": {
                    "thread_id": "  thread-1  ",
                    "worker_created_at": 10,
                    "worker_last_used_at": "bad",
                    "worker_policy_fingerprint": "  fp  ",
                    "in_flight_started_at": 12,
                    "in_flight_message_id": "bad",
                },
                "tg:not-a-chat": {"thread_id": "ignored"},
                "tg:2": ["not-a-dict"],
            }
            path = Path(tmpdir) / "chat_sessions.json"
            path.write_text(json.dumps(payload), encoding="utf-8")

            sessions = state_store.load_canonical_sessions(str(path))

            self.assertEqual(set(sessions), {"tg:1", "tg:not-a-chat"})

            session = sessions["tg:1"]
            self.assertEqual(session.thread_id, "thread-1")
            self.assertEqual(session.worker_created_at, 10.0)
            self.assertIsNone(session.worker_last_used_at)
            self.assertEqual(session.worker_policy_fingerprint, "fp")
            self.assertEqual(session.in_flight_started_at, 12.0)
            self.assertIsNone(session.in_flight_message_id)

            custom_scope = sessions["tg:not-a-chat"]
            self.assertEqual(custom_scope.thread_id, "ignored")
            self.assertIsNone(custom_scope.worker_created_at)

    def test_clear_thread_id_sqlite_updates_only_target_scope(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sqlite_path = str(Path(tmpdir) / "chat_sessions.sqlite3")
            state = state_store.State(
                canonical_sessions_enabled=True,
                canonical_sqlite_enabled=True,
                canonical_sqlite_path=sqlite_path,
                chat_sessions={
                    "tg:7": state_store.CanonicalSession(thread_id="stale-thread"),
                    "tg:8": state_store.CanonicalSession(thread_id="keep-thread"),
                },
            )
            state_store.persist_canonical_sessions(state)

            removed = state_store.clear_thread_id(state, 7)

            self.assertTrue(removed)
            persisted = state_store.load_canonical_sessions_sqlite(sqlite_path)
            self.assertEqual(set(persisted), {"tg:8"})
            self.assertEqual(persisted["tg:8"].thread_id, "keep-thread")

    def test_persist_canonical_sessions_sqlite_preserves_custom_scope_keys(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sqlite_path = str(Path(tmpdir) / "chat_sessions.sqlite3")
            state_store.persist_canonical_sessions_sqlite(
                sqlite_path,
                {
                    "tg:not-a-chat": state_store.CanonicalSession(thread_id="custom-thread"),
                },
            )

            persisted = state_store.load_canonical_sessions_sqlite(sqlite_path)
            self.assertEqual(set(persisted), {"tg:not-a-chat"})
            self.assertEqual(persisted["tg:not-a-chat"].thread_id, "custom-thread")


if __name__ == "__main__":
    unittest.main()
