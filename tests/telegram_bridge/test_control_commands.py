import unittest
from unittest import mock
import json
import tempfile
from pathlib import Path

from tests.telegram_bridge.helpers import FakeTelegramClient, make_config

import telegram_bridge.control_commands as bridge_control_commands
from telegram_bridge.state_store import State


class TestControlCommands(unittest.TestCase):
    def test_handle_reset_command_replies_when_context_cleared(self):
        client = FakeTelegramClient()

        with mock.patch.object(bridge_control_commands, "clear_thread_id", return_value=True):
            with mock.patch.object(bridge_control_commands, "clear_worker_session") as clear_worker_session:
                with mock.patch.object(bridge_control_commands.PiEngineAdapter, "clear_scope_session_files"):
                    bridge_control_commands.handle_reset_command(
                        State(),
                        make_config(persistent_workers_enabled=False),
                        client,
                        "tg:1",
                        1,
                        77,
                        88,
                    )

        clear_worker_session.assert_not_called()
        self.assertEqual(
            client.messages[-1],
            (1, "Context reset. Your next message starts a new conversation.", 88, None),
        )

    def test_handle_reset_command_marks_stale_warning_handled(self):
        client = FakeTelegramClient()
        with tempfile.TemporaryDirectory() as tmpdir:
            state_dir = Path(tmpdir)
            stale_path = state_dir / "dream_loop_stale_context.json"
            stale_path.write_text(
                json.dumps(
                    {
                        "tg:1": {
                            "scope_key": "tg:1",
                            "warning_fingerprint": "fp-1",
                            "warning_generated_at": "2026-05-20T10:00:00+10:00",
                            "warning_outstanding": True,
                            "handled_fingerprint": "",
                            "handled_at": "",
                            "last_reset_at": "",
                        }
                    }
                ),
                encoding="utf-8",
            )
            with mock.patch.object(bridge_control_commands, "clear_thread_id", return_value=True):
                with mock.patch.object(bridge_control_commands, "clear_worker_session") as clear_worker_session:
                    with mock.patch.object(bridge_control_commands.PiEngineAdapter, "clear_scope_session_files"):
                        bridge_control_commands.handle_reset_command(
                            State(),
                            make_config(state_dir=str(state_dir), persistent_workers_enabled=False),
                            client,
                            "tg:1",
                            1,
                            77,
                            88,
                        )

            clear_worker_session.assert_not_called()
            persisted = json.loads(stale_path.read_text(encoding="utf-8"))
            self.assertFalse(persisted["tg:1"]["warning_outstanding"])
            self.assertEqual(persisted["tg:1"]["handled_fingerprint"], "fp-1")
            self.assertIn("Outstanding stale-context warning marked handled.", client.messages[-1][1])

    def test_handle_restart_command_queued_replies_with_busy_count(self):
        client = FakeTelegramClient()

        with mock.patch.object(
            bridge_control_commands,
            "request_safe_restart",
            return_value=("queued", 3),
        ):
            bridge_control_commands.handle_restart_command(State(), client, 1, 77, 88)

        self.assertEqual(
            client.messages[-1],
            (1, "Safe restart queued. Waiting for 3 active request(s) to finish.", 88, None),
        )

    def test_handle_restart_command_triggers_async_restart_when_idle(self):
        state = State()
        client = FakeTelegramClient()

        with mock.patch.object(
            bridge_control_commands,
            "request_safe_restart",
            return_value=("restart_now", 0),
        ):
            with mock.patch.object(bridge_control_commands, "trigger_restart_async") as trigger_restart_async:
                bridge_control_commands.handle_restart_command(state, client, 1, 77, 88)

        self.assertEqual(client.messages[-1], (1, "No active request. Restarting bridge now.", 88, None))
        trigger_restart_async.assert_called_once_with(state, client, 1, 77, 88)

    def test_handle_cancel_command_replies_for_requested_status(self):
        client = FakeTelegramClient()

        with mock.patch.object(bridge_control_commands, "request_chat_cancel", return_value="requested"):
            bridge_control_commands.handle_cancel_command(State(), client, "tg:1", 1, 77, 88)

        self.assertEqual(client.messages[-1], (1, bridge_control_commands.CANCEL_REQUESTED_MESSAGE, 88, None))

    def test_handle_cancel_command_replies_for_unavailable_status(self):
        client = FakeTelegramClient()

        with mock.patch.object(bridge_control_commands, "request_chat_cancel", return_value="unavailable"):
            bridge_control_commands.handle_cancel_command(State(), client, "tg:1", 1, 77, 88)

        self.assertEqual(
            client.messages[-1],
            (
                1,
                "Active request cannot be canceled at this stage. Please wait a few seconds and retry.",
                88,
                None,
            ),
        )

    def test_handle_truth_status_command_reports_scope_stale_state(self):
        client = FakeTelegramClient()
        with tempfile.TemporaryDirectory() as tmpdir:
            state_dir = Path(tmpdir) / "bridge"
            dream_dir = Path(tmpdir) / "dream"
            state_dir.mkdir(parents=True, exist_ok=True)
            dream_dir.mkdir(parents=True, exist_ok=True)
            (dream_dir / "latest_truth_state.json").write_text(
                json.dumps(
                    {
                        "stale_context_eligibility": {
                            "eligible_scope_keys": ["tg:1"],
                            "changed_machine_inputs": ["ARCHITECT_INSTRUCTION.md"],
                            "changed_policy_inputs": ["src/telegram_bridge/runtime_config.py"],
                        }
                    }
                ),
                encoding="utf-8",
            )
            (dream_dir / "latest_run_state.json").write_text(
                json.dumps(
                    {
                        "generated_at": "2026-05-20T12:00:00+10:00",
                        "run_status": "succeeded",
                        "skipped_checks": [],
                    }
                ),
                encoding="utf-8",
            )
            (state_dir / "dream_loop_stale_context.json").write_text(
                json.dumps(
                    {
                        "tg:1": {
                            "scope_key": "tg:1",
                            "warning_fingerprint": "abcdef1234567890",
                            "warning_generated_at": "2026-05-20T11:00:00+10:00",
                            "warning_outstanding": True,
                            "handled_fingerprint": "",
                            "handled_at": "",
                            "last_reset_at": "",
                        }
                    }
                ),
                encoding="utf-8",
            )
            with mock.patch.dict("os.environ", {"DREAM_LOOP_STATE_DIR": str(dream_dir)}):
                bridge_control_commands.handle_truth_status_command(
                    State(),
                    make_config(state_dir=str(state_dir)),
                    client,
                    "tg:1",
                    1,
                    77,
                    88,
                )

        text = client.messages[-1][1]
        self.assertIn("Dream-loop truth status:", text)
        self.assertIn("Outstanding stale warning: yes", text)
        self.assertIn("Scope currently eligible for stale warning: yes", text)
        self.assertIn("ARCHITECT_INSTRUCTION.md", text)


if __name__ == "__main__":
    unittest.main()
