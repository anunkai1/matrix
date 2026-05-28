import sys
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from telegram_bridge.executor import (
    ExecutorCancelledError,
    cached_executor_result_output,
    cached_executor_result_steered_follow_up_count,
)
from telegram_bridge import pi_live_rpc


class _FakePiStdin:
    def __init__(self, process) -> None:
        self._process = process
        self.closed = False

    def write(self, value: str) -> None:
        if self.closed:
            raise ValueError("stdin closed")
        self._process.handle_prompt(value)

    def flush(self) -> None:
        if self.closed:
            raise ValueError("stdin closed")

    def close(self) -> None:
        self.closed = True


class _FakePiStdout:
    def __init__(self, process) -> None:
        self._process = process
        self.closed = False

    def readline(self) -> str:
        return self._process.readline()

    def close(self) -> None:
        self.closed = True


class _FakePiStderr:
    def __iter__(self):
        return self

    def __next__(self):
        raise StopIteration

    def close(self) -> None:
        return None


class _FakePiProcess:
    def __init__(self, responses, *, release_first_response: threading.Event | None = None) -> None:
        self.stdin = _FakePiStdin(self)
        self.stdout = _FakePiStdout(self)
        self.stderr = _FakePiStderr()
        self.args = []
        self._responses = list(responses)
        self._release_first_response = release_first_response
        self._prompt_count = 0
        self._current_lines = []
        self._pending_response_text = ""
        self._lock = threading.Lock()
        self._killed = False
        self.prompt_payloads = []

    def handle_prompt(self, value: str) -> None:
        with self._lock:
            self.prompt_payloads.append(value.strip())
            response_text = self._responses.pop(0)
            self._pending_response_text = response_text
            self._prompt_count += 1
            if self._prompt_count == 1 and self._release_first_response is not None:
                self._current_lines = []
            else:
                self._current_lines = [self._agent_end_line(response_text)]

    def readline(self) -> str:
        with self._lock:
            if self._killed:
                return ""
            if self._prompt_count == 1 and self._release_first_response is not None and not self._release_first_response.is_set():
                return ""
            if self._prompt_count == 1 and self._release_first_response is not None and not self._current_lines:
                self._current_lines = [self._agent_end_line(self._pending_response_text)]
                self._pending_response_text = ""
            if self._current_lines:
                return self._current_lines.pop(0)
            return ""

    def poll(self):
        return -9 if self._killed else None

    def wait(self, timeout=None):
        del timeout
        return -9 if self._killed else 0

    def kill(self) -> None:
        self._killed = True

    @staticmethod
    def _agent_end_line(text: str) -> str:
        return (
            '{"type":"agent_end","messages":[{"role":"assistant","content":'
            f'[{{"type":"text","text":"{text}"}}]}}]}}\n'
        )


class PiLiveRpcTests(unittest.TestCase):
    def setUp(self) -> None:
        with pi_live_rpc._SESSION_REGISTRY_LOCK:
            for session in pi_live_rpc._SESSION_REGISTRY.values():
                session.close()
            pi_live_rpc._SESSION_REGISTRY.clear()

    def tearDown(self) -> None:
        self.setUp()

    def _config(self, **overrides):
        values = {
            "pi_live_rpc_enabled": True,
            "pi_live_rpc_idle_timeout_seconds": 900,
            "pi_provider": "deepseek",
            "pi_model": "deepseek-v4-pro",
            "pi_runner": "local",
            "pi_bin": "pi",
            "pi_ssh_host": "server4-test",
            "pi_local_cwd": "/runtime/root",
            "pi_remote_cwd": "/tmp",
            "pi_session_mode": "telegram_scope",
            "pi_session_dir": "/runtime/pi-sessions",
            "pi_session_max_bytes": 1024 * 1024,
            "pi_session_max_age_seconds": 3600,
            "pi_session_archive_retention_seconds": 7200,
            "pi_session_archive_dir": "",
            "pi_tools_mode": "none",
            "pi_tools_allowlist": "",
            "pi_extra_args": "",
            "pi_ollama_tunnel_enabled": False,
            "pi_ollama_tunnel_local_port": 19091,
            "pi_ollama_tunnel_remote_host": "127.0.0.1",
            "pi_ollama_tunnel_remote_port": 11434,
            "pi_request_timeout_seconds": 5,
        }
        values.update(overrides)
        return SimpleNamespace(**values)

    def test_run_live_pi_turn_reuses_scope_session_between_requests(self):
        config = self._config()
        fake_process = _FakePiProcess(["first answer", "second answer"])

        with mock.patch.object(pi_live_rpc.subprocess, "Popen", return_value=fake_process) as popen_mock:
            first = pi_live_rpc.run_live_pi_turn(
                config=config,
                prompt="first",
                scope_key="tg:1",
                image_paths=[],
                cancel_event=None,
            )
            second = pi_live_rpc.run_live_pi_turn(
                config=config,
                prompt="second",
                scope_key="tg:1",
                image_paths=[],
                cancel_event=None,
            )

        self.assertEqual(popen_mock.call_count, 1)
        self.assertEqual(cached_executor_result_output(first), (None, "first answer"))
        self.assertEqual(cached_executor_result_output(second), (None, "second answer"))

    def test_live_pi_turn_does_not_accept_follow_up_steering(self):
        config = self._config()
        release_first_response = threading.Event()
        fake_process = _FakePiProcess(["initial answer"], release_first_response=release_first_response)
        result_holder = {}
        error_holder = {}

        def _worker() -> None:
            try:
                result_holder["result"] = pi_live_rpc.run_live_pi_turn(
                    config=config,
                    prompt="original task",
                    scope_key="tg:followup",
                    image_paths=[],
                    cancel_event=None,
                )
            except BaseException as exc:  # pragma: no cover - captured for assertions
                error_holder["error"] = exc

        with mock.patch.object(pi_live_rpc.subprocess, "Popen", return_value=fake_process):
            worker = threading.Thread(target=_worker, daemon=True)
            worker.start()
            time.sleep(0.2)
            self.assertFalse(pi_live_rpc.try_steer_live_pi_turn(config, "tg:followup", "follow up one"))
            release_first_response.set()
            worker.join(timeout=5)

        self.assertFalse(worker.is_alive())
        self.assertNotIn("error", error_holder)
        result = result_holder["result"]
        self.assertEqual(cached_executor_result_output(result), (None, "initial answer"))
        self.assertEqual(cached_executor_result_steered_follow_up_count(result), 0)
        self.assertEqual(len(fake_process.prompt_payloads), 1)

    def test_live_pi_turn_does_not_wait_for_missing_follow_up(self):
        config = self._config()
        fake_process = _FakePiProcess(["initial answer"])

        with mock.patch.object(pi_live_rpc.subprocess, "Popen", return_value=fake_process):
            started_at = time.monotonic()
            result = pi_live_rpc.run_live_pi_turn(
                config=config,
                prompt="original task",
                scope_key="tg:no-followup-wait",
                image_paths=[],
                cancel_event=None,
            )
            elapsed = time.monotonic() - started_at

        self.assertEqual(cached_executor_result_output(result), (None, "initial answer"))
        self.assertEqual(len(fake_process.prompt_payloads), 1)
        self.assertLess(elapsed, 1.0)

    def test_live_pi_turn_cancel_kills_process_and_raises(self):
        config = self._config()
        cancel_event = threading.Event()
        fake_process = _FakePiProcess(["unused"], release_first_response=threading.Event())
        error_holder = {}

        def _worker() -> None:
            try:
                pi_live_rpc.run_live_pi_turn(
                    config=config,
                    prompt="cancel me",
                    scope_key="tg:cancel",
                    image_paths=[],
                    cancel_event=cancel_event,
                )
            except BaseException as exc:  # pragma: no cover - captured for assertions
                error_holder["error"] = exc

        with mock.patch.object(pi_live_rpc.subprocess, "Popen", return_value=fake_process):
            worker = threading.Thread(target=_worker, daemon=True)
            worker.start()
            time.sleep(0.2)
            cancel_event.set()
            worker.join(timeout=5)

        self.assertFalse(worker.is_alive())
        self.assertIsInstance(error_holder.get("error"), ExecutorCancelledError)
        self.assertTrue(fake_process._killed or pi_live_rpc.live_pi_turn_is_active(config, "tg:cancel") in {False, None})

    def test_live_pi_turn_uses_nested_engine_config_values(self):
        nested = self._config(
            pi_provider="venice",
            pi_model="venice-model",
            pi_runner="ssh",
            pi_ssh_host="server4-nested",
            pi_remote_cwd="/nested-runtime",
        )
        config = SimpleNamespace(
            pi_live_rpc_enabled=False,
            pi_provider="deepseek",
            pi_model="top-level-model",
            pi_runner="local",
            pi_ssh_host="server4-top-level",
            pi_remote_cwd="/top-level-runtime",
            engines=nested,
        )
        fake_process = _FakePiProcess(["nested answer"])

        with mock.patch.object(pi_live_rpc.subprocess, "Popen", return_value=fake_process) as popen_mock:
            result = pi_live_rpc.run_live_pi_turn(
                config=config,
                prompt="nested config",
                scope_key="tg:nested",
                image_paths=[],
                cancel_event=None,
            )

        self.assertEqual(cached_executor_result_output(result), (None, "nested answer"))
        self.assertEqual(pi_live_rpc._session_signature(config), ("ssh", "venice", "venice-model"))
        self.assertEqual(popen_mock.call_args.args[0][:4], ["ssh", "-o", "BatchMode=yes", "server4-nested"])
        self.assertIn("cd /nested-runtime &&", popen_mock.call_args.args[0][4])


if __name__ == "__main__":
    unittest.main()
