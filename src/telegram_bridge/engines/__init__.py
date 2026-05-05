"""Pluggable engine adapters for the Telegram bridge."""

from telegram_bridge.engines._base import (
    CompletedProcessOutputMixin,
    EngineAdapter,
    ProgressCallback,
    _communicate_process_with_cancel,
    _completed_process_with_output,
    _run_blocking_with_cancel,
)
from telegram_bridge.engines.codex import CodexEngineAdapter
from telegram_bridge.engines.gemma import GemmaEngineAdapter
from telegram_bridge.engines.venice import VeniceEngineAdapter
from telegram_bridge.engines.chatgpt_web import ChatGPTWebEngineAdapter
from telegram_bridge.engines.pi import PiEngineAdapter
from telegram_bridge.engines.mavali_eth import MavaliEthEngineAdapter

__all__ = [
    "ChatGPTWebEngineAdapter",
    "CodexEngineAdapter",
    "CompletedProcessOutputMixin",
    "EngineAdapter",
    "GemmaEngineAdapter",
    "MavaliEthEngineAdapter",
    "PiEngineAdapter",
    "ProgressCallback",
    "VeniceEngineAdapter",
    "_communicate_process_with_cancel",
    "_completed_process_with_output",
    "_run_blocking_with_cancel",
]
