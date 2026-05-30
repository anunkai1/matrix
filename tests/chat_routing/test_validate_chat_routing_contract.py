import importlib.util
import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock


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

    def test_resolve_alert_targets_falls_back_to_process_env_when_files_missing(self):
        ambient = {
            "RUNTIME_OBSERVER_TELEGRAM_BOT_TOKEN": "ambient-observer-token",
            "RUNTIME_OBSERVER_TELEGRAM_CHAT_IDS": "9,10",
            "TELEGRAM_BOT_TOKEN": "ambient-architect-token",
            "TELEGRAM_ALLOWED_CHAT_IDS": "1,2",
        }
        with mock.patch.dict(os.environ, ambient, clear=True):
            token, chat_ids = contract.resolve_alert_targets(observer_env=None, architect_env=None)
        self.assertEqual(token, "ambient-observer-token")
        self.assertEqual(chat_ids, ["9", "10"])

    def test_resolve_alert_targets_prefers_explicit_architect_env_over_ambient(self):
        ambient = {
            "RUNTIME_OBSERVER_TELEGRAM_BOT_TOKEN": "ambient-observer-token",
            "RUNTIME_OBSERVER_TELEGRAM_CHAT_IDS": "9,10",
        }
        with mock.patch.dict(os.environ, ambient, clear=True):
            token, chat_ids = contract.resolve_alert_targets(
                observer_env=None,
                architect_env={
                    "TELEGRAM_BOT_TOKEN": "architect-token",
                    "TELEGRAM_ALLOWED_CHAT_IDS": "1,2",
                },
            )
        self.assertEqual(token, "architect-token")
        self.assertEqual(chat_ids, ["1", "2"])

    def test_run_failure_alert_uses_explicit_env_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            contract_path = root / "contract.env"
            telegram_path = root / "telegram.env"
            whatsapp_path = root / "whatsapp.env"
            observer_path = root / "observer.env"
            architect_path = root / "architect.env"

            contract_path.write_text(
                "\n".join(
                    [
                        "CONTRACT_ALLOWED_CHAT_IDS=1,2,3",
                        "CONTRACT_TELEGRAM_ALLOW_PRIVATE_CHATS_UNLISTED=true",
                        "CONTRACT_TELEGRAM_REQUIRE_PREFIX_IN_PRIVATE=false",
                        "CONTRACT_WA_DM_ALWAYS_RESPOND=true",
                        "CONTRACT_WA_GROUP_TRIGGER_REQUIRED=true",
                    ]
                ),
                encoding="utf-8",
            )
            telegram_path.write_text(
                "\n".join(
                    [
                        "TELEGRAM_ALLOWED_CHAT_IDS=1,2",
                        "TELEGRAM_ALLOW_PRIVATE_CHATS_UNLISTED=true",
                        "TELEGRAM_REQUIRE_PREFIX_IN_PRIVATE=false",
                    ]
                ),
                encoding="utf-8",
            )
            whatsapp_path.write_text(
                "\n".join(
                    [
                        "WA_ALLOWED_CHAT_IDS=1,2,3",
                        "WA_DM_ALWAYS_RESPOND=true",
                        "WA_GROUP_TRIGGER_REQUIRED=true",
                    ]
                ),
                encoding="utf-8",
            )
            observer_path.write_text(
                "\n".join(
                    [
                        "RUNTIME_OBSERVER_TELEGRAM_BOT_TOKEN=observer-token",
                        "RUNTIME_OBSERVER_TELEGRAM_CHAT_IDS=3,4",
                    ]
                ),
                encoding="utf-8",
            )
            architect_path.write_text(
                "\n".join(
                    [
                        "TELEGRAM_BOT_TOKEN=architect-token",
                        "TELEGRAM_ALLOWED_CHAT_IDS=1,2",
                    ]
                ),
                encoding="utf-8",
            )

            args = contract.build_parser().parse_args(
                [
                    "--contract",
                    str(contract_path),
                    "--telegram-env",
                    str(telegram_path),
                    "--whatsapp-env",
                    str(whatsapp_path),
                    "--observer-env",
                    str(observer_path),
                    "--architect-env",
                    str(architect_path),
                    "--telegram-alert-on-fail",
                ]
            )

            stdout_buffer = io.StringIO()
            stderr_buffer = io.StringIO()
            with (
                mock.patch.dict(
                    os.environ,
                    {
                        "RUNTIME_OBSERVER_TELEGRAM_BOT_TOKEN": "ambient-observer-token",
                        "RUNTIME_OBSERVER_TELEGRAM_CHAT_IDS": "9,10",
                        "TELEGRAM_BOT_TOKEN": "ambient-architect-token",
                        "TELEGRAM_ALLOWED_CHAT_IDS": "7,8",
                    },
                    clear=True,
                ),
                mock.patch.object(contract, "send_telegram_alert") as send_alert,
                redirect_stdout(stdout_buffer),
                redirect_stderr(stderr_buffer),
            ):
                exit_code = contract.run(args)

            self.assertEqual(exit_code, 2)
            send_alert.assert_called_once()
            token, chat_ids, text = send_alert.call_args.args[:3]
            self.assertEqual(token, "observer-token")
            self.assertEqual(chat_ids, ["3", "4"])
            self.assertIn("Server3 chat-routing contract drift detected.", text)
            self.assertIn("TELEGRAM_ALLOWED_CHAT_IDS", text)


if __name__ == "__main__":
    unittest.main()
