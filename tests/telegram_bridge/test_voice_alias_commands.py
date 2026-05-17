import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from tests.telegram_bridge.helpers import FakeTelegramClient, make_config

import telegram_bridge.main as bridge
import telegram_bridge.voice_alias_commands as bridge_voice_alias_commands


class TestVoiceAliasCommands(unittest.TestCase):
    def test_handle_voice_alias_command_replies_when_learning_disabled(self):
        client = FakeTelegramClient()

        handled = bridge_voice_alias_commands.handle_voice_alias_command(
            state=bridge.State(),
            config=make_config(),
            client=client,
            chat_id=1,
            message_id=91,
            raw_text="/voice-alias list",
        )

        self.assertTrue(handled)
        self.assertEqual(client.messages[-1], (1, "Voice alias learning is disabled.", 91, None))

    def test_handle_voice_alias_command_lists_pending_suggestions(self):
        client = FakeTelegramClient()
        learning_store = mock.Mock()
        learning_store.list_pending.return_value = [
            SimpleNamespace(suggestion_id=7, source="master broom", target="master bedroom", count=3)
        ]
        state = bridge.State(voice_alias_learning_store=learning_store)

        handled = bridge_voice_alias_commands.handle_voice_alias_command(
            state=state,
            config=make_config(),
            client=client,
            chat_id=1,
            message_id=92,
            raw_text="/voice-alias list",
        )

        self.assertTrue(handled)
        self.assertIn("Pending voice alias suggestions:", client.messages[-1][1])
        self.assertIn("#7: `master broom` => `master bedroom`", client.messages[-1][1])
        self.assertEqual(client.messages[-1][2], 92)


if __name__ == "__main__":
    unittest.main()
