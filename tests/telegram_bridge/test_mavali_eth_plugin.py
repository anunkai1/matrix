import importlib.util
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[2]
BRIDGE_DIR = ROOT / "src" / "telegram_bridge"
SRC_ROOT = ROOT / "src"
if str(BRIDGE_DIR) not in sys.path:
    sys.path.insert(0, str(BRIDGE_DIR))
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

import plugin_registry as bridge_plugin_registry
import engine_adapter as bridge_engine_adapter


class MavaliEthPluginTests(unittest.TestCase):
    def test_default_plugin_registry_exposes_mavali_eth_engine(self):
        registry = bridge_plugin_registry.build_default_plugin_registry()
        self.assertIn("mavali_eth", registry.list_engines())
        engine = registry.build_engine("mavali_eth")
        self.assertIsInstance(engine, bridge_engine_adapter.MavaliEthEngineAdapter)

    def test_mavali_eth_engine_returns_config_error_as_text(self):
        engine = bridge_engine_adapter.MavaliEthEngineAdapter()
        config = SimpleNamespace(state_dir="/tmp")
        result = engine.run(
            config=config,
            prompt="what is my wallet address",
            thread_id=None,
            session_key="telegram:1",
            channel_name="telegram",
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("MAVALI_ETH_KEYSTORE_PASSPHRASE", result.stdout)
