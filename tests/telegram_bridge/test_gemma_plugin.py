import os
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


class GemmaPluginTests(unittest.TestCase):
    def test_default_plugin_registry_exposes_gemma_engine(self):
        registry = bridge_plugin_registry.build_default_plugin_registry()
        self.assertIn("gemma", registry.list_engines())
        self.assertIsInstance(registry.build_engine("gemma"), bridge_engine_adapter.GemmaEngineAdapter)

    def test_gemma_http_engine_extracts_ollama_content(self):
        engine = bridge_engine_adapter.GemmaEngineAdapter()
        config = SimpleNamespace(
            gemma_provider="ollama_http",
            gemma_model="gemma4:26b",
            gemma_base_url="http://server4-beast:11434",
            gemma_request_timeout_seconds=30,
        )
        response = b'{"message":{"role":"assistant","content":"hello from gemma"},"done":true}'
        fake_urlopen = mock.MagicMock()
        fake_urlopen.return_value.__enter__.return_value.read.return_value = response
        with mock.patch.object(bridge_engine_adapter.urllib_request, "urlopen", fake_urlopen):
            result = engine.run(config=config, prompt="hello", thread_id=None)
        self.assertEqual(result.returncode, 0)
        self.assertIn("OUTPUT_BEGIN", result.stdout)
        self.assertIn("hello from gemma", result.stdout)


if __name__ == "__main__":
    unittest.main()
