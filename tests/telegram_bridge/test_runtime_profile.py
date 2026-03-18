import importlib.util
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "src" / "telegram_bridge" / "runtime_profile.py"
MODULE_DIR = MODULE_PATH.parent

spec = importlib.util.spec_from_file_location("telegram_bridge_runtime_profile", MODULE_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError("Failed to load telegram runtime profile module spec")
runtime_profile = importlib.util.module_from_spec(spec)
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))
sys.modules[spec.name] = runtime_profile
spec.loader.exec_module(runtime_profile)


class RuntimeProfileTests(unittest.TestCase):
    def test_extract_keyword_request_supports_expected_separators(self) -> None:
        self.assertEqual(
            runtime_profile.extract_server3_keyword_request("Server3 TV: open Firefox"),
            (True, "open Firefox"),
        )
        self.assertEqual(
            runtime_profile.extract_browser_brain_keyword_request("Server3 Browser - snapshot current page"),
            (True, "snapshot current page"),
        )

    def test_apply_outbound_reply_prefix_normalizes_whatsapp_prefix(self) -> None:
        client = SimpleNamespace(channel_name="whatsapp")
        self.assertEqual(
            runtime_profile.apply_outbound_reply_prefix(client, "говорун: привет"),
            "Даю справку: привет",
        )
        self.assertEqual(
            runtime_profile.apply_outbound_reply_prefix(client, "Даю справку: привет"),
            "Даю справку: привет",
        )

    def test_start_command_message_uses_assistant_name(self) -> None:
        config = SimpleNamespace(assistant_name="HelperBot")
        self.assertIn("HelperBot", runtime_profile.start_command_message(config))

    def test_browser_brain_prompt_references_wrapper(self) -> None:
        prompt = runtime_profile.build_browser_brain_keyword_prompt("open example.com")
        self.assertIn("browser_brain_ctl.sh", prompt)
        self.assertIn("snapshot", prompt)

if __name__ == "__main__":
    unittest.main()
