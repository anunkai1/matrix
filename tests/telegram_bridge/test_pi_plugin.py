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
            pi_ssh_host="server4-test",
            pi_remote_cwd="/tmp",
            pi_tools_mode="none",
            pi_tools_allowlist="",
            pi_extra_args="--thinking low",
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


if __name__ == "__main__":
    unittest.main()
