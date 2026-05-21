import os
import sys
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
BRIDGE_DIR = ROOT / "src" / "telegram_bridge"
if str(BRIDGE_DIR) not in sys.path:
    sys.path.insert(0, str(BRIDGE_DIR))

import session_manager
from state_models import CanonicalSession, State, WorkerSession


class SessionManagerRestartUnitTests(unittest.TestCase):
    def test_build_restart_unit_name_prefers_explicit_restart_env(self):
        with mock.patch.dict(
            os.environ,
            {
                "TELEGRAM_RESTART_UNIT": "telegram-mavali-eth-bridge.service",
                "UNIT_NAME": "telegram-architect-bridge.service",
            },
            clear=False,
        ):
            self.assertEqual(
                session_manager.build_restart_unit_name(),
                "telegram-mavali-eth-bridge.service",
            )

    def test_build_restart_unit_name_falls_back_to_unit_name_env(self):
        with mock.patch.dict(
            os.environ,
            {"UNIT_NAME": "telegram-mavali-eth-bridge.service"},
            clear=False,
        ):
            os.environ.pop("TELEGRAM_RESTART_UNIT", None)
            self.assertEqual(
                session_manager.build_restart_unit_name(),
                "telegram-mavali-eth-bridge.service",
            )

    def test_reset_codex_session_state_for_restart_canonical_clears_threads_and_workers(self):
        state = State(
            canonical_sessions_enabled=True,
            chat_sessions={
                "tg:1": CanonicalSession(
                    thread_id="thread-1",
                    worker_created_at=1.0,
                    worker_last_used_at=2.0,
                    worker_policy_fingerprint="fp",
                ),
                "tg:2": CanonicalSession(thread_id="thread-2"),
            },
        )

        with mock.patch.object(session_manager, "persist_canonical_sessions") as persist:
            result = session_manager.reset_codex_session_state_for_restart(state)

        self.assertEqual(result, {"threads": 2, "workers": 1})
        self.assertEqual(state.chat_sessions, {})
        persist.assert_called_once_with(state)

    def test_reset_codex_session_state_for_restart_legacy_clears_threads_and_workers(self):
        state = State(
            chat_threads={"tg:1": "thread-1", "tg:2": "thread-2"},
            worker_sessions={
                "tg:1": WorkerSession(
                    created_at=1.0,
                    last_used_at=2.0,
                    thread_id="thread-1",
                    policy_fingerprint="fp",
                )
            },
        )

        with (
            mock.patch.object(session_manager, "persist_chat_threads") as persist_threads,
            mock.patch.object(session_manager, "persist_worker_sessions") as persist_workers,
        ):
            result = session_manager.reset_codex_session_state_for_restart(state)

        self.assertEqual(result, {"threads": 2, "workers": 1})
        self.assertEqual(state.chat_threads, {})
        self.assertEqual(state.worker_sessions, {})
        persist_threads.assert_called_once_with(state)
        persist_workers.assert_called_once_with(state)

    def test_run_restart_script_resets_codex_state_before_invoking_helper(self):
        state = State(canonical_sessions_enabled=True)
        client = mock.Mock()
        completed = mock.Mock(returncode=0, stderr="")

        with (
            mock.patch.object(
                session_manager,
                "reset_codex_session_state_for_restart",
                return_value={"threads": 3, "workers": 2},
            ) as reset_state,
            mock.patch.object(session_manager, "emit_event") as emit_event,
            mock.patch.object(session_manager.subprocess, "run", return_value=completed) as run,
        ):
            session_manager.run_restart_script(
                state,
                client,
                chat_id=7,
                message_thread_id=11,
                reply_to_message_id=13,
            )

        reset_state.assert_called_once_with(state)
        run.assert_called_once()
        self.assertEqual(emit_event.call_args_list[0].args[0], "bridge.restart_codex_state_reset")
