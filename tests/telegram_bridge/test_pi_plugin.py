import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

import telegram_bridge.engine_adapter as bridge_engine_adapter
import telegram_bridge.engines.pi as pi_engine
import telegram_bridge.plugin_registry as bridge_plugin_registry


def _make_fake_pi_process(output_text: str):
    class _FakeStdin:
        def __init__(self) -> None:
            self.closed = False
            self.buffer: list[str] = []

        def write(self, value: str) -> None:
            if self.closed:
                raise ValueError("I/O operation on closed file.")
            self.buffer.append(value)

        def flush(self) -> None:
            if self.closed:
                raise ValueError("I/O operation on closed file.")

        def close(self) -> None:
            self.closed = True

    class _FakeStdout:
        def __init__(self, payload: str) -> None:
            self._lines = [
                (
                    '{"type":"agent_end","messages":[{"role":"assistant","content":'
                    f'[{{"type":"text","text":{payload!r}}}]}}]}}\n'
                ).replace("'", '"')
            ]

        def readline(self) -> str:
            if self._lines:
                return self._lines.pop(0)
            return ""

    class _FakeProcess:
        def __init__(self, payload: str) -> None:
            self.stdin = _FakeStdin()
            self.stdout = _FakeStdout(payload)
            self.stderr = None
            self.returncode = 0
            self.args = []

        def poll(self):
            return None if self.stdout._lines else 0

        def communicate(self, timeout=None):
            if self.stdin is not None:
                raise ValueError("I/O operation on closed file.")
            return ("", "")

        def wait(self, timeout=None):
            return 0

        def kill(self) -> None:
            raise AssertionError("kill should not be called")

    return _FakeProcess(output_text)


def _make_fake_pi_empty_rpc_process():
    class _FakeStdin:
        def __init__(self) -> None:
            self.closed = False

        def write(self, value: str) -> None:
            if self.closed:
                raise ValueError("I/O operation on closed file.")

        def flush(self) -> None:
            if self.closed:
                raise ValueError("I/O operation on closed file.")

        def close(self) -> None:
            self.closed = True

    class _FakeStdout:
        def __init__(self) -> None:
            self._lines = [
                '{"type":"response","command":"prompt","success":true}\n',
                '{"type":"agent_start"}\n',
                '{"type":"turn_start"}\n',
                '{"type":"message_start","message":{"role":"user","content":[{"type":"text","text":"hello"}]}}\n',
                '{"type":"message_end","message":{"role":"user","content":[{"type":"text","text":"hello"}]}}\n',
            ]

        def readline(self) -> str:
            if self._lines:
                return self._lines.pop(0)
            return ""

    class _FakeProcess:
        def __init__(self) -> None:
            self.stdin = _FakeStdin()
            self.stdout = _FakeStdout()
            self.stderr = None
            self.returncode = 0
            self.args = []

        def poll(self):
            return None if self.stdout._lines else 0

        def communicate(self, timeout=None):
            if self.stdin is not None:
                raise ValueError("I/O operation on closed file.")
            return ("", "")

        def wait(self, timeout=None):
            return 0

        def kill(self) -> None:
            raise AssertionError("kill should not be called")

    return _FakeProcess()


class PiPluginTests(unittest.TestCase):
    def test_pi_engine_local_keeps_stdin_open_until_agent_end(self):
        engine = bridge_engine_adapter.PiEngineAdapter()
        config = SimpleNamespace(
            pi_provider="ollama",
            pi_model="gemma4:26b",
            pi_runner="local",
            pi_bin="pi",
            pi_ssh_host="server4-test",
            pi_local_cwd="/runtime/root",
            pi_remote_cwd="/tmp",
            pi_session_mode="none",
            pi_session_dir="",
            pi_session_max_bytes=2 * 1024 * 1024,
            pi_session_max_age_seconds=7 * 24 * 60 * 60,
            pi_session_archive_retention_seconds=14 * 24 * 60 * 60,
            pi_session_archive_dir="",
            pi_tools_mode="none",
            pi_tools_allowlist="",
            pi_extra_args="",
            pi_ollama_tunnel_enabled=False,
            pi_ollama_tunnel_local_port=19091,
            pi_ollama_tunnel_remote_host="127.0.0.1",
            pi_ollama_tunnel_remote_port=11434,
            pi_request_timeout_seconds=30,
        )

        class _GateableStdin:
            def __init__(self) -> None:
                self.closed = False

            def write(self, value: str) -> None:
                if self.closed:
                    raise ValueError("I/O operation on closed file.")

            def flush(self) -> None:
                if self.closed:
                    raise ValueError("I/O operation on closed file.")

            def close(self) -> None:
                self.closed = True

        class _GateableStdout:
            def __init__(self, stdin_handle: _GateableStdin) -> None:
                self._stdin = stdin_handle
                self._emitted = False

            def readline(self) -> str:
                if self._stdin.closed:
                    return ""
                if self._emitted:
                    return ""
                self._emitted = True
                return (
                    '{"type":"agent_end","messages":[{"role":"assistant","content":'
                    '[{"type":"text","text":"hello after agent_end"}]}]}\n'
                )

        class _GateableProcess:
            def __init__(self) -> None:
                self.stdin = _GateableStdin()
                self.stdout = _GateableStdout(self.stdin)
                self.stderr = None
                self.returncode = 0
                self.args = []

            def poll(self):
                return None if not self.stdout._emitted else 0

            def communicate(self, timeout=None):
                if self.stdin is not None:
                    raise ValueError("I/O operation on closed file.")
                return ("", "")

            def wait(self, timeout=None):
                return 0

            def kill(self) -> None:
                raise AssertionError("kill should not be called")

        with mock.patch.object(
            pi_engine.subprocess,
            "Popen",
            return_value=_GateableProcess(),
        ):
            result = engine.run(config=config, prompt="hello", thread_id=None)

        self.assertEqual(result.returncode, 0)
        self.assertIn("hello after agent_end", result.stdout)

    def test_pi_engine_local_detaches_closed_stdin_before_communicate(self):
        engine = bridge_engine_adapter.PiEngineAdapter()
        config = SimpleNamespace(
            pi_provider="ollama",
            pi_model="gemma4:26b",
            pi_runner="local",
            pi_bin="pi",
            pi_ssh_host="server4-test",
            pi_local_cwd="/runtime/root",
            pi_remote_cwd="/tmp",
            pi_session_mode="none",
            pi_session_dir="",
            pi_session_max_bytes=2 * 1024 * 1024,
            pi_session_max_age_seconds=7 * 24 * 60 * 60,
            pi_session_archive_retention_seconds=14 * 24 * 60 * 60,
            pi_session_archive_dir="",
            pi_tools_mode="none",
            pi_tools_allowlist="",
            pi_extra_args="",
            pi_ollama_tunnel_enabled=False,
            pi_ollama_tunnel_local_port=19091,
            pi_ollama_tunnel_remote_host="127.0.0.1",
            pi_ollama_tunnel_remote_port=11434,
            pi_request_timeout_seconds=30,
        )
        fake_process = _make_fake_pi_process("hello from local pi")

        with mock.patch.object(
            pi_engine.subprocess,
            "Popen",
            return_value=fake_process,
        ):
            result = engine.run(config=config, prompt="hello", thread_id=None)

        self.assertEqual(result.returncode, 0)
        self.assertIn("hello from local pi", result.stdout)

    def test_default_plugin_registry_exposes_pi_engine(self):
        registry = bridge_plugin_registry.build_default_plugin_registry()
        self.assertIn("pi", registry.list_engines())
        self.assertIsInstance(registry.build_engine("pi"), bridge_engine_adapter.PiEngineAdapter)

    def test_pi_engine_runs_over_ssh_with_configured_model(self):
        engine = bridge_engine_adapter.PiEngineAdapter()
        config = SimpleNamespace(
            pi_provider="ollama",
            pi_model="gemma4:26b",
            pi_runner="ssh",
            pi_bin="pi",
            pi_ssh_host="server4-test",
            pi_local_cwd="/tmp/local",
            pi_remote_cwd="/tmp",
            pi_session_mode="none",
            pi_session_dir="",
            pi_session_max_bytes=2 * 1024 * 1024,
            pi_session_max_age_seconds=7 * 24 * 60 * 60,
            pi_session_archive_retention_seconds=14 * 24 * 60 * 60,
            pi_session_archive_dir="",
            pi_tools_mode="none",
            pi_tools_allowlist="",
            pi_extra_args="--thinking low",
            pi_ollama_tunnel_enabled=True,
            pi_ollama_tunnel_local_port=11435,
            pi_ollama_tunnel_remote_host="127.0.0.1",
            pi_ollama_tunnel_remote_port=11434,
            pi_request_timeout_seconds=30,
        )
        fake_process = _make_fake_pi_process("hello from pi")

        with mock.patch.object(
            pi_engine.subprocess,
            "Popen",
            return_value=fake_process,
        ) as popen_mock:
            result = engine.run(config=config, prompt="hello", thread_id=None)

        self.assertEqual(result.returncode, 0)
        self.assertIn("OUTPUT_BEGIN", result.stdout)
        self.assertIn("hello from pi", result.stdout)
        cmd = popen_mock.call_args.args[0]
        self.assertEqual(cmd[:3], ["ssh", "-o", "BatchMode=yes"])
        self.assertIn("server4-test", cmd)
        self.assertIn("--provider ollama", cmd[-1])
        self.assertIn("--model gemma4:26b", cmd[-1])
        self.assertIn("--no-tools", cmd[-1])
        self.assertIn("--thinking low", cmd[-1])

    def test_pi_engine_can_run_locally_in_runtime_cwd(self):
        engine = bridge_engine_adapter.PiEngineAdapter()
        config = SimpleNamespace(
            pi_provider="ollama",
            pi_model="gemma4:26b",
            pi_runner="local",
            pi_bin="pi",
            pi_ssh_host="server4-test",
            pi_local_cwd="/runtime/root",
            pi_remote_cwd="/tmp",
            pi_session_mode="none",
            pi_session_dir="",
            pi_session_max_bytes=2 * 1024 * 1024,
            pi_session_max_age_seconds=7 * 24 * 60 * 60,
            pi_session_archive_retention_seconds=14 * 24 * 60 * 60,
            pi_session_archive_dir="",
            pi_tools_mode="none",
            pi_tools_allowlist="",
            pi_extra_args="",
            pi_ollama_tunnel_enabled=False,
            pi_ollama_tunnel_local_port=19091,
            pi_ollama_tunnel_remote_host="127.0.0.1",
            pi_ollama_tunnel_remote_port=11434,
            pi_request_timeout_seconds=30,
        )
        fake_process = _make_fake_pi_process("hello from local pi")

        with mock.patch.object(
            pi_engine.subprocess,
            "Popen",
            return_value=fake_process,
        ) as popen_mock:
            result = engine.run(config=config, prompt="hello", thread_id=None)

        self.assertEqual(result.returncode, 0)
        self.assertIn("hello from local pi", result.stdout)
        popen_mock.assert_called_once()
        self.assertEqual(popen_mock.call_args.kwargs["cwd"], "/runtime/root")
        self.assertEqual(popen_mock.call_args.args[0][0], "pi")
        self.assertNotIn("--no-context-files", popen_mock.call_args.args[0])
        self.assertIn("--no-session", popen_mock.call_args.args[0])
        self.assertEqual(
            popen_mock.call_args.kwargs["env"]["OLLAMA_HOST"],
            "http://127.0.0.1:19091",
        )

    def test_pi_engine_local_ollama_path_uses_pi_cli_not_raw_http_shortcut(self):
        engine = bridge_engine_adapter.PiEngineAdapter()
        config = SimpleNamespace(
            pi_provider="ollama",
            pi_model="gemma4:26b",
            pi_runner="local",
            pi_bin="pi",
            pi_ssh_host="server4-test",
            pi_local_cwd="/runtime/root",
            pi_remote_cwd="/tmp",
            pi_session_mode="telegram_scope",
            pi_session_dir="/runtime/pi-sessions",
            pi_session_max_bytes=2 * 1024 * 1024,
            pi_session_max_age_seconds=7 * 24 * 60 * 60,
            pi_session_archive_retention_seconds=14 * 24 * 60 * 60,
            pi_session_archive_dir="",
            pi_tools_mode="allowlist",
            pi_tools_allowlist="read,bash",
            pi_extra_args="",
            pi_ollama_tunnel_enabled=True,
            pi_ollama_tunnel_local_port=19091,
            pi_ollama_tunnel_remote_host="127.0.0.1",
            pi_ollama_tunnel_remote_port=11434,
            pi_request_timeout_seconds=30,
        )
        fake_process = _make_fake_pi_process("hello from local pi")

        with (
            mock.patch.object(engine, "_ensure_local_ollama_tunnel") as ensure_tunnel,
            mock.patch.object(
                pi_engine.subprocess,
                "Popen",
                return_value=fake_process,
            ) as popen_mock,
            mock.patch.object(bridge_engine_adapter.urllib_request, "urlopen") as urlopen_mock,
        ):
            result = engine.run(
                config=config,
                prompt="hello",
                thread_id=None,
                session_key="tg:1",
            )

        self.assertEqual(result.returncode, 0)
        ensure_tunnel.assert_called_once_with(config)
        urlopen_mock.assert_not_called()
        cmd = popen_mock.call_args.args[0]
        self.assertIn("--session", cmd)
        self.assertIn("--tools", cmd)

    def test_pi_engine_skips_ollama_tunnel_for_local_venice_provider(self):
        engine = bridge_engine_adapter.PiEngineAdapter()
        config = SimpleNamespace(
            pi_provider="venice",
            pi_model="zai-org-glm-5-1",
            pi_runner="local",
            pi_bin="pi",
            pi_ssh_host="server4-test",
            pi_local_cwd="/runtime/root",
            pi_remote_cwd="/tmp",
            pi_session_mode="none",
            pi_session_dir="",
            pi_session_max_bytes=2 * 1024 * 1024,
            pi_session_max_age_seconds=7 * 24 * 60 * 60,
            pi_session_archive_retention_seconds=14 * 24 * 60 * 60,
            pi_session_archive_dir="",
            pi_tools_mode="none",
            pi_tools_allowlist="",
            pi_extra_args="",
            pi_ollama_tunnel_enabled=True,
            pi_ollama_tunnel_local_port=19091,
            pi_ollama_tunnel_remote_host="127.0.0.1",
            pi_ollama_tunnel_remote_port=11434,
            pi_request_timeout_seconds=30,
        )
        fake_process = _make_fake_pi_process("hello from venice pi")

        with (
            mock.patch.object(
                engine,
                "_ensure_local_ollama_tunnel",
                side_effect=AssertionError("Ollama tunnel should not start for Venice"),
            ),
            mock.patch.object(
                pi_engine.subprocess,
                "Popen",
                return_value=fake_process,
            ) as popen_mock,
        ):
            result = engine.run(config=config, prompt="hello", thread_id=None)

        self.assertEqual(result.returncode, 0)
        self.assertIn("hello from venice pi", result.stdout)
        cmd = popen_mock.call_args.args[0]
        self.assertIn("--provider", cmd)
        self.assertEqual(cmd[cmd.index("--provider") + 1], "venice")
        self.assertEqual(cmd[cmd.index("--model") + 1], "zai-org-glm-5-1")

    def test_pi_engine_local_falls_back_to_text_mode_when_rpc_exits_without_output(self):
        engine = bridge_engine_adapter.PiEngineAdapter()
        config = SimpleNamespace(
            pi_provider="deepseek",
            pi_model="deepseek-v4-pro",
            pi_runner="local",
            pi_bin="pi",
            pi_ssh_host="server4-test",
            pi_local_cwd="/runtime/root",
            pi_remote_cwd="/tmp",
            pi_session_mode="none",
            pi_session_dir="",
            pi_session_max_bytes=2 * 1024 * 1024,
            pi_session_max_age_seconds=7 * 24 * 60 * 60,
            pi_session_archive_retention_seconds=14 * 24 * 60 * 60,
            pi_session_archive_dir="",
            pi_tools_mode="none",
            pi_tools_allowlist="",
            pi_extra_args="",
            pi_ollama_tunnel_enabled=False,
            pi_ollama_tunnel_local_port=19091,
            pi_ollama_tunnel_remote_host="127.0.0.1",
            pi_ollama_tunnel_remote_port=11434,
            pi_request_timeout_seconds=30,
        )
        fake_process = _make_fake_pi_empty_rpc_process()
        fake_completed = subprocess.CompletedProcess(
            args=["pi", "--print"],
            returncode=0,
            stdout="ok from text mode\n",
            stderr="",
        )

        with (
            mock.patch.object(
                pi_engine.subprocess,
                "Popen",
                return_value=fake_process,
            ),
            mock.patch.object(
                pi_engine.subprocess,
                "run",
                return_value=fake_completed,
            ) as run_mock,
        ):
            result = engine.run(config=config, prompt="hello", thread_id=None)

        self.assertEqual(result.returncode, 0)
        self.assertIn("ok from text mode", result.stdout)
        fallback_cmd = run_mock.call_args.args[0]
        self.assertIn("--print", fallback_cmd)
        self.assertNotIn("--mode", fallback_cmd)
        self.assertEqual(fallback_cmd[-1], "hello")

    def test_pi_engine_resets_image_contaminated_session_for_image_capable_model(self):
        engine = bridge_engine_adapter.PiEngineAdapter()
        config = SimpleNamespace(
            pi_provider="deepseek",
            pi_model="deepseek-v4-pro",
            pi_runner="local",
            pi_bin="pi",
            pi_ssh_host="server4-test",
            pi_local_cwd="/runtime/root",
            pi_remote_cwd="/tmp",
            pi_session_mode="telegram_scope",
            pi_session_dir="/runtime/pi-sessions",
            pi_session_max_bytes=2 * 1024 * 1024,
            pi_session_max_age_seconds=7 * 24 * 60 * 60,
            pi_session_archive_retention_seconds=14 * 24 * 60 * 60,
            pi_session_archive_dir="",
            pi_tools_mode="none",
            pi_tools_allowlist="",
            pi_extra_args="",
            pi_ollama_tunnel_enabled=False,
            pi_ollama_tunnel_local_port=19091,
            pi_ollama_tunnel_remote_host="127.0.0.1",
            pi_ollama_tunnel_remote_port=11434,
            pi_request_timeout_seconds=30,
        )

        calls = []

        def _fake_run_pi_local(_config, prompt, session_key, cancel_event, **kwargs):
            del cancel_event, kwargs
            calls.append((prompt, session_key))
            if session_key is not None:
                raise RuntimeError(
                    "400 Failed to deserialize the JSON body into the target type: "
                    "messages[118]: unknown variant `image_url`, expected `text`"
                )
            return "clean retry output"

        with mock.patch.object(
            engine,
            "_run_pi_local",
            side_effect=_fake_run_pi_local,
        ):
            result = engine.run(
                config=config,
                prompt="Hi",
                thread_id=None,
                session_key="tg:-1003894351534:topic:1712",
            )

        self.assertEqual(result.returncode, 0)
        self.assertIn("Session was reset because the previous Pi session", result.stdout)
        self.assertIn("clean retry output", result.stdout)
        self.assertEqual(
            calls,
            [("Hi", "tg:-1003894351534:topic:1712"), ("Hi", None)],
        )

    def test_pi_engine_can_use_telegram_scope_session_path(self):
        engine = bridge_engine_adapter.PiEngineAdapter()
        config = SimpleNamespace(
            pi_provider="ollama",
            pi_model="gemma4:26b",
            pi_runner="local",
            pi_bin="pi",
            pi_ssh_host="server4-test",
            pi_local_cwd="/runtime/root",
            pi_remote_cwd="/tmp",
            pi_session_mode="telegram_scope",
            pi_session_dir="/runtime/pi-sessions",
            pi_session_max_bytes=2 * 1024 * 1024,
            pi_session_max_age_seconds=7 * 24 * 60 * 60,
            pi_session_archive_retention_seconds=14 * 24 * 60 * 60,
            pi_session_archive_dir="",
            pi_tools_mode="none",
            pi_tools_allowlist="",
            pi_extra_args="",
            pi_ollama_tunnel_enabled=False,
            pi_ollama_tunnel_local_port=19091,
            pi_ollama_tunnel_remote_host="127.0.0.1",
            pi_ollama_tunnel_remote_port=11434,
            pi_request_timeout_seconds=30,
        )
        fake_process = _make_fake_pi_process("hello from scoped pi")

        with mock.patch.object(
            pi_engine.subprocess,
            "Popen",
            return_value=fake_process,
        ) as popen_mock:
            result = engine.run(
                config=config,
                prompt="hello",
                thread_id=None,
                session_key="tg:-1003706836145:topic:2843",
            )

        self.assertEqual(result.returncode, 0)
        self.assertIn("hello from scoped pi", result.stdout)
        cmd = popen_mock.call_args.args[0]
        self.assertNotIn("--no-session", cmd)
        self.assertIn("--session-dir", cmd)
        self.assertIn("/runtime/pi-sessions", cmd)
        session_arg = cmd[cmd.index("--session") + 1]
        self.assertIn("provider_ollama", session_arg)
        self.assertIn("model_gemma4_26b", session_arg)
        self.assertTrue(session_arg.endswith(".jsonl"))

    def test_pi_engine_scopes_native_sessions_by_provider_and_model(self):
        engine = bridge_engine_adapter.PiEngineAdapter()
        session_key = "tg:-1003706836145:topic:2843"
        venice_config = SimpleNamespace(pi_provider="venice", pi_model="zai-org-glm-5-1")
        deepseek_config = SimpleNamespace(pi_provider="deepseek", pi_model="deepseek-v4-pro")

        venice_name = engine._safe_session_filename(engine._provider_scoped_session_key(venice_config, session_key))
        deepseek_name = engine._safe_session_filename(engine._provider_scoped_session_key(deepseek_config, session_key))

        self.assertNotEqual(venice_name, deepseek_name)
        self.assertIn("provider_venice", venice_name)
        self.assertIn("provider_deepseek", deepseek_name)

    def test_pi_engine_rotates_large_or_stale_sessions_and_prunes_old_archives(self):
        engine = bridge_engine_adapter.PiEngineAdapter()
        with tempfile.TemporaryDirectory() as tmpdir:
            session_dir = Path(tmpdir) / "sessions"
            archive_dir = Path(tmpdir) / "archive"
            session_dir.mkdir(parents=True, exist_ok=True)
            archive_dir.mkdir(parents=True, exist_ok=True)
            session_key = "tg:-1003706836145:topic:2843"
            scoped_session_key = engine._provider_scoped_session_key(
                SimpleNamespace(pi_provider="ollama", pi_model="gemma4:26b"),
                session_key,
            )
            session_path = session_dir / engine._safe_session_filename(scoped_session_key)
            session_path.write_text("x" * 4096, encoding="utf-8")
            old_ts = time.time() - 10_000
            stale_archive = archive_dir / "legacy.rotated.20240101T000000Z.jsonl"
            stale_archive.write_text("old archive", encoding="utf-8")
            os.utime(stale_archive, (old_ts, old_ts))

            config = SimpleNamespace(
                pi_provider="ollama",
                pi_model="gemma4:26b",
                pi_runner="local",
                pi_bin="pi",
                pi_ssh_host="server4-test",
                pi_local_cwd="/runtime/root",
                pi_remote_cwd="/tmp",
                pi_session_mode="telegram_scope",
                pi_session_dir=str(session_dir),
                pi_session_max_bytes=1024,
                pi_session_max_age_seconds=3600,
                pi_session_archive_retention_seconds=7200,
                pi_session_archive_dir=str(archive_dir),
                pi_tools_mode="none",
                pi_tools_allowlist="",
                pi_extra_args="",
                pi_ollama_tunnel_enabled=False,
                pi_ollama_tunnel_local_port=19091,
                pi_ollama_tunnel_remote_host="127.0.0.1",
                pi_ollama_tunnel_remote_port=11434,
                pi_request_timeout_seconds=30,
            )
            fake_process = _make_fake_pi_process("rotated session")

            with mock.patch.object(
                pi_engine.subprocess,
                "Popen",
                return_value=fake_process,
            ):
                result = engine.run(
                    config=config,
                    prompt="hello",
                    thread_id=None,
                    session_key=session_key,
                )

            self.assertEqual(result.returncode, 0)
            self.assertFalse(session_path.exists())
            rotated = list(archive_dir.glob("*.rotated.*.jsonl"))
            self.assertEqual(len(rotated), 1)
            self.assertTrue(rotated[0].name.startswith(session_path.stem + ".rotated."))
            self.assertFalse(stale_archive.exists())


if __name__ == "__main__":
    unittest.main()
