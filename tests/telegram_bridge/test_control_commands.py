import unittest
from unittest import mock

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


if __name__ == "__main__":
    unittest.main()
