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


class StateStoreUnitTests(unittest.TestCase):
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

    def test_canonical_mark_and_clear_inflight_mirrors_legacy_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state = state_store.State(
                chat_thread_path=str(Path(tmpdir) / "chat_threads.json"),
                worker_sessions_path=str(Path(tmpdir) / "worker_sessions.json"),
                in_flight_path=str(Path(tmpdir) / "in_flight_requests.json"),
                chat_sessions_path=str(Path(tmpdir) / "chat_sessions.json"),
                canonical_sessions_enabled=True,
                canonical_legacy_mirror_enabled=True,
            )

            with mock.patch.object(state_store.time, "time", return_value=123.0):
                state_store.mark_in_flight_request(state, 9, 90)

            canonical_payload = json.loads(
                Path(state.chat_sessions_path).read_text(encoding="utf-8")
            )
            legacy_inflight_payload = json.loads(
                Path(state.in_flight_path).read_text(encoding="utf-8")
            )
            self.assertEqual(canonical_payload["tg:9"]["in_flight_message_id"], 90)
            self.assertEqual(legacy_inflight_payload["tg:9"]["message_id"], 90)

            state_store.clear_in_flight_request(state, 9)

            canonical_cleared = json.loads(Path(state.chat_sessions_path).read_text(encoding="utf-8"))
            legacy_inflight_cleared = json.loads(
                Path(state.in_flight_path).read_text(encoding="utf-8")
            )
            self.assertEqual(canonical_cleared, {})
            self.assertEqual(legacy_inflight_cleared, {})

    def test_pop_interrupted_requests_canonical_preserves_thread_and_clears_mirror(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state = state_store.State(
                chat_thread_path=str(Path(tmpdir) / "chat_threads.json"),
                worker_sessions_path=str(Path(tmpdir) / "worker_sessions.json"),
                in_flight_path=str(Path(tmpdir) / "in_flight_requests.json"),
                chat_sessions_path=str(Path(tmpdir) / "chat_sessions.json"),
                canonical_sessions_enabled=True,
                canonical_legacy_mirror_enabled=True,
                chat_sessions={
                    "tg:4": state_store.CanonicalSession(
                        thread_id="thread-4",
                        in_flight_started_at=44.0,
                        in_flight_message_id=400,
                    )
                },
            )
            state_store.persist_canonical_sessions(state)
            state_store.mirror_legacy_from_canonical(state, persist=True)

            interrupted = state_store.pop_interrupted_requests(state)

            self.assertEqual(
                interrupted,
                {"tg:4": {"started_at": 44.0, "message_id": 400}},
            )
            self.assertEqual(state.chat_sessions["tg:4"].thread_id, "thread-4")
            self.assertIsNone(state.chat_sessions["tg:4"].in_flight_started_at)
            self.assertEqual(state.chat_threads, {"tg:4": "thread-4"})
            self.assertEqual(state.in_flight_requests, {})

            canonical_payload = json.loads(
                Path(state.chat_sessions_path).read_text(encoding="utf-8")
            )
            legacy_inflight_payload = json.loads(
                Path(state.in_flight_path).read_text(encoding="utf-8")
            )
            self.assertEqual(canonical_payload["tg:4"]["thread_id"], "thread-4")
            self.assertIsNone(canonical_payload["tg:4"]["in_flight_started_at"])
            self.assertEqual(legacy_inflight_payload, {})

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
