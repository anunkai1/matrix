import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from tests.telegram_bridge.helpers import FakeTelegramClient, make_config

import telegram_bridge.command_routing as bridge_command_routing
from telegram_bridge.handler_models import KnownCommandContext
from telegram_bridge.state_store import State


class TestCommandRouting(unittest.TestCase):
    def _ctx(self, **overrides):
        base = {
            "state": State(),
            "config": make_config(),
            "client": FakeTelegramClient(),
            "scope_key": "tg:1",
            "chat_id": 1,
            "message_thread_id": 77,
            "message_id": 88,
            "raw_text": "/status",
        }
        base.update(overrides)
        return KnownCommandContext(**base)

    def test_handle_start_known_command_replies_to_trigger_message(self):
        ctx = self._ctx(message_thread_id=None, raw_text="/start")

        with mock.patch.object(bridge_command_routing, "start_command_message", return_value="hello"):
            handled = bridge_command_routing._handle_start_known_command(ctx)

        self.assertTrue(handled)
        self.assertEqual(ctx.client.messages[-1], (1, "hello", 88, None))

    def test_handle_status_known_command_includes_thread_reply(self):
        ctx = self._ctx(raw_text="/status")

        with mock.patch.object(bridge_command_routing, "build_status_text", return_value="status"):
            handled = bridge_command_routing._handle_status_known_command(ctx)

        self.assertTrue(handled)
        self.assertEqual(ctx.client.messages[-1], (1, "status", 88, None))

    def test_handle_diary_queue_known_command_replies_with_queue_status(self):
        ctx = self._ctx(raw_text="/queue")

        with mock.patch.object(bridge_command_routing, "build_diary_queue_status", return_value="queue status"):
            handled = bridge_command_routing._handle_diary_queue_known_command(ctx)

        self.assertTrue(handled)
        self.assertEqual(ctx.client.messages[-1], (1, "queue status", 88, None))


if __name__ == "__main__":
    unittest.main()
