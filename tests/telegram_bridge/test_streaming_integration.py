"""Integration tests for progressive streaming wiring.

Covers:
  * ``ProgressReporter.handle_executor_event`` routing ``text_delta``
    events to a stream consumer (or ignoring them when no consumer is
    attached).
  * ``stream_control`` ``/stream on|off|status|reset`` behavior.
  * ``state_store`` per-scope ``chat_streaming_enabled`` round-trip
    through load/persist.
"""

import os
import tempfile
import unittest
from unittest import mock

from telegram_bridge import handler_progress
from telegram_bridge import stream_control
from telegram_bridge.executor import ExecutorProgressEvent
from telegram_bridge.state_store import (
    get_chat_streaming_enabled,
    set_chat_streaming_enabled,
    clear_chat_streaming_enabled,
)
from telegram_bridge.state_models import State


class FakeTelegramClient:
    channel_name = "telegram"
    supports_message_edits = True

    def __init__(self):
        self.sends = []
        self.edits = []

    def send_message_get_id(self, chat_id, text, reply_to_message_id=None, message_thread_id=None):
        self.sends.append((chat_id, text, reply_to_message_id))
        return {"ok": True, "message_id": 999}

    def edit_message(self, chat_id, message_id, text):
        self.edits.append((chat_id, message_id, text))

    def send_message(self, chat_id, text, reply_to_message_id=None, message_thread_id=None, reply_markup=None):
        self.sends.append((chat_id, text, reply_to_message_id))

    def send_chat_action(self, chat_id, action, message_thread_id=None):
        return None


class ProgressReporterTextDeltaTests(unittest.TestCase):
    def test_text_delta_routed_to_consumer(self):
        reporter = handler_progress.ProgressReporter(
            client=FakeTelegramClient(),
            chat_id=1,
            reply_to_message_id=5,
            message_thread_id=None,
            assistant_name="Architect",
        )
        consumer = mock.MagicMock()
        reporter.stream_consumer = consumer

        reporter.handle_executor_event(ExecutorProgressEvent(kind="text_delta", detail="hello"))
        consumer.on_delta.assert_called_once_with("hello")

    def test_text_delta_without_consumer_is_silent(self):
        reporter = handler_progress.ProgressReporter(
            client=FakeTelegramClient(),
            chat_id=1,
            reply_to_message_id=5,
            message_thread_id=None,
            assistant_name="Architect",
        )
        # No consumer attached. The event must not raise and must not
        # mutate the reporter's phase label.
        reporter.handle_executor_event(ExecutorProgressEvent(kind="text_delta", detail="hello"))
        self.assertEqual(reporter.phase, "")
        self.assertFalse(reporter.streaming_active)

    def test_text_delta_with_failing_consumer_is_swallowed(self):
        reporter = handler_progress.ProgressReporter(
            client=FakeTelegramClient(),
            chat_id=1,
            reply_to_message_id=5,
            message_thread_id=None,
            assistant_name="Architect",
        )
        consumer = mock.MagicMock()
        consumer.on_delta.side_effect = RuntimeError("queue full")
        reporter.stream_consumer = consumer

        # Must not raise; the consumer's failure is logged and the
        # reporter keeps going.
        reporter.handle_executor_event(ExecutorProgressEvent(kind="text_delta", detail="x"))

    def test_agent_message_marks_streaming_active_when_consumer_attached(self):
        reporter = handler_progress.ProgressReporter(
            client=FakeTelegramClient(),
            chat_id=1,
            reply_to_message_id=5,
            message_thread_id=None,
            assistant_name="Architect",
        )
        reporter.stream_consumer = mock.MagicMock()
        reporter.handle_executor_event(ExecutorProgressEvent(kind="agent_message", detail="final"))
        self.assertTrue(reporter.streaming_active)


class _StubStreaming:
    enabled = True
    supported_engine_plugins = "codex,pi"

    def is_engine_supported(self, engine_plugin):
        if not self.enabled:
            return False
        return engine_plugin in {"codex", "pi"}


class _StubConfig:
    streaming = _StubStreaming()


class StreamControlTests(unittest.TestCase):
    def _make_state(self):
        return State()

    def test_status_reports_global_and_scope_state(self):
        state = self._make_state()
        client = FakeTelegramClient()
        config = _StubConfig
        text = stream_control.build_streaming_status_text(state, config, "tg:1:topic:2", "codex")
        self.assertIn("off", text)
        self.assertIn("unset (uses global)", text)
        self.assertIn("codex", text)

    def test_on_off_reset_roundtrip(self):
        state = self._make_state()
        scope = "tg:1:topic:2"
        # Opt in
        set_chat_streaming_enabled(state, scope, True)
        self.assertTrue(get_chat_streaming_enabled(state, scope))
        # Opt out
        set_chat_streaming_enabled(state, scope, False)
        self.assertFalse(get_chat_streaming_enabled(state, scope))
        # Reset
        cleared = clear_chat_streaming_enabled(state, scope)
        self.assertTrue(cleared)
        self.assertIsNone(get_chat_streaming_enabled(state, scope))

    def test_handle_stream_command_on(self):
        state = self._make_state()
        client = FakeTelegramClient()
        config = _StubConfig
        handled = stream_control.handle_stream_command(
            state=state,
            config=config,
            client=client,
            scope_key="tg:1:topic:2",
            chat_id=1,
            message_thread_id=2,
            message_id=99,
            raw_text="/stream on",
            active_engine_plugin_fn=lambda *_: "codex",
        )
        self.assertTrue(handled)
        self.assertEqual(len(client.sends), 1)
        self.assertIn("enabled", client.sends[0][1].lower())
        self.assertTrue(get_chat_streaming_enabled(state, "tg:1:topic:2"))

    def test_handle_stream_command_off(self):
        state = self._make_state()
        set_chat_streaming_enabled(state, "tg:1:topic:2", True)
        client = FakeTelegramClient()
        handled = stream_control.handle_stream_command(
            state=state,
            config=_StubConfig,
            client=client,
            scope_key="tg:1:topic:2",
            chat_id=1,
            message_thread_id=2,
            message_id=99,
            raw_text="/stream off",
            active_engine_plugin_fn=lambda *_: "codex",
        )
        self.assertTrue(handled)
        self.assertFalse(get_chat_streaming_enabled(state, "tg:1:topic:2"))

    def test_handle_stream_command_reset(self):
        state = self._make_state()
        set_chat_streaming_enabled(state, "tg:1:topic:2", True)
        client = FakeTelegramClient()
        handled = stream_control.handle_stream_command(
            state=state,
            config=_StubConfig,
            client=client,
            scope_key="tg:1:topic:2",
            chat_id=1,
            message_thread_id=2,
            message_id=99,
            raw_text="/stream reset",
            active_engine_plugin_fn=lambda *_: "codex",
        )
        self.assertTrue(handled)
        self.assertIsNone(get_chat_streaming_enabled(state, "tg:1:topic:2"))

    def test_handle_stream_command_unknown_tail_returns_usage(self):
        state = self._make_state()
        client = FakeTelegramClient()
        handled = stream_control.handle_stream_command(
            state=state,
            config=_StubConfig,
            client=client,
            scope_key="tg:1:topic:2",
            chat_id=1,
            message_thread_id=2,
            message_id=99,
            raw_text="/stream foo",
            active_engine_plugin_fn=lambda *_: "codex",
        )
        self.assertTrue(handled)
        self.assertIn("Unknown", client.sends[0][1])


class ChatStreamingEnabledPersistenceTests(unittest.TestCase):
    def test_persist_and_reload_roundtrip(self):
        from telegram_bridge.scope_state_store import (
            load_chat_streaming_enabled,
            persist_chat_streaming_enabled,
        )
        from telegram_bridge.conversation_scope import normalize_scope_storage_key

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "chat_streaming_enabled.json")
            state = State()
            state.chat_streaming_enabled_path = path
            set_chat_streaming_enabled(state, "tg:1:topic:2", True)
            set_chat_streaming_enabled(state, "tg:3", False)
            persist_chat_streaming_enabled(state)
            loaded = load_chat_streaming_enabled(path)
            # ``loaded`` keys are ScopeKey instances (chat_id +
            # topic_id) — convert the test expectations to the same
            # canonical form for the assertion.
            self.assertIn(normalize_scope_storage_key("tg:1:topic:2"), loaded)
            self.assertIn(normalize_scope_storage_key("tg:3"), loaded)
            self.assertTrue(loaded[normalize_scope_storage_key("tg:1:topic:2")])
            self.assertFalse(loaded[normalize_scope_storage_key("tg:3")])


if __name__ == "__main__":
    unittest.main()
