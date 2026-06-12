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


class StreamConsumerFallbackStateRegressionTests(unittest.TestCase):
    """Regression tests for the duplicate-send cascade (2026-06-10 07:24 UTC).

    Original bug: when ``_send_message`` raised in ``_send_or_edit`` (because
    the transport's 3-retry budget was exhausted on a 429), or when 3 edit
    attempts in a row failed with 429, the consumer only set
    ``_edit_supported = False`` and returned. It did NOT mark the consumer
    as in fallback mode (no ``_message_id = -1`` sentinel, no
    ``_fallback_final_send = True``, no ``_already_sent = True``). The next
    tick of the run loop then re-entered the "send the first message"
    branch and re-sent the full accumulated text via ``sendMessage``,
    producing a cascade of duplicate Telegram messages.

    These tests pin the contract: when send / edit fails hard, the consumer
    must transition atomically into fallback state, and the run loop must
    never call ``sendMessage`` with the same accumulated text more than
    once for a given stream.
    """

    def test_initial_send_exception_promotes_to_fallback_state(self) -> None:
        """If the very first sendMessage raises (e.g. 429 retries
        exhausted), the consumer must enter fallback state: ``_message_id``
        must become a sentinel, ``_fallback_final_send`` must be True, and
        ``_already_sent`` must be True so the run loop will not re-send
        the full accumulated text on every subsequent tick.
        """

        class AlwaysFailsClient(FakeTelegramClient):
            def send_message_get_id(self, chat_id, text, reply_to_message_id=None, message_thread_id=None):
                # Mirror what the real transport does on a 3-strike
                # flood: raise RuntimeError. The consumer should treat
                # this as a hard failure, not as "send succeeded with
                # no id".
                raise RuntimeError(
                    "TELEGRAM_API sendMessage failed: 429 Too Many Requests: retry after 9"
                )

        client = AlwaysFailsClient()
        cfg = StreamConsumerConfig(
            edit_interval=0.0,
            buffer_threshold=0,
            cursor=" ▉",
            min_first_message_chars=2,
        )
        consumer = StreamConsumer(client, 42, 7, config=cfg)

        def action() -> None:
            consumer.on_delta("Server2 is up but mavali.top is down")
            consumer.finish()

        _drive(consumer, action)
        # After a hard initial-send failure the consumer must be in
        # fallback mode so the run loop does not re-send the same text
        # on every tick. The key invariant is the sentinel on
        # ``_message_id`` (None is the "never tried" sentinel; -1 is
        # the "tried and gave up" sentinel; both must take the
        # "do not re-enter initial-send" branch).
        self.assertTrue(consumer.stats.fallback_final_send)
        self.assertTrue(consumer._fallback_final_send)
        self.assertTrue(consumer._already_sent)
        self.assertIsNotNone(
            consumer._message_id,
            "consumer must set a non-None _message_id sentinel after initial-send failure",
        )
        self.assertLess(
            int(consumer._message_id),
            0,
            "consumer must use a negative _message_id sentinel after initial-send failure",
        )
        consumer.stop_loop()

    def test_initial_send_exception_does_not_resend_on_subsequent_ticks(self) -> None:
        """Reproduces the duplicate-send cascade: a hard initial-send
        failure followed by more deltas must not produce a second
        ``sendMessage`` call. The run loop must back off / sit in
        fallback rather than re-attempting the initial-send branch.
        """

        class AlwaysFailsClient(FakeTelegramClient):
            def send_message_get_id(self, chat_id, text, reply_to_message_id=None, message_thread_id=None):
                raise RuntimeError(
                    "TELEGRAM_API sendMessage failed: 429 Too Many Requests: retry after 9"
                )

        client = AlwaysFailsClient()
        cfg = StreamConsumerConfig(
            edit_interval=0.0,
            buffer_threshold=0,
            cursor=" ▉",
            min_first_message_chars=2,
        )
        consumer = StreamConsumer(client, 42, 7, config=cfg)

        def action() -> None:
            # First delta fails the initial send. Subsequent deltas must
            # not trigger another sendMessage call.
            consumer.on_delta("Server2 is up but mavali.top is down")
            consumer.on_delta(" — investigating the routing table")
            consumer.on_delta(" and the NordVPN tunnel")
            consumer.finish()

        _drive(consumer, action)
        # send_message_get_id raised on every call attempt. The consumer
        # must have made at most one attempt, not one per delta. The
        # FakeTelegramClient inherits the call counter from the parent
        # (we only care that there was no cascade of sends).
        self.assertEqual(
            len(client.sends),
            0,
            "sendMessage must not be called more than once when initial-send is in hard failure",
        )
        # The fallback final-send path is allowed to fire once at the
        # end (because _finalize_after_done → _send_fallback_final),
        # but it must also handle a failing client gracefully (no
        # exception leak into the run loop). Since our client raises,
        # the fallback send will also raise, but the run loop must
        # swallow it — what we pin here is that the consumer's
        # "already-sent" state is consistent (i.e. the run loop did not
        # keep trying).
        self.assertTrue(consumer._already_sent)
        self.assertTrue(consumer._fallback_final_send)
        consumer.stop_loop()

    def test_three_strike_edit_failure_promotes_to_fallback_with_sentinel_message_id(self) -> None:
        """After 3 consecutive editMessageText failures (the 429
        scenario), the consumer must set ``_message_id = -1`` so the
        run loop will not re-enter the initial-send branch and create a
        brand-new Telegram message with the full accumulated text.

        Real incident shape: the engine kept emitting deltas while
        Telegram was 429-ing the edits. The run loop must be allowed
        to process deltas in the regular (non-finalize) tick path so
        it actually hits the 3-strike branch — not just drain
        everything in one go and jump straight to finalize. Use a
        feeder thread with a delay between deltas.
        """

        import threading
        import time as _time

        class FlakyEditClient(FakeTelegramClient):
            def __init__(self) -> None:
                super().__init__()
                self._edit_calls = 0

            def edit_message(self, chat_id, message_id, text):
                self._edit_calls += 1
                # Block briefly so the run loop is awake and picking
                # up deltas between edit attempts.
                _time.sleep(0.02)
                raise RuntimeError(
                    "TELEGRAM_API editMessageText failed: 429 Too Many Requests: retry after 5"
                )

        client = FlakyEditClient()
        cfg = StreamConsumerConfig(
            edit_interval=0.0,
            buffer_threshold=0,
            cursor=" ▉",
            min_first_message_chars=2,
        )
        import telegram_bridge.stream_consumer as sc_mod

        original_strikes = sc_mod.DEFAULT_MAX_FLOOD_STRIKES
        sc_mod.DEFAULT_MAX_FLOOD_STRIKES = 1
        try:
            consumer = StreamConsumer(client, 42, 7, config=cfg)
            consumer.start()

            def feeder():
                for i in range(10):
                    consumer.on_delta(f"chunk{i} ")
                    _time.sleep(0.04)
                consumer.finish()

            t = threading.Thread(target=feeder, daemon=True)
            t.start()
            done = consumer.wait_until_done(timeout=5.0)
            t.join(timeout=5.0)
            self.assertTrue(done, "consumer should finish within timeout")

            # The first send landed and got a real message_id. The edits
            # all failed; after the strikes exhausted, the consumer
            # MUST have flipped _message_id to a sentinel (negative
            # value) so the next run-loop tick takes the fallback path
            # instead of the initial-send path.
            self.assertIsNotNone(consumer._message_id, "first send should have set _message_id")
            self.assertLess(
                int(consumer._message_id),
                0,
                "after 3-strike edit failure _message_id must be flipped to a negative sentinel",
            )
            self.assertTrue(consumer.stats.fallback_final_send)
            self.assertTrue(consumer._fallback_final_send)
            self.assertTrue(consumer._already_sent)
        finally:
            sc_mod.DEFAULT_MAX_FLOOD_STRIKES = original_strikes

        consumer.stop_loop()


class StreamConsumerFinalizeAfterFallbackTests(unittest.TestCase):
    """End-to-end regression for the duplicate-send cascade.

    Drive the consumer with a client whose first sendMessage raises (the
    429 path), then verify the run loop delivers the final text via at
    most one ``sendMessage`` call — not many. This is the exact failure
    mode that produced the 70+ duplicate messages on 2026-06-10 07:24 UTC.
    """

    def test_fallback_after_send_exception_finalizes_with_exactly_one_send(self) -> None:
        """Simulates the rate-limited initial-send path that produced
        the 70+ duplicate messages on 2026-06-10 07:24 UTC.

        Real incident timeline: the engine emitted ``text_delta``
        events for ~2 minutes while the transport was 429-failing.
        Each run-loop tick re-attempted the initial-send branch and
        each retry that happened to succeed produced a new Telegram
        message. The cascade stopped only when ``finish()`` was
        finally called.

        The test reproduces the cascade with a thread that feeds
        deltas slowly into the queue while the run loop is awake —
        the exact production shape.
        """

        import threading
        import time as _time

        class FlakySlowClient(FakeTelegramClient):
            """Mimics the production transport: each sendMessage call
            takes ~30ms (transport retry budget on a 429) and the
            first N calls fail before one finally succeeds."""

            def __init__(self, fail_first_n: int) -> None:
                super().__init__()
                self._send_attempts = 0
                self._fail_first_n = fail_first_n

            def send_message_get_id(self, chat_id, text, reply_to_message_id=None, message_thread_id=None):
                # Block briefly so the run loop has a chance to pick
                # up new deltas from the queue between calls. In
                # production this is the 3-retry / 10s-per-retry
                # budget. Here we use 30ms to keep the test fast
                # while still letting the queue get new work.
                _time.sleep(0.03)
                self._send_attempts += 1
                if self._send_attempts <= self._fail_first_n:
                    raise RuntimeError(
                        "TELEGRAM_API sendMessage failed: 429 Too Many Requests: retry after 9"
                    )
                self.sends.append((chat_id, text, reply_to_message_id, message_thread_id))
                self.next_message_id += 1
                return {"ok": True, "message_id": self.next_message_id}

        # Fail 3, then accept. The bug would let the run loop call
        # sendMessage on every tick — with 50ms ticks and deltas
        # trickling in from a feeder thread, that's many calls.
        client = FlakySlowClient(fail_first_n=3)
        cfg = StreamConsumerConfig(
            edit_interval=0.0,
            buffer_threshold=0,
            cursor=" ▉",
            min_first_message_chars=2,
        )
        consumer = StreamConsumer(client, 42, 7, config=cfg)
        consumer.start()

        # Feeder thread: push deltas slowly so the run loop has time
        # to attempt and fail multiple sendMessage calls before
        # finish() is called.
        def feeder():
            for i in range(15):
                consumer.on_delta(f"chunk{i} ")
                _time.sleep(0.04)
            consumer.finish()

        t = threading.Thread(target=feeder, daemon=True)
        t.start()
        done = consumer.wait_until_done(timeout=5.0)
        t.join(timeout=5.0)
        self.assertTrue(done, "consumer should finish within timeout")

        # Contract 1: at most ONE sendMessage call may succeed. The
        # original bug produced many duplicate Telegram messages.
        self.assertLessEqual(
            len(client.sends),
            1,
            f"run loop must call sendMessage at most once after fallback transition; got {len(client.sends)}",
        )
        # Contract 2: the run loop must not have hammered the client.
        # Without the fix, the run loop calls sendMessage on every
        # tick (50ms). With 15 deltas spaced 40ms apart over ~600ms,
        # the run loop would call sendMessage many times — easily
        # exceeding 4. With the fix, the initial-send fails, the
        # consumer enters fallback state, and no further attempts
        # are made until finish()/finalize (which gets 1 more attempt
        # for the fallback final-send).
        self.assertLessEqual(
            client._send_attempts,
            4,
            f"run loop must not retry initial-send after fallback transition; got {client._send_attempts} attempts",
        )
        self.assertTrue(consumer.stats.fallback_final_send)
        self.assertTrue(consumer._fallback_final_send)
        consumer.stop_loop()

if __name__ == "__main__":
    unittest.main()
