"""Unit tests for the StreamConsumer (Hermes-style progressive streaming)."""

import asyncio
import unittest
from typing import List, Optional, Tuple

from telegram_bridge.stream_consumer import (
    StreamConsumer,
    StreamConsumerConfig,
    _clean_for_display,
)


class FakeTelegramClient:
    """Minimal Telegram stand-in that records send/edit/delete calls.

    Mirrors the shape of ``TelegramChannelAdapter`` so the consumer
    exercises the real control flow without touching the network.
    """

    channel_name = "telegram"
    supports_message_edits = True

    def __init__(self) -> None:
        self.sends: List[Tuple[int, str, Optional[int], Optional[int]]] = []
        self.edits: List[Tuple[int, int, str]] = []
        self.next_message_id: int = 100

    def send_message_get_id(self, chat_id, text, reply_to_message_id=None, message_thread_id=None):
        self.sends.append((chat_id, text, reply_to_message_id, message_thread_id))
        self.next_message_id += 1
        return {"ok": True, "message_id": self.next_message_id}

    def edit_message(self, chat_id, message_id, text):
        self.edits.append((chat_id, message_id, text))
        return None


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _drive(consumer, action):
    """Run a single-step test scenario against a started consumer.

    The consumer exposes a sync facade (``start`` + ``wait_until_done``);
    this helper runs ``action()`` and then blocks until the consumer
    finishes. Tests can call ``consumer.on_delta`` etc. inside
    ``action`` to drive the consumer.
    """
    consumer.start()
    action()
    return consumer.wait_until_done(timeout=2.0)


class StreamConsumerConfigTests(unittest.TestCase):
    def test_from_config_returns_defaults_when_streaming_block_missing(self) -> None:
        cfg = StreamConsumerConfig.from_config(None)
        self.assertFalse(cfg.edit_interval != cfg.edit_interval)  # truthy
        self.assertEqual(cfg.cursor, " ▉")
        self.assertEqual(cfg.max_message_length, 4096)

    def test_from_config_reads_streaming_block(self) -> None:
        class _Streaming:
            edit_interval = 0.25
            buffer_threshold = 10
            cursor = " |"
            max_message_length = 8000
            min_first_message_chars = 8

        class _Config:
            streaming = _Streaming()

        cfg = StreamConsumerConfig.from_config(_Config())
        self.assertEqual(cfg.edit_interval, 0.25)
        self.assertEqual(cfg.buffer_threshold, 10)
        self.assertEqual(cfg.cursor, " |")
        self.assertEqual(cfg.max_message_length, 8000)
        self.assertEqual(cfg.min_first_message_chars, 8)


class CleanForDisplayTests(unittest.TestCase):
    def test_strips_media_directive(self) -> None:
        cleaned = _clean_for_display("hello MEDIA:/tmp/x.png world")
        self.assertNotIn("MEDIA:", cleaned)
        self.assertIn("hello", cleaned)
        self.assertIn("world", cleaned)

    def test_strips_audio_as_voice_directive(self) -> None:
        cleaned = _clean_for_display("hi [[audio_as_voice]] there")
        self.assertNotIn("audio_as_voice", cleaned)
        self.assertIn("hi", cleaned)
        self.assertIn("there", cleaned)

    def test_preserves_plain_text(self) -> None:
        self.assertEqual(_clean_for_display("plain text"), "plain text")


class StreamConsumerHappyPathTests(unittest.TestCase):
    def test_first_delta_creates_message_with_cursor_subsequent_deltas_edit_it(self) -> None:
        client = FakeTelegramClient()
        cfg = StreamConsumerConfig(
            edit_interval=0.0,  # immediate flush on every tick
            buffer_threshold=0,
            cursor=" ▉",
            min_first_message_chars=2,
        )
        consumer = StreamConsumer(client, 42, 7, config=cfg, initial_reply_to_message_id=99)

        def action():
            consumer.on_delta("Hello")
            consumer.on_delta(", world")
            consumer.finish()

        done = _drive(consumer, action)
        self.assertTrue(done)
        # First message goes out via send_message_get_id (with cursor).
        self.assertEqual(len(client.sends), 1)
        chat_id, text, reply_to, thread_id = client.sends[0]
        self.assertEqual(chat_id, 42)
        self.assertEqual(reply_to, 99)
        self.assertEqual(thread_id, 7)
        self.assertIn("Hello, world", text)
        # Final edit (cursor stripped) should land via edit_message.
        self.assertTrue(any("Hello, world" in e[2] and "▉" not in e[2] for e in client.edits))
        self.assertTrue(consumer.final_response_sent)
        self.assertTrue(consumer.stats.final_response_sent)
        consumer.stop_loop()

    def test_final_response_sent_false_when_consumer_never_saw_deltas(self) -> None:
        client = FakeTelegramClient()
        cfg = StreamConsumerConfig(edit_interval=0.0, buffer_threshold=0)
        consumer = StreamConsumer(client, 42, 7, config=cfg)

        def action():
            consumer.finish()

        _drive(consumer, action)
        # No deltas were emitted, so the consumer should not claim it
        # delivered a final reply — the bridge's normal final-send
        # path remains authoritative.
        self.assertFalse(consumer.final_response_sent)
        self.assertEqual(client.sends, [])
        self.assertEqual(client.edits, [])
        consumer.stop_loop()


class StreamConsumerFallbackTests(unittest.TestCase):
    def test_edit_failure_promotes_to_fallback_final_send(self) -> None:
        class FlakyClient(FakeTelegramClient):
            def __init__(self) -> None:
                super().__init__()
                self._edit_calls = 0

            def edit_message(self, chat_id, message_id, text):
                self._edit_calls += 1
                # First N edits fail with the standard "not modified"
                # error path is a no-op; we want hard failures, so
                # raise a different RuntimeError that the consumer
                # treats as a real failure.
                raise RuntimeError("TELEGRAM_API editMessageText failed: 429 retry after 5")

        client = FlakyClient()
        cfg = StreamConsumerConfig(
            edit_interval=0.0,
            buffer_threshold=0,
            cursor=" ▉",
            min_first_message_chars=2,
        )
        # Lower the flood-strike threshold by monkey-patching the
        # module-level default to make the test fast.
        import telegram_bridge.stream_consumer as sc_mod

        original = sc_mod.DEFAULT_MAX_FLOOD_STRIKES
        sc_mod.DEFAULT_MAX_FLOOD_STRIKES = 1
        try:
            consumer = StreamConsumer(client, 42, 7, config=cfg)

            def action():
                # Multiple deltas so the consumer actually attempts an
                # edit (the first delta always lands via send; edits
                # only happen on the 2nd+ delta).
                consumer.on_delta("partial ")
                consumer.on_delta("text one ")
                consumer.on_delta("text two ")
                consumer.finish()

            _drive(consumer, action)
            # The first send landed; subsequent edits failed; the
            # fallback path should have sent the final accumulated text
            # via send_message_get_id.
            self.assertTrue(consumer.stats.fallback_final_send)
            self.assertGreaterEqual(len(client.sends), 1)
            self.assertTrue(consumer.final_response_sent)
            consumer.stop_loop()
        finally:
            sc_mod.DEFAULT_MAX_FLOOD_STRIKES = original


class StreamConsumerSegmentBreakTests(unittest.TestCase):
    def test_segment_break_resets_accumulator(self) -> None:
        client = FakeTelegramClient()
        cfg = StreamConsumerConfig(
            edit_interval=0.0,
            buffer_threshold=0,
            cursor=" ▉",
            min_first_message_chars=2,
        )
        consumer = StreamConsumer(client, 42, 7, config=cfg)

        def action():
            consumer.on_delta("first part ")
            consumer.on_segment_break()
            consumer.on_delta("second part")
            consumer.finish()

        _drive(consumer, action)
        # At least one send and one edit. After the segment break the
        # second batch should have produced a fresh edit (or send) of
        # the second-part text.
        self.assertGreaterEqual(len(client.sends), 1)
        # Final content must mention both parts.
        final = " ".join(text for _chat, _mid, text in client.edits) + " " + " ".join(
            t for _c, t, _r, _th in client.sends
        )
        self.assertIn("first part", final)
        self.assertIn("second part", final)
        consumer.stop_loop()


class StreamConsumerCommentaryTests(unittest.TestCase):
    def test_commentary_sends_its_own_message(self) -> None:
        client = FakeTelegramClient()
        cfg = StreamConsumerConfig(
            edit_interval=0.0,
            buffer_threshold=0,
            cursor=" ▉",
            min_first_message_chars=2,
        )
        consumer = StreamConsumer(client, 42, 7, config=cfg)

        def action():
            consumer.on_delta("streaming...")
            consumer.on_commentary("Inspecting the repo first.")
            consumer.on_delta(" more text")
            consumer.finish()

        _drive(consumer, action)
        # Commentary produces a fresh send; the streaming text is
        # delivered via edit.
        self.assertGreaterEqual(len(client.sends), 1)
        commentary_sends = [t for _c, t, _r, _th in client.sends if "Inspecting" in t]
        self.assertTrue(commentary_sends, "commentary message was not delivered as a separate send")
        consumer.stop_loop()


class StreamConsumerCleanupTests(unittest.TestCase):
    """Regression tests for the run-task teardown contract.

    The duplicate-body bug in ``_run`` used to set ``_finished_event``
    before the run loop had actually finished, which let
    ``wait_until_done`` return early. The follow-up cancellation then
    arrived at a pending ``_run_task`` and asyncio logged
    "Task was destroyed but it is pending!" once the loop closed.

    These tests pin the contract:
      * ``wait_until_done`` only returns True after the run task is done.
      * ``stop_loop`` is a no-op once the run task is done (no warning).
      * A consumer that has not been started leaves ``stop_loop`` clean.
    """

    def _assert_no_pending_task_warnings(self, log_output: str) -> None:
        self.assertNotIn(
            "Task was destroyed but it is pending",
            log_output,
            "asyncio logged a destroyed-pending-task warning during teardown",
        )

    def test_finish_then_stop_loop_does_not_leave_pending_run_task(self) -> None:
        import io
        import logging

        client = FakeTelegramClient()
        cfg = StreamConsumerConfig(
            edit_interval=0.0, buffer_threshold=0, cursor=" ▉", min_first_message_chars=2
        )
        consumer = StreamConsumer(client, 42, 7, config=cfg)

        consumer.start()
        consumer.on_delta("hello")
        consumer.finish()
        self.assertTrue(consumer.wait_until_done(timeout=2.0))

        # The run task must be done at this point, not still pending.
        run_task = consumer._run_task
        self.assertIsNotNone(run_task)
        self.assertTrue(
            run_task.done(),
            "run task should be done after wait_until_done returns",
        )

        # Capture asyncio's "Task was destroyed" warning channel for
        # the duration of stop_loop so we can assert nothing leaked.
        buf = io.StringIO()
        handler = logging.StreamHandler(buf)
        handler.setLevel(logging.WARNING)
        asyncio_logger = logging.getLogger("asyncio")
        previous_level = asyncio_logger.level
        asyncio_logger.addHandler(handler)
        try:
            consumer.stop_loop()
        finally:
            asyncio_logger.removeHandler(handler)
            asyncio_logger.setLevel(previous_level)

        self._assert_no_pending_task_warnings(buf.getvalue())

    def test_stop_loop_without_start_is_a_clean_noop(self) -> None:
        consumer = StreamConsumer(FakeTelegramClient(), 1, 1)
        # Must not raise; no loop / no task to tear down.
        consumer.stop_loop()
        self.assertIsNone(consumer._run_task)


class StreamConsumerConfigSanityTests(unittest.TestCase):
    def test_default_cursor_is_visible(self) -> None:
        cfg = StreamConsumerConfig()
        self.assertTrue(cfg.cursor.strip())
        # The default cursor is " ▉" — a single block character that
        # renders as a visible streaming indicator. Tests rely on the
        # exact string for filter assertions.
        self.assertEqual(cfg.cursor, " ▉")

    def test_min_first_message_chars_default_blocks_tiny_first_sends(self) -> None:
        cfg = StreamConsumerConfig()
        self.assertEqual(cfg.min_first_message_chars, 4)


if __name__ == "__main__":
    unittest.main()
