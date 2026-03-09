import importlib.util
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "src" / "telegram_bridge" / "runtime_routing.py"
MODULE_DIR = MODULE_PATH.parent

spec = importlib.util.spec_from_file_location("telegram_bridge_runtime_routing", MODULE_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError("Failed to load telegram runtime routing module spec")
runtime_routing = importlib.util.module_from_spec(spec)
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))
sys.modules[spec.name] = runtime_routing
spec.loader.exec_module(runtime_routing)


class RuntimeRoutingTests(unittest.TestCase):
    def test_apply_required_prefix_gate_ignores_non_prefixed_text(self) -> None:
        client = SimpleNamespace(channel_name="telegram")
        config = SimpleNamespace(
            required_prefixes=["@helper"],
            required_prefix_ignore_case=True,
            require_prefix_in_private=True,
        )

        result = runtime_routing.apply_required_prefix_gate(
            client=client,
            config=config,
            prompt_input="hello there",
            voice_file_id=None,
            document=None,
            is_private_chat=False,
            normalize_command=lambda text: None,
            strip_required_prefix=lambda text, prefixes, ignore_case: (False, text),
        )

        self.assertTrue(result.ignored)
        self.assertEqual(result.rejection_reason, "prefix_required")

    def test_apply_priority_keyword_routing_rejects_empty_server3_request(self) -> None:
        config = SimpleNamespace(keyword_routing_enabled=True)

        result = runtime_routing.apply_priority_keyword_routing(
            config=config,
            prompt_input="Server3 TV",
            command=None,
            chat_id=1,
        )

        self.assertEqual(result.rejection_reason, "server3_keyword_missing_action")
        self.assertIn("Server3 TV mode needs an action.", result.rejection_message)


if __name__ == "__main__":
    unittest.main()
