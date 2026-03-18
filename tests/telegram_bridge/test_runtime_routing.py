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
            has_reply_context=False,
            voice_file_id=None,
            document=None,
            is_private_chat=False,
            normalize_command=lambda text: None,
            strip_required_prefix=lambda text, prefixes, ignore_case: (False, text),
        )

        self.assertTrue(result.ignored)
        self.assertEqual(result.rejection_reason, "prefix_required")

    def test_apply_required_prefix_gate_allows_prefix_only_reply_when_context_exists(self) -> None:
        client = SimpleNamespace(channel_name="whatsapp")
        config = SimpleNamespace(
            required_prefixes=["govorun"],
            required_prefix_ignore_case=True,
            require_prefix_in_private=True,
        )

        result = runtime_routing.apply_required_prefix_gate(
            client=client,
            config=config,
            prompt_input="govorun",
            has_reply_context=True,
            voice_file_id=None,
            document=None,
            is_private_chat=False,
            normalize_command=lambda text: None,
            strip_required_prefix=lambda text, prefixes, ignore_case: (True, ""),
        )

        self.assertEqual(result.prompt_input, "")
        self.assertIsNone(result.rejection_reason)

    def test_apply_required_prefix_gate_allows_bare_youtube_link_without_prefix(self) -> None:
        client = SimpleNamespace(channel_name="telegram")
        config = SimpleNamespace(
            required_prefixes=["@helper"],
            required_prefix_ignore_case=True,
            require_prefix_in_private=True,
        )

        result = runtime_routing.apply_required_prefix_gate(
            client=client,
            config=config,
            prompt_input="https://www.youtube.com/watch?v=yD5DFL3xPmo",
            has_reply_context=False,
            voice_file_id=None,
            document=None,
            is_private_chat=False,
            normalize_command=lambda text: None,
            strip_required_prefix=lambda text, prefixes, ignore_case: (False, text),
        )

        self.assertEqual(result.prompt_input, "https://www.youtube.com/watch?v=yD5DFL3xPmo")
        self.assertFalse(result.ignored)
        self.assertIsNone(result.rejection_reason)

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

    def test_apply_priority_keyword_routing_routes_browser_brain_requests(self) -> None:
        config = SimpleNamespace(keyword_routing_enabled=True)

        result = runtime_routing.apply_priority_keyword_routing(
            config=config,
            prompt_input="Server3 Browser open https://example.com and snapshot it",
            command=None,
            chat_id=1,
        )

        self.assertTrue(result.priority_keyword_mode)
        self.assertTrue(result.stateless)
        self.assertEqual(result.routed_event, "bridge.browser_brain_keyword_routed")
        self.assertIn("Server3 Browser Brain priority mode is active.", result.prompt_input)

    def test_apply_priority_keyword_routing_routes_youtube_links(self) -> None:
        config = SimpleNamespace(keyword_routing_enabled=True)

        result = runtime_routing.apply_priority_keyword_routing(
            config=config,
            prompt_input="https://www.youtube.com/watch?v=yD5DFL3xPmo\nsummarise this",
            command=None,
            chat_id=1,
        )

        self.assertTrue(result.priority_keyword_mode)
        self.assertTrue(result.stateless)
        self.assertEqual(result.route_kind, "youtube_link")
        self.assertEqual(result.route_value, "https://www.youtube.com/watch?v=yD5DFL3xPmo")
        self.assertEqual(result.routed_event, "bridge.youtube_link_auto_routed")
        self.assertEqual(result.prompt_input, "https://www.youtube.com/watch?v=yD5DFL3xPmo\nsummarise this")

    def test_apply_priority_keyword_routing_ignores_non_request_text_with_youtube_link(self) -> None:
        config = SimpleNamespace(keyword_routing_enabled=True)

        result = runtime_routing.apply_priority_keyword_routing(
            config=config,
            prompt_input="watch this https://www.youtube.com/watch?v=yD5DFL3xPmo",
            command=None,
            chat_id=1,
        )

        self.assertFalse(result.priority_keyword_mode)
        self.assertFalse(result.stateless)
        self.assertIsNone(result.route_kind)
        self.assertEqual(result.prompt_input, "watch this https://www.youtube.com/watch?v=yD5DFL3xPmo")


if __name__ == "__main__":
    unittest.main()
