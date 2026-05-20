import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from tests.telegram_bridge.helpers import FakeTelegramClient, make_config

import telegram_bridge.command_routing as bridge_command_routing
import telegram_bridge.remember_commands as bridge_remember_commands
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

    def test_handle_remember_known_command_proposes_exact_text(self):
        ctx = self._ctx(raw_text="/remember codex stores local session history in jsonl files")

        handled = bridge_command_routing._handle_remember_known_command(ctx)

        self.assertTrue(handled)
        reply = ctx.client.messages[-1]
        self.assertEqual(reply[0], 1)
        self.assertEqual(reply[2], 88)
        self.assertIn("Proposed `remember.md` text:", reply[1])
        self.assertIn(
            "codex stores local session history in jsonl files.",
            reply[1],
        )
        self.assertIn(str(bridge_remember_commands.remember_file_path()), reply[1])
        self.assertIn("inline_keyboard", reply[3])
        self.assertEqual(reply[3]["inline_keyboard"][0][0]["text"], "Save")
        self.assertEqual(reply[3]["inline_keyboard"][0][1]["text"], "Cancel")

    def test_handle_remember_known_command_requires_text(self):
        ctx = self._ctx(raw_text="/remember")

        handled = bridge_command_routing._handle_remember_known_command(ctx)

        self.assertTrue(handled)
        self.assertEqual(
            ctx.client.messages[-1],
            (1, bridge_remember_commands.USAGE_MESSAGE, 88, None),
        )

    def test_handle_remember_known_command_delete_removes_numbered_item(self):
        ctx = self._ctx(raw_text="/remember delete 2")

        with tempfile.TemporaryDirectory() as tmpdir:
            remember_path = Path(tmpdir) / "remember.md"
            remember_path.write_text("1. First item.\n2. Second item.\n3. Third item.\n", encoding="utf-8")
            with mock.patch.object(
                bridge_remember_commands,
                "remember_file_path",
                return_value=remember_path,
            ):
                handled = bridge_command_routing._handle_remember_known_command(ctx)
                saved_text = remember_path.read_text(encoding="utf-8")

        self.assertTrue(handled)
        self.assertIn("Removed remembered item 2", ctx.client.messages[-1][1])
        self.assertEqual(saved_text, "1. First item.\n2. Third item.\n")

    def test_handle_remember_known_command_delete_requires_valid_number(self):
        ctx = self._ctx(raw_text="/remember delete nope")

        handled = bridge_command_routing._handle_remember_known_command(ctx)

        self.assertTrue(handled)
        self.assertEqual(ctx.client.messages[-1][1], "Usage: /remember delete <number>")

    def test_handle_remember_callback_action_saves_numbered_text(self):
        state = State()
        token = "tok-save"
        state.pending_remember_proposals[token] = bridge_remember_commands.PendingRememberProposal(
            scope_key="tg:1",
            text="Keep this exact sentence.",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch.object(
                bridge_remember_commands,
                "remember_file_path",
                return_value=Path(tmpdir) / "remember.md",
            ):
                result = bridge_command_routing._handle_remember_callback_action(
                    bridge_command_routing.CallbackActionContext(
                        state=state,
                        config=make_config(),
                        client=FakeTelegramClient(),
                        scope_key="tg:1",
                        chat_id=1,
                        message_thread_id=77,
                        message_id=88,
                        callback_query_id="cb1",
                        kind="remember",
                        engine_name="local",
                        action="save",
                        value=token,
                    )
                )
                saved_text = (Path(tmpdir) / "remember.md").read_text(encoding="utf-8")

        self.assertIn("Saved to `remember.md` as item 1", result.text)
        self.assertEqual(result.toast_text, bridge_remember_commands.SAVE_SUCCESS_TOAST)
        self.assertEqual(saved_text, "1. Keep this exact sentence.\n")
        self.assertNotIn(token, state.pending_remember_proposals)

    def test_handle_remember_callback_action_renumbers_legacy_entries_on_save(self):
        state = State()
        token = "tok-save-legacy"
        state.pending_remember_proposals[token] = bridge_remember_commands.PendingRememberProposal(
            scope_key="tg:1",
            text="Brand new item.",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            remember_path = Path(tmpdir) / "remember.md"
            remember_path.write_text("Legacy first.\nLegacy second.\n", encoding="utf-8")
            with mock.patch.object(
                bridge_remember_commands,
                "remember_file_path",
                return_value=remember_path,
            ):
                result = bridge_command_routing._handle_remember_callback_action(
                    bridge_command_routing.CallbackActionContext(
                        state=state,
                        config=make_config(),
                        client=FakeTelegramClient(),
                        scope_key="tg:1",
                        chat_id=1,
                        message_thread_id=77,
                        message_id=88,
                        callback_query_id="cb-legacy",
                        kind="remember",
                        engine_name="local",
                        action="save",
                        value=token,
                    )
                )
                saved_text = remember_path.read_text(encoding="utf-8")

        self.assertIn("Saved to `remember.md` as item 3", result.text)
        self.assertEqual(
            saved_text,
            "1. Legacy first.\n2. Legacy second.\n3. Brand new item.\n",
        )

    def test_handle_remember_callback_action_cancel_discards(self):
        state = State()
        token = "tok-cancel"
        state.pending_remember_proposals[token] = bridge_remember_commands.PendingRememberProposal(
            scope_key="tg:1",
            text="Discard this.",
        )

        result = bridge_command_routing._handle_remember_callback_action(
            bridge_command_routing.CallbackActionContext(
                state=state,
                config=make_config(),
                client=FakeTelegramClient(),
                scope_key="tg:1",
                chat_id=1,
                message_thread_id=77,
                message_id=88,
                callback_query_id="cb2",
                kind="remember",
                engine_name="local",
                action="cancel",
                value=token,
            )
        )

        self.assertEqual(result.toast_text, bridge_remember_commands.CANCEL_SUCCESS_TOAST)
        self.assertNotIn(token, state.pending_remember_proposals)


if __name__ == "__main__":
    unittest.main()
