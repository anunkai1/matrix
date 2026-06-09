"""Tests for Pi RPC text-delta streaming (stage 2 of the streaming rollout)."""

import io
import json
import os
import tempfile
import threading
import time
import unittest
from typing import List, Optional
from unittest import mock

from telegram_bridge.engines import pi_transport


class _StubProcess:
    """Minimal Popen stand-in that yields scripted stdout lines.

    Mirrors the surface ``read_rpc_stdout`` actually uses: ``stdout``
    (a file-like with ``readline``) and ``poll`` / ``kill``.
    """

    def __init__(self, lines: List[str]) -> None:
        self.stdout = io.StringIO("\n".join(lines) + "\n")
        self._exit_code: Optional[int] = None
        self.killed = False

    def poll(self) -> Optional[int]:
        if self.killed:
            return -9
        # After the buffered lines are consumed, ``readline`` returns
        # empty, which the consumer treats as "process finished".
        return self._exit_code

    def kill(self) -> None:
        self.killed = True
        self._exit_code = -9


def _script_lines(chunks: List[str]) -> List[str]:
    """Build a Pi RPC stdout script that emits a list of text deltas.

    The script terminates with ``agent_end`` so ``read_rpc_stdout``
    breaks out of its loop without timing out.
    """
    out: List[str] = []
    for chunk in chunks:
        out.append(
            json.dumps(
                {
                    "type": "message_update",
                    "assistantMessageEvent": {
                        "type": "text_delta",
                        "delta": chunk,
                    },
                }
            )
        )
    out.append(json.dumps({"type": "agent_end", "messages": []}))
    return out


def _drain(process, *, on_text_delta=None) -> List[str]:
    return pi_transport.read_rpc_stdout(
        process,
        cancel_event=None,
        timeout=2,
        time_module=time,
        executor_cancelled_error_cls=RuntimeError,
        on_text_delta=on_text_delta,
    )


class ReadRpcStdoutStreamingTests(unittest.TestCase):
    def test_text_delta_callback_fires_for_each_chunk(self) -> None:
        chunks = ["Hello, ", "world", "!"]
        deltas: List[str] = []
        process = _StubProcess(_script_lines(chunks))
        lines = _drain(process, on_text_delta=deltas.append)
        self.assertEqual(deltas, chunks)
        # The script also included ``agent_end`` plus the chunks; the
        # consumer should have read them all.
        self.assertGreaterEqual(len(lines), len(chunks))

    def test_no_callback_means_no_emission(self) -> None:
        chunks = ["a", "b"]
        process = _StubProcess(_script_lines(chunks))
        # No on_text_delta. Read should still succeed.
        lines = _drain(process)
        self.assertGreaterEqual(len(lines), len(chunks))

    def test_non_delta_lines_ignored(self) -> None:
        # Mix in a tool_start, an unrelated event, and only one delta.
        lines = [
            json.dumps({"type": "tool_start", "tool": "bash"}),
            json.dumps({"type": "tick"}),
            json.dumps(
                {
                    "type": "message_update",
                    "assistantMessageEvent": {
                        "type": "text_delta",
                        "delta": "real delta",
                    },
                }
            ),
            json.dumps({"type": "agent_end", "messages": []}),
        ]
        deltas: List[str] = []
        process = _StubProcess(lines)
        _drain(process, on_text_delta=deltas.append)
        self.assertEqual(deltas, ["real delta"])

    def test_callback_exception_is_swallowed(self) -> None:
        # Callback raises — the read loop must NOT break. This is
        # critical because the read loop runs in the same thread that
        # is also draining the subprocess; if it crashed, the user
        # would see a frozen preview and no agent_end ever arriving.
        def _raise(_delta: str) -> None:
            raise RuntimeError("queue full")

        process = _StubProcess(_script_lines(["chunk-1", "chunk-2"]))
        # Must not raise.
        lines = _drain(process, on_text_delta=_raise)
        # We still read all the lines.
        self.assertGreaterEqual(len(lines), 3)

    def test_malformed_lines_skipped(self) -> None:
        # Lines that aren't valid JSON or aren't message_update events
        # must not crash the consumer.
        lines = [
            "not-json",
            "",
            json.dumps({"type": "message_update", "assistantMessageEvent": {"type": "tool_call"}}),
            json.dumps(
                {
                    "type": "message_update",
                    "assistantMessageEvent": {"type": "text_delta", "delta": "ok"},
                }
            ),
            json.dumps({"type": "agent_end", "messages": []}),
        ]
        deltas: List[str] = []
        process = _StubProcess(lines)
        _drain(process, on_text_delta=deltas.append)
        self.assertEqual(deltas, ["ok"])


class StreamingConfigEngineAllowlistTests(unittest.TestCase):
    def test_default_allows_codex_and_pi(self) -> None:
        from telegram_bridge.runtime_config import StreamingConfig

        cfg = StreamingConfig(enabled=True)
        self.assertTrue(cfg.is_engine_supported("codex"))
        self.assertTrue(cfg.is_engine_supported("pi"))
        self.assertFalse(cfg.is_engine_supported("gemma"))
        self.assertFalse(cfg.is_engine_supported("venice"))
        self.assertFalse(cfg.is_engine_supported("unknown"))

    def test_disabled_blocks_all_engines(self) -> None:
        from telegram_bridge.runtime_config import StreamingConfig

        cfg = StreamingConfig(enabled=False)
        self.assertFalse(cfg.is_engine_supported("codex"))
        self.assertFalse(cfg.is_engine_supported("pi"))

    def test_custom_supported_list(self) -> None:
        from telegram_bridge.runtime_config import StreamingConfig

        cfg = StreamingConfig(enabled=True, supported_engine_plugins="venice")
        self.assertTrue(cfg.is_engine_supported("venice"))
        self.assertFalse(cfg.is_engine_supported("codex"))
        self.assertFalse(cfg.is_engine_supported("pi"))


class PiEngineAdapterOnTextDeltaTests(unittest.TestCase):
    """Smoke-check that the PiEngineAdapter passes the progress callback
    through to the transport as an ``on_text_delta`` shim.

    We don't actually run the engine subprocess here — we mock the
    transport layer and verify the wiring.
    """

    def test_run_pi_local_passes_text_delta_shim_to_transport(self) -> None:
        from telegram_bridge.engines import pi

        captured = {}

        def _fake_run_pi_local(config, prompt, session_key, cancel_event, **kwargs):
            captured["on_text_delta"] = kwargs.get("on_text_delta")
            return "fake output"

        adapter = pi.PiEngineAdapter()
        adapter._run_pi_local = _fake_run_pi_local  # type: ignore[assignment]
        # Stub out the side paths we don't exercise.
        adapter._model_supports_images = lambda *_: False  # type: ignore[assignment]
        captured_callbacks = []

        class _CB:
            def __call__(self, event):
                captured_callbacks.append(event)

        # Trigger the local-runner code path. We need pi_runner=local.
        from telegram_bridge.executor import ExecutorProgressEvent

        class _Config:
            pi_runner = "local"
            pi_provider = "ollama"
            pi_live_rpc_enabled = False
            pi_ollama_tunnel_enabled = False
            pi_ollama_tunnel_local_port = 11435
            pi_local_cwd = None
            pi_remote_cwd = "/tmp"
            pi_ssh_host = "server4-beast"

        cb = _CB()
        result = adapter.run(
            _Config(),
            prompt="hi",
            thread_id=None,
            session_key="tg:1",
            progress_callback=cb,
        )
        self.assertIsNotNone(captured.get("on_text_delta"))
        # Now fire a fake delta and ensure the callback sees a
        # text_delta progress event.
        captured["on_text_delta"]("hello ")
        captured["on_text_delta"]("world")
        self.assertEqual(len(captured_callbacks), 2)
        for event in captured_callbacks:
            self.assertIsInstance(event, ExecutorProgressEvent)
            self.assertEqual(event.kind, "text_delta")
        self.assertEqual(captured_callbacks[0].detail, "hello ")
        self.assertEqual(captured_callbacks[1].detail, "world")

    def test_callback_exception_does_not_break_text_delta_emit(self) -> None:
        from telegram_bridge.engines import pi

        captured = {}

        def _fake_run_pi_local(config, prompt, session_key, cancel_event, **kwargs):
            captured["on_text_delta"] = kwargs.get("on_text_delta")
            return "fake"

        adapter = pi.PiEngineAdapter()
        adapter._run_pi_local = _fake_run_pi_local  # type: ignore[assignment]
        adapter._model_supports_images = lambda *_: False  # type: ignore[assignment]

        class _Config:
            pi_runner = "local"
            pi_provider = "ollama"
            pi_live_rpc_enabled = False
            pi_ollama_tunnel_enabled = False
            pi_ollama_tunnel_local_port = 11435
            pi_local_cwd = None
            pi_remote_cwd = "/tmp"
            pi_ssh_host = "server4-beast"

        def _raising_cb(_event):
            raise RuntimeError("boom")

        adapter.run(
            _Config(),
            prompt="hi",
            thread_id=None,
            session_key="tg:1",
            progress_callback=_raising_cb,
        )
        # Must not raise.
        captured["on_text_delta"]("delta")
        captured["on_text_delta"]("more")


if __name__ == "__main__":
    unittest.main()
