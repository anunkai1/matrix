import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "ops" / "chat-routing" / "validate_chat_routing_contract.py"

spec = importlib.util.spec_from_file_location("chat_routing_contract", MODULE_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError("Failed to load chat routing contract module")
contract = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = contract
spec.loader.exec_module(contract)


class ChatRoutingContractTests(unittest.TestCase):
    def test_validate_contract_passes_for_matching_values(self):
        contract_env = {
            "CONTRACT_ALLOWED_CHAT_IDS": "2,1,1",
            "CONTRACT_TELEGRAM_ALLOW_PRIVATE_CHATS_UNLISTED": "true",
            "CONTRACT_TELEGRAM_REQUIRE_PREFIX_IN_PRIVATE": "false",
            "CONTRACT_WA_DM_ALWAYS_RESPOND": "true",
            "CONTRACT_WA_GROUP_TRIGGER_REQUIRED": "true",
            "CONTRACT_WA_ALLOWED_DMS": "",
            "CONTRACT_WA_ALLOWED_GROUPS": "",
        }
        telegram_env = {
            "TELEGRAM_ALLOWED_CHAT_IDS": "1,2",
            "TELEGRAM_ALLOW_PRIVATE_CHATS_UNLISTED": "1",
            "TELEGRAM_REQUIRE_PREFIX_IN_PRIVATE": "0",
        }
        whatsapp_env = {
            "WA_ALLOWED_CHAT_IDS": "2,1",
            "WA_DM_ALWAYS_RESPOND": "true",
            "WA_GROUP_TRIGGER_REQUIRED": "yes",
            "WA_ALLOWED_DMS": "",
            "WA_ALLOWED_GROUPS": "",
        }
        contract.validate_contract(contract_env, telegram_env, whatsapp_env)

    def test_validate_contract_raises_with_field_name_on_mismatch(self):
        contract_env = {
            "CONTRACT_ALLOWED_CHAT_IDS": "1,2,3",
            "CONTRACT_TELEGRAM_ALLOW_PRIVATE_CHATS_UNLISTED": "true",
            "CONTRACT_TELEGRAM_REQUIRE_PREFIX_IN_PRIVATE": "false",
            "CONTRACT_WA_DM_ALWAYS_RESPOND": "true",
            "CONTRACT_WA_GROUP_TRIGGER_REQUIRED": "true",
        }
        telegram_env = {
            "TELEGRAM_ALLOWED_CHAT_IDS": "1,2",
            "TELEGRAM_ALLOW_PRIVATE_CHATS_UNLISTED": "true",
            "TELEGRAM_REQUIRE_PREFIX_IN_PRIVATE": "false",
        }
        whatsapp_env = {
            "WA_ALLOWED_CHAT_IDS": "1,2,3",
            "WA_DM_ALWAYS_RESPOND": "true",
            "WA_GROUP_TRIGGER_REQUIRED": "true",
        }
        with self.assertRaises(contract.ValidationError) as context:
            contract.validate_contract(contract_env, telegram_env, whatsapp_env)
        self.assertIn("TELEGRAM_ALLOWED_CHAT_IDS", str(context.exception))

    def test_resolve_alert_targets_prefers_observer_over_architect(self):
        token, chat_ids = contract.resolve_alert_targets(
            observer_env={
                "RUNTIME_OBSERVER_TELEGRAM_BOT_TOKEN": "observer-token",
                "RUNTIME_OBSERVER_TELEGRAM_CHAT_IDS": "3,4",
            },
            architect_env={
                "TELEGRAM_BOT_TOKEN": "architect-token",
                "TELEGRAM_ALLOWED_CHAT_IDS": "1,2",
            },
        )
        self.assertEqual(token, "observer-token")
        self.assertEqual(chat_ids, ["3", "4"])


if __name__ == "__main__":
    unittest.main()
