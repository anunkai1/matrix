"""Streaming events delivered from engine → bridge stream consumer.

The bridge progressively edits a single Telegram message with assistant
tokens instead of buffering the whole response and sending it once. To keep
the contract between the engine and the consumer explicit, this module
defines a small frozen-dataclass vocabulary that mirrors the Hermes-agent
``stream_events.py`` (GatewayStreamConsumer seam) but is trimmed to what
the Telegram bridge needs in stage 1 (edit-in-place, no native draft
transport yet).

Design constraints:
  * Events describe transport, never context. Nothing here is persisted to
    conversation history; the engine owns the final assistant text.
  * Events are constructed on the engine worker thread and pushed into the
    consumer's ``queue.Queue`` from the same thread; the consumer's async
    ``run()`` task is the only consumer.
  * The vocabulary is intentionally small: ``TextDelta`` covers the
    streaming case (the Codex app-server emits ``item/agentMessage/delta``
    for every token chunk); ``MessageStop`` and ``Commentary`` cover the
    turn boundary and interim-pre-tool-call text cases. Stage 2 will add
    a Pi ``message_update``/``text_delta`` producer that reuses the same
    ``TextDelta`` event.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Union


@dataclass(frozen=True)
class TextDelta:
    """An incremental chunk of assistant text.

    ``text`` is the raw token delta the model produced. The consumer
    accumulates chunks and progressively renders them via Telegram
    ``editMessageText``. ``turn_id`` correlates deltas to a single
    assistant turn so the consumer can reject deltas from a turn it is
    no longer serving (mirrors the run-generation guard the rest of the
    bridge uses for follow-up steering).
    """

    text: str
    turn_id: str = ""


@dataclass(frozen=True)
class MessageStop:
    """The current assistant message is complete.

    Fired when the engine signals turn completion (Codex app-server
    ``turn/completed``). ``final`` is always True for the bridge today;
    the field is kept for parity with Hermes in case the bridge later
    needs interim segment stops at tool boundaries.
    """

    final: bool = True
    turn_id: str = ""


@dataclass(frozen=True)
class Commentary:
    """A complete interim assistant message emitted between tool iterations.

    Example: the model says "I'll inspect the repo first." before issuing
    a tool call. Unlike a ``TextDelta`` this is already-complete text;
    the consumer renders it as its own message so it reads as a distinct
    beat rather than getting merged into the streaming bubble.
    """

    text: str
    turn_id: str = ""


StreamEvent = Union[TextDelta, MessageStop, Commentary]

__all__ = ["TextDelta", "MessageStop", "Commentary", "StreamEvent"]
