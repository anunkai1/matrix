import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from tests.telegram_bridge.helpers import FakeTelegramClient, make_config

import telegram_bridge.command_known_routing as command_known_routing
from telegram_bridge.handler_models import KnownCommandContext
from telegram_bridge.state_store import State


class TestCommandKnownRouting(unittest.TestCase):
    def test_handle_known_command_returns_false_for_missing_command(self):
        handled = command_known_routing.handle_known_command(
            State(),
            make_config(),
            FakeTelegramClient(),
            "tg:1",
            1,
            None,
            10,
            None,
            "",
            known_command_context_cls=KnownCommandContext,
            help_command_aliases={"/help"},
            cancel_command_aliases={"/cancel"},
            handle_help_known_command=lambda *_args: self.fail("help should not run"),
            handle_cancel_known_command=lambda *_args: self.fail("cancel should not run"),
            known_command_handlers={},
            diary_mode_enabled=lambda _config: False,
            diary_command_handlers={},
        )

        self.assertFalse(handled)

    def test_handle_known_command_routes_help_alias(self):
        observed = {}

        def handle_help(ctx):
            observed["raw_text"] = ctx.raw_text
            return True

        handled = command_known_routing.handle_known_command(
            State(),
            make_config(),
            FakeTelegramClient(),
            "tg:1",
            1,
            None,
            11,
            "/h",
            "/h",
            known_command_context_cls=KnownCommandContext,
            help_command_aliases={"/h", "/help"},
            cancel_command_aliases={"/cancel"},
            handle_help_known_command=handle_help,
            handle_cancel_known_command=lambda *_args: self.fail("cancel should not run"),
            known_command_handlers={},
            diary_mode_enabled=lambda _config: False,
            diary_command_handlers={},
        )

        self.assertTrue(handled)
        self.assertEqual(observed["raw_text"], "/h")

    def test_handle_known_command_routes_cancel_alias(self):
        observed = {}

        def handle_cancel(ctx):
            observed["scope_key"] = ctx.scope_key
            return True

        handled = command_known_routing.handle_known_command(
            State(),
            make_config(),
            FakeTelegramClient(),
            "tg:cancel",
            1,
            None,
            12,
            "/cancel",
            "/cancel",
            known_command_context_cls=KnownCommandContext,
            help_command_aliases={"/help"},
            cancel_command_aliases={"/cancel"},
            handle_help_known_command=lambda *_args: self.fail("help should not run"),
            handle_cancel_known_command=handle_cancel,
            known_command_handlers={},
            diary_mode_enabled=lambda _config: False,
            diary_command_handlers={},
        )

        self.assertTrue(handled)
        self.assertEqual(observed["scope_key"], "tg:cancel")

    def test_handle_known_command_routes_registered_handler(self):
        observed = {}

        def handle_engine(ctx):
            observed["chat_id"] = ctx.chat_id
            return True

        handled = command_known_routing.handle_known_command(
            State(),
            make_config(),
            FakeTelegramClient(),
            "tg:1",
            99,
            None,
            13,
            "/engine",
            "/engine status",
            known_command_context_cls=KnownCommandContext,
            help_command_aliases={"/help"},
            cancel_command_aliases={"/cancel"},
            handle_help_known_command=lambda *_args: self.fail("help should not run"),
            handle_cancel_known_command=lambda *_args: self.fail("cancel should not run"),
            known_command_handlers={"/engine": handle_engine},
            diary_mode_enabled=lambda _config: False,
            diary_command_handlers={},
        )

        self.assertTrue(handled)
        self.assertEqual(observed["chat_id"], 99)

    def test_handle_known_command_routes_diary_handler_only_when_enabled(self):
        observed = {}

        def handle_today(ctx):
            observed["message_id"] = ctx.message_id
            return True

        enabled = command_known_routing.handle_known_command(
            State(),
            make_config(),
            FakeTelegramClient(),
            "tg:1",
            1,
            None,
            14,
            "/today",
            "/today",
            known_command_context_cls=KnownCommandContext,
            help_command_aliases={"/help"},
            cancel_command_aliases={"/cancel"},
            handle_help_known_command=lambda *_args: self.fail("help should not run"),
            handle_cancel_known_command=lambda *_args: self.fail("cancel should not run"),
            known_command_handlers={},
            diary_mode_enabled=lambda _config: True,
            diary_command_handlers={"/today": handle_today},
        )

        disabled = command_known_routing.handle_known_command(
            State(),
            make_config(),
            FakeTelegramClient(),
            "tg:1",
            1,
            None,
            15,
            "/today",
            "/today",
            known_command_context_cls=KnownCommandContext,
            help_command_aliases={"/help"},
            cancel_command_aliases={"/cancel"},
            handle_help_known_command=lambda *_args: self.fail("help should not run"),
            handle_cancel_known_command=lambda *_args: self.fail("cancel should not run"),
            known_command_handlers={},
            diary_mode_enabled=lambda _config: False,
            diary_command_handlers={"/today": handle_today},
        )

        self.assertTrue(enabled)
        self.assertFalse(disabled)
        self.assertEqual(observed["message_id"], 14)


if __name__ == "__main__":
    unittest.main()
