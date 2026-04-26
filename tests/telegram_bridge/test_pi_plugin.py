import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
BRIDGE_DIR = ROOT / "src" / "telegram_bridge"
SRC_ROOT = ROOT / "src"
if str(BRIDGE_DIR) not in sys.path:
    sys.path.insert(0, str(BRIDGE_DIR))
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

import engine_adapter as bridge_engine_adapter
import plugin_registry as bridge_plugin_registry


class PiPluginTests(unittest.TestCase):
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
            pi_tools_mode="none",
            pi_tools_allowlist="",
            pi_extra_args="--thinking low",
            pi_ollama_tunnel_enabled=True,
            pi_ollama_tunnel_local_port=11435,
            pi_ollama_tunnel_remote_host="127.0.0.1",
            pi_ollama_tunnel_remote_port=11434,
            pi_request_timeout_seconds=30,
        )
        fake_process = mock.MagicMock()
        fake_process.communicate.return_value = ("hello from pi\n", "")
        fake_process.returncode = 0
        fake_process.args = []
        fake_process.wait.return_value = 0

        with mock.patch.object(
            bridge_engine_adapter.subprocess,
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
            pi_tools_mode="none",
            pi_tools_allowlist="",
            pi_extra_args="",
            pi_ollama_tunnel_enabled=False,
            pi_ollama_tunnel_local_port=19091,
            pi_ollama_tunnel_remote_host="127.0.0.1",
            pi_ollama_tunnel_remote_port=11434,
            pi_request_timeout_seconds=30,
        )
        fake_process = mock.MagicMock()
        fake_process.communicate.return_value = ("hello from local pi\n", "")
        fake_process.returncode = 0
        fake_process.args = []
        fake_process.wait.return_value = 0

        with mock.patch.object(
            bridge_engine_adapter.subprocess,
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
            pi_tools_mode="none",
            pi_tools_allowlist="",
            pi_extra_args="",
            pi_ollama_tunnel_enabled=False,
            pi_ollama_tunnel_local_port=19091,
            pi_ollama_tunnel_remote_host="127.0.0.1",
            pi_ollama_tunnel_remote_port=11434,
            pi_request_timeout_seconds=30,
        )
        fake_process = mock.MagicMock()
        fake_process.communicate.return_value = ("hello from scoped pi\n", "")
        fake_process.returncode = 0
        fake_process.args = []
        fake_process.wait.return_value = 0

        with mock.patch.object(
            bridge_engine_adapter.subprocess,
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
        self.assertTrue(session_arg.startswith("/runtime/pi-sessions/tg_-1003706836145_topic_2843-"))
        self.assertTrue(session_arg.endswith(".jsonl"))


if __name__ == "__main__":
    unittest.main()
