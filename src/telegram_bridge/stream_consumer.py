"""Stream consumer — progressively edits one Telegram message with assistant tokens.

The engine (Codex app-server, future Pi RPC) fires ``text_delta`` progress
events synchronously from its worker thread. ``StreamConsumer`` accepts
those deltas via ``on_delta`` and routes them to an async ``run()`` task
that:

  1. Buffers text from the queue (``queue.Queue``, sync → async handoff).
  2. Throttles ``editMessageText`` calls so we do not exceed Telegram
     flood-control limits (defaults: 0.8s edit interval, 24-char buffer
     threshold — same starting points as Hermes's
     ``GatewayStreamConsumer``).
  3. On completion, drops the streaming cursor and delivers the final
     visible text. If edits fail mid-stream, the consumer falls back to
     a single fresh-send of the missing tail so the user always gets the
     full answer.

The consumer is bound to one Telegram chat + thread for the lifetime of
one assistant turn. It is constructed by the bridge request worker
inside ``process_prompt_request`` and torn down in the same scope after
``finalize_prompt_success`` runs.

Async / sync bridging:

  The bridge request worker is a sync function (it runs in a thread
  pool). To keep the consumer implementation in one place while
  coexisting with the sync worker, ``StreamConsumer`` owns a private
  ``asyncio`` event loop running in a daemon thread. ``start()`` is
  sync (it boots the loop + schedules ``run()``); ``on_delta``,
  ``on_commentary``, ``on_segment_break``, and ``finish()`` are all
  sync and thread-safe (they push into ``queue.Queue``); and
  ``wait_until_done()`` is sync (it blocks on a ``threading.Event``).

Design / safety contract (mirrors Hermes's ``stream_consumer.py``):

  * Sync ``on_delta`` only enqueues — never blocks on the async loop. The
    queue is unbounded by design; if the engine produces deltas faster
    than we can render, they accumulate in memory but do not block the
    engine. In practice, Telegram edit latency is the bottleneck and
    matches the model's streaming rate, so the queue stays shallow.
  * On any failure the consumer never raises into the engine. Errors are
    logged + counted and the consumer degrades gracefully (fallback
    final-send path).
  * The consumer reports ``final_response_sent`` so the bridge can skip
    the normal ``send_executor_output`` final-send path when the consumer
    has already delivered the visible answer. This is the only contract
    that lets the consumer coexist with the existing
    ``deliver_output_and_emit_success`` flow without double-sending.
  * Cancellation is cooperative: the bridge sets ``stop_event`` and
    calls ``finish()``; the consumer drains the queue, attempts a
    best-effort final edit, and reports what it actually delivered.
"""

from __future__ import annotations

import asyncio
import logging
import queue
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

logger = logging.getLogger("telegram_bridge.stream_consumer")

# Stream-completion sentinel pushed by finish().
_DONE = object()

# Tool-boundary sentinel — finalize current message and start fresh.
_NEW_SEGMENT = object()

# Tag used in logs / events for the consumer's work.
CONSUMER_TAG = "stream_consumer"

# Default knobs — match Hermes's GatewayStreamConsumer starting points.
DEFAULT_EDIT_INTERVAL_SECONDS = 0.8
DEFAULT_BUFFER_THRESHOLD_CHARS = 24
DEFAULT_CURSOR = " ▉"
DEFAULT_MAX_MESSAGE_LENGTH = 4096
DEFAULT_MAX_FLOOD_STRIKES = 3
DEFAULT_EDIT_BACKOFF_MAX_SECONDS = 10.0
DEFAULT_FALLBACK_FLOOD_RETRY_SECONDS = 3.0
MIN_NEW_MSG_CHARS = 4
QUEUE_POLL_INTERVAL_SECONDS = 0.05


@dataclass
class StreamConsumerConfig:
    """Runtime config for a single stream consumer instance."""

    edit_interval: float = DEFAULT_EDIT_INTERVAL_SECONDS
    buffer_threshold: int = DEFAULT_BUFFER_THRESHOLD_CHARS
    cursor: str = DEFAULT_CURSOR
    max_message_length: int = DEFAULT_MAX_MESSAGE_LENGTH
    # When True, send the first partial message only when the visible
    # accumulated text reaches ``min_first_message_chars`` (default 4).
    # Prevents tiny token deltas from creating standalone "X ▉" messages
    # that risk a permanently visible cursor if the next edit fails.
    min_first_message_chars: int = MIN_NEW_MSG_CHARS

    @classmethod
    def from_config(cls, source: Any) -> "StreamConsumerConfig":
        """Build a config from a runtime ``Config`` or any object with
        the matching attribute names. Returns defaults if ``source`` is
        None or does not expose a ``streaming`` group.
        """
        if source is None:
            return cls()
        streaming = getattr(source, "streaming", None)
        if streaming is None:
            return cls()
        return cls(
            edit_interval=float(getattr(streaming, "edit_interval", DEFAULT_EDIT_INTERVAL_SECONDS) or DEFAULT_EDIT_INTERVAL_SECONDS),
            buffer_threshold=int(getattr(streaming, "buffer_threshold", DEFAULT_BUFFER_THRESHOLD_CHARS) or DEFAULT_BUFFER_THRESHOLD_CHARS),
            cursor=str(getattr(streaming, "cursor", DEFAULT_CURSOR) or DEFAULT_CURSOR),
            max_message_length=int(getattr(streaming, "max_message_length", DEFAULT_MAX_MESSAGE_LENGTH) or DEFAULT_MAX_MESSAGE_LENGTH),
            min_first_message_chars=int(getattr(streaming, "min_first_message_chars", MIN_NEW_MSG_CHARS) or MIN_NEW_MSG_CHARS),
        )


@dataclass
class StreamConsumerStats:
    """Per-consumer counters surfaced via ``stats()`` and the structured event."""

    edit_attempts: int = 0
    edit_successes: int = 0
    edit_failures_other: int = 0
    flood_strikes: int = 0
    fallback_final_send: bool = False
    final_response_sent: bool = False
    final_content_delivered: bool = False


# Optional media-tag / directive cleaner — strip out ``MEDIA:`` and
# ``[[audio_as_voice]]`` directives the way the existing
# ``response_delivery`` path strips them, so the user never sees raw
# directive tokens in the streamed preview.
_MEDIA_TAG_RE = re.compile(r"\bMEDIA:[^\s]*\.(?:jpg|jpeg|png|webp|gif|ogg|oga|opus|mp3|m4a|aac|wav|flac)(?:\s|$)", re.IGNORECASE)
_AUDIO_AS_VOICE_TAG_RE = re.compile(r"\[\[\s*audio_as_voice\s*\]\]", re.IGNORECASE)


def _clean_for_display(text: str) -> str:
    """Strip media directives and collapse whitespace.

    The streaming path delivers raw text chunks that may include
    ``MEDIA:<path>`` and ``[[audio_as_voice]]`` directives meant for the
    platform adapter's post-processing. We hide the directives from the
    user; actual media files are delivered separately by the bridge
    after the stream finishes.
    """
    if "MEDIA:" not in text and "[[audio_as_voice]]" not in text:
        return text
    cleaned = _AUDIO_AS_VOICE_TAG_RE.sub("", text)
    cleaned = _MEDIA_TAG_RE.sub("", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.rstrip()


# Type aliases for adapter calls — kept loose because the bridge uses
# duck-typed client objects.
EditCallable = Callable[..., Any]
SendCallable = Callable[..., Any]
DeleteCallable = Callable[..., Any]


class StreamConsumer:
    """Async consumer that progressively edits one Telegram message.

    The consumer is constructed and started from the bridge request
    worker (see ``prompt_execution``). Lifecycle:

      consumer = StreamConsumer(client, chat_id, message_thread_id, config)
      asyncio.create_task(consumer.run())
      # engine fires deltas via consumer.on_delta(text)
      consumer.finish()  # signal turn end
      await consumer.wait_until_done()  # join the run() task
      if consumer.stats.final_response_sent:
          # consumer already delivered the answer — skip normal final-send
          ...
    """

    def __init__(
        self,
        client: Any,
        chat_id: int,
        message_thread_id: Optional[int],
        config: Optional[StreamConsumerConfig] = None,
        initial_reply_to_message_id: Optional[int] = None,
        on_first_send: Optional[Callable[[], None]] = None,
    ) -> None:
        self.client = client
        self.chat_id = int(chat_id)
        self.message_thread_id = message_thread_id
        self.cfg = config or StreamConsumerConfig()
        self.initial_reply_to_message_id = initial_reply_to_message_id
        self._on_first_send = on_first_send
        self._queue: "queue.Queue[Any]" = queue.Queue()
        self._accumulated = ""
        self._message_id: Optional[int] = None
        self._already_sent = False
        self._edit_supported = bool(getattr(client, "supports_message_edits", True))
        self._last_edit_time = 0.0
        self._last_sent_text = ""
        self._current_edit_interval = self.cfg.edit_interval
        self._flood_strikes = 0
        self._fallback_final_send = False
        self._fallback_prefix = ""
        self._final_response_sent = False
        self._final_content_delivered = False
        # Public stats — read by tests and the structured event emitter.
        self.stats = StreamConsumerStats()
        # Per-stream stop event so external callers can interrupt
        # (currently unused, reserved for future cancellation paths).
        self._stop_event = threading.Event()
        # Track segments so consecutive edits can detect "new" text
        # segments at tool boundaries.
        self._segment_started = False
        # Private event loop + thread that drive the async ``run()``.
        # The bridge request worker is sync, so the consumer owns its
        # own loop to keep the public API thread-safe. ``start()`` boots
        # the loop; ``wait_until_done()`` blocks on a threading.Event.
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._loop_thread: Optional[threading.Thread] = None
        self._loop_ready = threading.Event()
        self._run_task: Optional[asyncio.Future[Any]] = None
        self._finished_event = threading.Event()

    # ── sync API (called from the engine worker thread) ───────────────

    def on_delta(self, text: str) -> None:
        """Thread-safe: enqueue an incremental text delta from the model.

        Empty / whitespace-only deltas are ignored. ``text=None`` is
        treated as a tool-boundary signal (finalize current segment).
        """
        if text is None:
            self._queue.put(_NEW_SEGMENT)
            return
        if not text:
            return
        self._queue.put(text)

    def on_commentary(self, text: str) -> None:
        """Queue a complete interim assistant message between tool calls.

        The consumer renders commentary as its own message, not merged
        into the streaming bubble, so the user sees it as a distinct
        beat.
        """
        if text:
            self._queue.put(("COMMENTARY", text))

    def on_segment_break(self) -> None:
        """Finalize the current segment and start a fresh message on the
        next text delta. Used at tool boundaries so subsequent text
        appears below any tool-progress messages the gateway rendered in
        between.
        """
        self._queue.put(_NEW_SEGMENT)

    def finish(self) -> None:
        """Signal the stream is complete. The run() task will drain the
        queue, deliver the final edit, and return.
        """
        self._queue.put(_DONE)

    # ── sync facade (called from the bridge request worker) ──────────

    def start(self) -> None:
        """Boot the consumer's private event loop and schedule ``run()``.

        Sync; safe to call from the bridge request worker. Returns once
        the loop is up and the run task is scheduled. The caller can
        immediately start firing ``on_delta`` / ``on_commentary`` /
        ``finish`` events.
        """
        if self._loop_thread is not None:
            return

        def _loop_runner() -> None:
            self._loop = asyncio.new_event_loop()
            try:
                asyncio.set_event_loop(self._loop)
                self._loop_ready.set()
                self._loop.run_forever()
            finally:
                try:
                    self._loop.close()
                except Exception:
                    pass
                self._loop = None

        self._loop_thread = threading.Thread(
            target=_loop_runner,
            name=f"stream-consumer-{self.chat_id}",
            daemon=True,
        )
        self._loop_thread.start()
        self._loop_ready.wait(timeout=2.0)

        if self._loop is None:
            raise RuntimeError("Stream consumer event loop failed to start")

        # Schedule the async ``run()`` coroutine on the private loop.
        self._run_task = asyncio.run_coroutine_threadsafe(self._run(), self._loop)

    def wait_until_done(self, timeout: float = 5.0) -> bool:
        """Block until the run loop finishes. Returns True if completed
        within the timeout.
        """
        # Fast path: ``finished_event`` is set in the run() finally
        # block via ``call_soon_threadsafe`` so the sync caller can
        # block on a threading primitive.
        if self._finished_event.wait(timeout=timeout):
            # Also wait for the run task to be marked done on the
            # event loop. ``call_soon_threadsafe`` queues the result
            # future to the loop, but the run task itself runs on the
            # loop so this is mostly defensive.
            if self._run_task is not None:
                try:
                    self._run_task.result(timeout=0.5)
                except Exception:
                    pass
            return True
        logger.warning(
            "Stream consumer did not finish within %ss — final state may be incomplete",
            timeout,
        )
        return False

    def stop_loop(self, timeout: float = 2.0) -> None:
        """Tear down the private event loop and thread.

        Called from the request worker's finally block so the daemon
        thread is reaped even on unhandled exceptions.
        """
        if self._loop is None:
            return
        # If the run task is still pending (e.g. test teardown), cancel
        # it so the event loop has nothing to do before we stop it.
        if self._run_task is not None and not self._run_task.done():
            try:
                self._loop.call_soon_threadsafe(self._run_task.cancel)
            except Exception:
                pass
        try:
            # Stop the loop after the run() task finishes (it should
            # already have returned by the time we get here because
            # the request worker has already called ``finish()`` and
            # ``wait_until_done()``). ``call_soon_threadsafe`` is
            # safe across threads.
            self._loop.call_soon_threadsafe(self._loop.stop)
        except Exception:
            pass
        if self._loop_thread is not None:
            self._loop_thread.join(timeout=timeout)

    # ── async ``run()`` coroutine (runs on the private loop) ──────

    async def _run(self) -> None:
        """Drain the queue, throttle edits, deliver the final response.

        Never raises — all exceptions are logged and swallowed so the
        engine can keep running. The consumer's final state is captured
        in ``self.stats`` and the public ``final_response_sent`` flag.

        The sync ``start()`` facade schedules this coroutine on the
        private loop; ``wait_until_done()`` blocks on
        ``_finished_event`` and ``stop_loop()`` cancels the run task
        on teardown.
        """
        # Use the adapter's UTF-16 length for Telegram so overflow
        # detection matches what the platform actually enforces.
        len_fn = getattr(self.client, "message_len_fn", None) or len
        safe_limit = max(500, self.cfg.max_message_length - len_fn(self.cfg.cursor) - 100)
        try:
            await self._run_loop(safe_limit, len_fn)
        except asyncio.CancelledError:
            # Best-effort final edit on cancellation.
            best_effort_ok = False
            if self._accumulated and self._message_id is not None and self._edit_supported:
                try:
                    best_effort_ok = bool(
                        await self._edit_message(self._message_id, self._accumulated)
                    )
                except Exception:
                    logger.debug("Stream consumer: best-effort edit on cancel failed", exc_info=True)
            if best_effort_ok and not self._final_response_sent:
                self._final_response_sent = True
                self._final_content_delivered = True
                self.stats.final_response_sent = True
                self.stats.final_content_delivered = True
        except Exception as exc:  # presentation must never break the agent loop
            logger.error("Stream consumer: unhandled error: %s", exc_info=True)
        finally:
            # Signal completion regardless of how _run() returned so
            # the sync ``wait_until_done`` can wake up.
            self._finished_event.set()

    async def _run_loop(self, safe_limit: int, len_fn: Any) -> None:
        """Inner drain loop. Pulled out so it can be unit-tested with
        a pre-set ``safe_limit`` / ``len_fn``.
        """
        while True:
            got_done = False
            got_segment_break = False
            commentary_text: Optional[str] = None
            # Drain all immediately-available queue items.
            while True:
                try:
                    item = self._queue.get_nowait()
                except queue.Empty:
                    break
                if item is _DONE:
                    got_done = True
                    break
                if item is _NEW_SEGMENT:
                    got_segment_break = True
                    continue
                if isinstance(item, tuple) and len(item) == 2 and item[0] == "COMMENTARY":
                    commentary_text = item[1]
                    continue
                if isinstance(item, str):
                    cleaned = _clean_for_display(item)
                    if cleaned:
                        self._accumulated += cleaned

            if got_done or got_segment_break or commentary_text is not None:
                should_edit = True
            else:
                now = time.monotonic()
                elapsed = now - self._last_edit_time
                should_edit = (
                    elapsed >= self._current_edit_interval
                    and self._accumulated
                ) or len(self._accumulated) >= self.cfg.buffer_threshold

            if should_edit and self._accumulated:
                # If we've entered fallback state (no editable id,
                # either the initial send failed or 3 edit strikes
                # exhausted), do NOT call _send_or_edit from the
                # regular drain path. Otherwise the run loop will
                # re-send the accumulated text on every tick and
                # create a cascade of duplicate Telegram messages —
                # the 2026-06-10 07:24 UTC incident. The fallback
                # final-send is delivered by ``_finalize_after_done``
                # when ``finish()`` is called.
                if self._fallback_final_send or (self._message_id is not None and self._message_id < 0):
                    pass
                else:
                    # Overflow: accumulated text exceeds the platform
                    # limit. Split into chunks, send first as a new
                    # message, queue the rest as a continuation.
                    if (
                        len_fn(self._accumulated) > safe_limit
                        and self._message_id is None
                    ):
                        await self._send_overflow_chunks(safe_limit, len_fn)
                        self._last_edit_time = time.monotonic()
                        if got_done:
                            return
                        if got_segment_break:
                            self._reset_segment_state()
                        continue
                    if await self._send_or_edit(
                        self._accumulated,
                        finalize=got_done or got_segment_break,
                    ):
                        self._last_edit_time = time.monotonic()

            # Commentary fires before the done/segment break so the
            # user sees the interim complete text in the right order:
            # streaming bubble → commentary message (if any) → final
            # streaming bubble (or tool bubble).
            if commentary_text is not None:
                await self._send_commentary(commentary_text)
                self._last_edit_time = time.monotonic()

            if got_done:
                await self._finalize_after_done()
                return

            if got_segment_break:
                self._reset_segment_state()

            await asyncio.sleep(QUEUE_POLL_INTERVAL_SECONDS)

    # ── internal helpers ──────────────────────────────────────────────

    def _reset_segment_state(self) -> None:
        """Clear per-segment state at a tool boundary / commentary send.

        The next text delta will create a fresh message below any
        tool-progress bubbles.
        """
        self._accumulated = ""
        self._message_id = None
        self._last_sent_text = ""
        self._final_response_sent = False
        self._final_content_delivered = False
        self._segment_started = False
        self._fallback_final_send = False
        self._fallback_prefix = ""

    async def _send_or_edit(self, text: str, *, finalize: bool = False) -> bool:
        """Send the first message or edit the existing one.

        Returns True if Telegram acknowledged the send/edit. Applies the
        cursor for non-final updates, strips the cursor for the final
        edit. Handles flood-control backoff and the small-message guard
        that prevents standalone "X ▉" messages.
        """
        text = _clean_for_display(text)
        visible = text
        if self.cfg.cursor:
            visible = visible.replace(self.cfg.cursor, "")
        visible_stripped = visible.strip()
        if not visible_stripped:
            return True
        if not text.strip():
            return True
        if (
            self._message_id is None
            and self.cfg.cursor
            and self.cfg.cursor in text
            and len(visible_stripped) < self.cfg.min_first_message_chars
        ):
            # Too short for a standalone first message; accumulate more.
            return True

        if self._message_id is not None and self._edit_supported:
            if text == self._last_sent_text:
                return True
            self.stats.edit_attempts += 1
            ok = await self._edit_message(self._message_id, text)
            if ok:
                self._last_sent_text = text
                self.stats.edit_successes += 1
                self._flood_strikes = 0
                return True
            # Edit failed — distinguish flood-control from other errors.
            # We don't have the full adapter error envelope here, so
            # treat all edit failures as "potential flood" and apply
            # adaptive backoff; if strikes exhaust, switch to fallback.
            self.stats.edit_failures_other += 1
            self._flood_strikes += 1
            self._current_edit_interval = min(
                self._current_edit_interval * 2,
                DEFAULT_EDIT_BACKOFF_MAX_SECONDS,
            )
            logger.debug(
                "Stream consumer: edit failed (strike %d/%d), backoff → %.1fs",
                self._flood_strikes,
                DEFAULT_MAX_FLOOD_STRIKES,
                self._current_edit_interval,
            )
            if self._flood_strikes >= DEFAULT_MAX_FLOOD_STRIKES:
                self._fallback_prefix = self._visible_prefix()
                self._fallback_final_send = True
                self._edit_supported = False
                self._already_sent = True
                # Flip _message_id to a negative sentinel so the next
                # run-loop tick takes the fallback path (sees
                # ``self._message_id in (None, -1)``) instead of the
                # initial-send path. Without this, the run loop would
                # re-enter the initial-send branch on every tick and
                # create a new Telegram message with the full
                # accumulated text — the duplicate-send cascade
                # observed on 2026-06-10 07:24 UTC.
                if self._message_id is not None and self._message_id > 0:
                    self._message_id = -1
                self.stats.fallback_final_send = True
                # Best-effort: strip the cursor from the last visible
                # message so the user doesn't see a stuck ▉.
                await self._try_strip_cursor()
                return False
            return False

        # No message_id yet → send the first message.
        try:
            result = self._send_message(text)
        except Exception as exc:
            # Hard failure (e.g. transport's 3-retry budget exhausted
            # on a 429). Transition atomically into fallback state so
            # the run loop does not re-enter this branch on every
            # tick and create a cascade of duplicate Telegram
            # messages. Mirrors the successful-but-no-id branch below
            # — both paths must end in the same fallback sentinel.
            logger.error("Stream consumer: initial send failed: %s", exc)
            self._message_id = -1
            self._fallback_prefix = text
            self._fallback_final_send = True
            self._already_sent = True
            self._edit_supported = False
            self.stats.fallback_final_send = True
            return False
        if not result:
            # Transport accepted the call but returned a falsy
            # response (e.g. an unknown adapter shape). Transition
            # into fallback state for the same reason as the
            # exception handler above: the run loop must not re-enter
            # this branch on every tick.
            self._message_id = -1
            self._fallback_prefix = text
            self._fallback_final_send = True
            self._already_sent = True
            self._edit_supported = False
            self.stats.fallback_final_send = True
            return False
        # Some adapters return the message_id; some don't. We track
        # both cases — without a message_id we still consider delivery
        # successful and let the final-send fallback path take over.
        new_id = self._extract_message_id(result)
        if new_id is not None:
            self._message_id = int(new_id)
        self._already_sent = True
        self._last_sent_text = text
        self._segment_started = True
        if new_id is None:
            # Platform accepted the send but didn't return an editable
            # id (e.g. webhook delivery). Switch to fallback mode so
            # subsequent edits don't re-enter the first-send path.
            self._message_id = -1
            self._fallback_prefix = text
            self._fallback_final_send = True
            self._edit_supported = False
            self.stats.fallback_final_send = True
        if self._on_first_send is not None:
            try:
                self._on_first_send()
            except Exception:
                logger.debug("Stream consumer: on_first_send callback raised", exc_info=True)
        return True

    async def _send_overflow_chunks(self, safe_limit: int, len_fn: Any) -> None:
        """Split an oversized accumulated buffer into multiple sends.

        First chunk is sent as a new message; remaining chunks are
        appended as new messages in the same thread so the user sees a
        continuous block of text rather than a single truncated wall.
        """
        remaining = self._accumulated
        if not remaining:
            return
        # Naive split: find the last newline within the budget so we
        # don't break mid-word. Fall back to a hard cut.
        first_chunk_len = safe_limit
        split_at = remaining.rfind("\n", 0, safe_limit)
        if split_at < safe_limit // 2:
            split_at = safe_limit
        first_chunk = remaining[:split_at]
        self._accumulated = remaining[split_at:].lstrip("\n")
        # Drop the cursor on the first chunk — overflow sends are full
        # chunks, not partial previews.
        ok = await self._send_or_edit(first_chunk, finalize=False)
        if not ok:
            return
        # Reset the message_id tracker so subsequent overflow chunks
        # open fresh messages, and we stop trying to edit the one we
        # just sent.
        self._message_id = None
        # Continue splitting in case the overflow is still too long.
        while len_fn(self._accumulated) > safe_limit:
            split_at = self._accumulated.rfind("\n", 0, safe_limit)
            if split_at < safe_limit // 2:
                split_at = safe_limit
            chunk = self._accumulated[:split_at]
            self._accumulated = self._accumulated[split_at:].lstrip("\n")
            await self._send_or_edit(chunk, finalize=False)
            self._message_id = None
        if self._accumulated:
            # The tail fits within the limit but needs a fresh message.
            await self._send_or_edit(self._accumulated, finalize=False)
            self._message_id = None

    async def _finalize_after_done(self) -> None:
        """Deliver the final visible answer.

        Three exit paths:
        1. Mid-stream edits already delivered the final text → mark
           final_response_sent and return.
        2. Fallback mode is active (flood / no editable id) → send the
           missing tail as a single fresh message.
        3. We still have a real message_id and a final accumulated text
           → do one last edit (no cursor) and mark delivered.
        """
        if not self._accumulated:
            # Nothing more to deliver; the prior edit was the final one.
            self._final_response_sent = self._already_sent
            self._final_content_delivered = self._already_sent
            self.stats.final_response_sent = self._final_response_sent
            self.stats.final_content_delivered = self._final_content_delivered
            return

        if self._fallback_final_send or self._message_id in (None, -1):
            await self._send_fallback_final(self._accumulated)
            return

        if self._message_id is not None and self._edit_supported:
            # Final edit: strip the cursor by re-sending the bare text.
            self.stats.edit_attempts += 1
            ok = await self._edit_message(self._message_id, self._accumulated)
            if ok:
                self._last_sent_text = self._accumulated
                self.stats.edit_successes += 1
                self._final_response_sent = True
                self._final_content_delivered = True
                self.stats.final_response_sent = True
                self.stats.final_content_delivered = True
                return
            # Final edit failed — fall back to a fresh send of the full
            # accumulated text so the user still gets the answer.
            self._already_sent = True
            await self._send_fallback_final(self._accumulated)
            return

        # No editable id and no fallback yet — last resort.
        await self._send_fallback_final(self._accumulated)

    async def _send_fallback_final(self, text: str) -> None:
        """Send the final tail as a fresh message after streaming edits
        stopped working. The text is the full accumulated answer; the
        consumer will not double-send if the prior mid-stream edits
        already covered everything visible.
        """
        final_text = _clean_for_display(text)
        if not final_text.strip():
            return
        # Always mark the fallback flag so observability / tests can
        # see that we left the edit-in-place path. The final-response
        # flags are set below only if Telegram actually accepted the
        # send.
        self._fallback_final_send = True
        self.stats.fallback_final_send = True
        try:
            result = self._send_message(final_text)
        except Exception as exc:
            logger.error("Stream consumer: fallback final-send failed: %s", exc)
            return
        if result:
            self._final_response_sent = True
            self._final_content_delivered = True
            self.stats.final_response_sent = True
            self.stats.final_content_delivered = True
            self._already_sent = True

    async def _send_commentary(self, text: str) -> bool:
        """Send a complete interim assistant commentary message.

        Commentary is sent as its own message, not merged into the
        streaming bubble, so it reads as a distinct beat. The consumer
        does NOT mark ``final_response_sent`` for commentary because the
        real answer is still in flight.
        """
        cleaned = _clean_for_display(text)
        if not cleaned.strip():
            return False
        try:
            result = self._send_message(cleaned)
        except Exception as exc:
            logger.error("Stream consumer: commentary send failed: %s", exc)
            return False
        return bool(result)

    async def _try_strip_cursor(self) -> None:
        """Best-effort edit to remove the cursor from the last visible
        message when fallback mode is entered. Avoids a stuck ▉ if the
        follow-up edits never succeed.
        """
        if not self._message_id or self._message_id <= 0:
            return
        prefix = self._visible_prefix()
        if not prefix or not prefix.strip():
            return
        try:
            await self._edit_message(self._message_id, prefix)
            self._last_sent_text = prefix
        except Exception:
            pass  # best-effort

    def _visible_prefix(self) -> str:
        """Return the visible text already shown in the streamed message,
        stripping a trailing cursor.
        """
        prefix = self._last_sent_text or ""
        if self.cfg.cursor and prefix.endswith(self.cfg.cursor):
            prefix = prefix[: -len(self.cfg.cursor)]
        return _clean_for_display(prefix)

    # ── thin adapter shims ────────────────────────────────────────────

    def _send_message(self, text: str) -> Any:
        """Send a new Telegram message. Returns the adapter's response
        (a dict with ``ok`` / ``message_id`` for the urllib-based
        transport). Returns truthy on success.
        """
        return self.client.send_message_get_id(
            self.chat_id,
            text,
            reply_to_message_id=self.initial_reply_to_message_id,
            message_thread_id=self.message_thread_id,
        )

    async def _edit_message(self, message_id: int, text: str) -> bool:
        """Edit an existing Telegram message. Returns True on success.

        The transport's ``edit_message`` is synchronous (urllib under
        the hood) and raises ``RuntimeError`` on Telegram API errors.
        We treat ``"message is not modified"`` as a no-op success (the
        visible state is already correct) and any other failure as a
        hard failure.
        """
        try:
            self.client.edit_message(self.chat_id, int(message_id), text)
            return True
        except RuntimeError as exc:
            msg = str(exc).lower()
            if "message is not modified" in msg or "message is not modified" in msg:
                return True
            logger.debug("Stream consumer: edit_message failed: %s", exc)
            return False
        except Exception as exc:
            logger.debug("Stream consumer: edit_message unexpected error: %s", exc)
            return False

    @staticmethod
    def _extract_message_id(send_result: Any) -> Optional[int]:
        """Pull ``message_id`` out of the transport's return value.

        The urllib-based transport returns a dict with ``message_id``
        when Telegram returns one. Returns None for webhook-style
        adapters that don't expose an editable id.
        """
        if send_result is None:
            return None
        if isinstance(send_result, dict):
            value = send_result.get("message_id")
            if isinstance(value, int):
                return value
            if isinstance(value, str) and value.lstrip("-").isdigit():
                return int(value)
        msg_id = getattr(send_result, "message_id", None)
        if isinstance(msg_id, int):
            return msg_id
        if isinstance(msg_id, str) and msg_id.lstrip("-").isdigit():
            return int(msg_id)
        return None

    @property
    def final_response_sent(self) -> bool:
        return self._final_response_sent

    @property
    def final_content_delivered(self) -> bool:
        return self._final_content_delivered

    @property
    def already_sent(self) -> bool:
        return self._already_sent

    @property
    def message_id(self) -> Optional[int]:
        return self._message_id


__all__ = [
    "StreamConsumer",
    "StreamConsumerConfig",
    "StreamConsumerStats",
    "DEFAULT_EDIT_INTERVAL_SECONDS",
    "DEFAULT_BUFFER_THRESHOLD_CHARS",
    "DEFAULT_CURSOR",
    "DEFAULT_MAX_MESSAGE_LENGTH",
]
