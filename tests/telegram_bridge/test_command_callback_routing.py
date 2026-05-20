import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from tests.telegram_bridge.helpers import FakeTelegramClient, make_config

import telegram_bridge.command_callback_routing as command_callback_routing
import telegram_bridge.command_routing as bridge_command_routing
import telegram_bridge.remember_commands as bridge_remember_commands
from telegram_bridge.handler_models import CallbackActionContext, CallbackActionResult
from telegram_bridge.state_store import State


def _callback_context(update):
    callback_query = update.get("callback_query", {})
    message = callback_query.get("message")
    if not isinstance(message, dict):
        return None, None, None, None, None
    chat = message.get("chat", {})
    scope = SimpleNamespace(
        chat_id=chat.get("id"),
        message_thread_id=message.get("message_thread_id"),
        scope_key="tg:1",
    )
    return (
        message,
        scope,
        message.get("message_id"),
        callback_query.get("id"),
        callback_query.get("data"),
    )


class TestCommandCallbackRouting(unittest.TestCase):
    def test_resolve_callback_action_handler_prefers_exact_then_fallback(self):
        exact = lambda ctx: CallbackActionResult(text=f"exact:{ctx.engine_name}")
        fallback = lambda ctx: CallbackActionResult(text=f"fallback:{ctx.engine_name}")
        handlers = {
            ("provider", "pi"): exact,
            ("provider", None): fallback,
        }

        self.assertIs(
            command_callback_routing.resolve_callback_action_handler(
                "provider",
                "pi",
                callback_action_handlers=handlers,
            ),
            exact,
        )
        self.assertIs(
            command_callback_routing.resolve_callback_action_handler(
                "provider",
                "gemma",
                callback_action_handlers=handlers,
            ),
            fallback,
        )

    def test_handle_callback_query_denies_unlisted_chat(self):
        client = FakeTelegramClient()
        config = make_config(allowed_chat_ids={99})
        update = {
            "callback_query": {
                "id": "cb-denied",
                "data": "cfg|engine|codex|set",
                "message": {
                    "message_id": 10,
                    "chat": {"id": 1, "type": "private"},
                },
            }
        }

        handled = command_callback_routing.handle_callback_query(
            State(),
            config,
            client,
            update,
            extract_callback_query_context=_callback_context,
            resolve_callback_action_handler_fn=lambda *_args: None,
            callback_action_context_cls=CallbackActionContext,
            callback_action_result_cls=CallbackActionResult,
            brief_health_error=str,
        )

        self.assertTrue(handled)
        self.assertEqual(client.callback_answers[0], ("cb-denied", "Access denied."))

    def test_handle_callback_query_rejects_unknown_data(self):
        client = FakeTelegramClient()
        config = make_config()
        update = {
            "callback_query": {
                "id": "cb-unknown",
                "data": "not-cfg",
                "message": {
                    "message_id": 11,
                    "chat": {"id": 1, "type": "private"},
                },
            }
        }

        handled = command_callback_routing.handle_callback_query(
            State(),
            config,
            client,
            update,
            extract_callback_query_context=_callback_context,
            resolve_callback_action_handler_fn=lambda *_args: None,
            callback_action_context_cls=CallbackActionContext,
            callback_action_result_cls=CallbackActionResult,
            brief_health_error=str,
        )

        self.assertTrue(handled)
        self.assertEqual(client.callback_answers[0], ("cb-unknown", "Unknown action."))

    def test_handle_callback_query_sends_unsupported_action_result(self):
        client = FakeTelegramClient()
        config = make_config()
        update = {
            "callback_query": {
                "id": "cb-unsupported",
                "data": "cfg|unknown|x|set",
                "message": {
                    "message_id": 12,
                    "chat": {"id": 1, "type": "private"},
                },
            }
        }

        handled = command_callback_routing.handle_callback_query(
            State(),
            config,
            client,
            update,
            extract_callback_query_context=_callback_context,
            resolve_callback_action_handler_fn=lambda *_args: None,
            callback_action_context_cls=CallbackActionContext,
            callback_action_result_cls=CallbackActionResult,
            brief_health_error=str,
        )

        self.assertTrue(handled)
        self.assertEqual(client.callback_answers[0], ("cb-unsupported", "Unsupported action."))
        self.assertEqual(client.edits[0][2], "Unsupported action.")

    def test_handle_callback_query_falls_back_to_send_message_when_edit_fails(self):
        client = FakeTelegramClient()
        client.edit_message = lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("edit failed"))
        config = make_config()
        update = {
            "callback_query": {
                "id": "cb-edit-fallback",
                "data": "cfg|engine|codex|set",
                "message": {
                    "message_id": 13,
                    "chat": {"id": 1, "type": "private"},
                },
            }
        }

        def handler(ctx):
            return CallbackActionResult(text=f"did:{ctx.action}")

        handled = command_callback_routing.handle_callback_query(
            State(),
            config,
            client,
            update,
            extract_callback_query_context=_callback_context,
            resolve_callback_action_handler_fn=lambda *_args: handler,
            callback_action_context_cls=CallbackActionContext,
            callback_action_result_cls=CallbackActionResult,
            brief_health_error=str,
        )

        self.assertTrue(handled)
        self.assertEqual(client.callback_answers[0], ("cb-edit-fallback", "Updated."))
        self.assertEqual(client.messages[0][1], "did:set")

    def test_handle_callback_query_reports_action_failure(self):
        client = FakeTelegramClient()
        config = make_config()
        update = {
            "callback_query": {
                "id": "cb-failed",
                "data": "cfg|engine|codex|set",
                "message": {
                    "message_id": 14,
                    "chat": {"id": 1, "type": "private"},
                },
            }
        }

        def handler(_ctx):
            raise RuntimeError("boom")

        handled = command_callback_routing.handle_callback_query(
            State(),
            config,
            client,
            update,
            extract_callback_query_context=_callback_context,
            resolve_callback_action_handler_fn=lambda *_args: handler,
            callback_action_context_cls=CallbackActionContext,
            callback_action_result_cls=CallbackActionResult,
            brief_health_error=str,
        )

        self.assertTrue(handled)
        self.assertEqual(client.callback_answers[0], ("cb-failed", "Action failed."))
        self.assertIn("Action failed.", client.edits[0][2])
        self.assertIn("boom", client.edits[0][2])

    def test_handle_callback_query_routes_remember_save_action(self):
        client = FakeTelegramClient()
        config = make_config()
        state = State()
        token = "remember-1"
        state.pending_remember_proposals[token] = bridge_remember_commands.PendingRememberProposal(
            scope_key="tg:1",
            text="Remember this exact line.",
        )
        update = {
            "callback_query": {
                "id": "cb-remember",
                "data": bridge_remember_commands.remember_callback_data("save", token),
                "message": {
                    "message_id": 15,
                    "chat": {"id": 1, "type": "private"},
                },
            }
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch.object(
                bridge_remember_commands,
                "remember_file_path",
                return_value=Path(tmpdir) / "remember.md",
            ):
                handled = bridge_command_routing.handle_callback_query(
                    state,
                    config,
                    client,
                    update,
                )
                saved_text = (Path(tmpdir) / "remember.md").read_text(encoding="utf-8")

        self.assertTrue(handled)
        self.assertEqual(client.callback_answers[0], ("cb-remember", bridge_remember_commands.SAVE_SUCCESS_TOAST))
        self.assertIn("Saved to `remember.md` as item 1", client.edits[0][2])
        self.assertEqual(saved_text, "1. Remember this exact line.\n")


if __name__ == "__main__":
    unittest.main()
