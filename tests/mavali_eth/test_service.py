import tempfile
import unittest
from pathlib import Path

import sys


ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from mavali_eth.config import MavaliEthConfig
from mavali_eth.models import CreatedWallet, SignedTransaction
from mavali_eth.service import MavaliEthService
from mavali_eth.store import MavaliEthStore


class FakeRpc:
    def __init__(self):
        self.chain_id = 1
        self.balance_wei = 2_500_000_000_000_000_000
        self.suggested_fee_wei = 4_000_000_000
        self.latest_block = 100
        self.nonce = 7
        self.sent = []
        self.blocks = {}
        self.receipts = {}

    def get_chain_id(self):
        return self.chain_id

    def get_balance_wei(self, address):
        return self.balance_wei

    def get_transaction_count(self, address):
        return self.nonce

    def get_suggested_max_fee_per_gas_wei(self):
        return self.suggested_fee_wei

    def estimate_transfer_gas(self, from_address, to_address, value_wei):
        return 21_000

    def send_raw_transaction(self, raw_tx_hex):
        self.sent.append(raw_tx_hex)
        return "0xsent"

    def get_latest_block_number(self):
        return self.latest_block

    def get_block_transactions(self, block_number):
        return list(self.blocks.get(block_number, []))

    def transaction_succeeded(self, tx_hash):
        return self.receipts.get(tx_hash, True)


class FakeSigner:
    def __init__(self):
        self.created = 0
        self.signed = []

    def create_wallet(self, passphrase):
        self.created += 1
        return CreatedWallet(
            address="0x1111111111111111111111111111111111111111",
            keystore_json='{"address":"1111111111111111111111111111111111111111"}',
        )

    def read_address(self, keystore_path):
        return "0x1111111111111111111111111111111111111111"

    def sign_transaction(self, keystore_path, passphrase, tx_dict):
        self.signed.append(tx_dict)
        return SignedTransaction(
            raw_tx_hex="0xraw",
            tx_hash="0xsigned",
            from_address="0x1111111111111111111111111111111111111111",
        )


def make_config(state_dir: str) -> MavaliEthConfig:
    return MavaliEthConfig(
        state_dir=state_dir,
        db_path=str(Path(state_dir) / "mavali_eth.sqlite3"),
        keystore_path=str(Path(state_dir) / "wallet.json"),
        keystore_passphrase="secret",
        rpc_url="http://example.invalid",
        chain_id=1,
        gas_cap_gwei=5,
        pending_action_expiry_minutes=10,
        confirmation_count=2,
        polling_interval_minutes=30,
        signer_python_bin="python3",
        signer_helper_script="/tmp/helper.py",
        telegram_bot_token="123:abc",
        telegram_api_base="https://api.telegram.org",
        telegram_owner_chat_id=123456789,
    )


class MavaliEthServiceTests(unittest.TestCase):
    def test_address_query_creates_wallet_and_returns_address(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            service = MavaliEthService(
                make_config(tmpdir),
                rpc=FakeRpc(),
                signer=FakeSigner(),
                store=MavaliEthStore(str(Path(tmpdir) / "db.sqlite3")),
            )
            text = service.handle_prompt("telegram:1", "what is my wallet address")
            self.assertIn("0x1111111111111111111111111111111111111111", text)

    def test_balance_query_returns_eth_balance(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            service = MavaliEthService(
                make_config(tmpdir),
                rpc=FakeRpc(),
                signer=FakeSigner(),
                store=MavaliEthStore(str(Path(tmpdir) / "db.sqlite3")),
            )
            text = service.handle_prompt("telegram:1", "what is my eth balance")
            self.assertIn("2.5 ETH", text)

    def test_send_request_creates_pending_confirmation_prompt(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = MavaliEthStore(str(Path(tmpdir) / "db.sqlite3"))
            service = MavaliEthService(
                make_config(tmpdir),
                rpc=FakeRpc(),
                signer=FakeSigner(),
                store=store,
            )
            text = service.handle_prompt(
                "telegram:1",
                "send 0.03 ETH to 0x2222222222222222222222222222222222222222",
            )
            self.assertIn("I am about to send 0.03 ETH", text)
            self.assertIn("configured maxFeePerGas cap is 5 gwei", text)
            self.assertIn("Reply confirm to execute", text)
            self.assertIsNotNone(store.get_pending_action("telegram:1"))

    def test_send_request_above_cap_mentions_override_confirmation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            rpc = FakeRpc()
            rpc.suggested_fee_wei = 8_000_000_000
            service = MavaliEthService(
                make_config(tmpdir),
                rpc=rpc,
                signer=FakeSigner(),
                store=MavaliEthStore(str(Path(tmpdir) / "db.sqlite3")),
            )
            text = service.handle_prompt(
                "telegram:1",
                "send 0.03 ETH to 0x2222222222222222222222222222222222222222",
            )
            self.assertIn("exceeds the configured cap", text)

    def test_confirm_executes_pending_transaction(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            rpc = FakeRpc()
            signer = FakeSigner()
            store = MavaliEthStore(str(Path(tmpdir) / "db.sqlite3"))
            service = MavaliEthService(
                make_config(tmpdir),
                rpc=rpc,
                signer=signer,
                store=store,
            )
            service.handle_prompt(
                "telegram:1",
                "send 0.03 ETH to 0x2222222222222222222222222222222222222222",
            )
            text = service.handle_prompt("telegram:1", "confirm")
            self.assertIn("Sent 0.03 ETH", text)
            self.assertIn("0xsent", text)
            self.assertEqual(len(rpc.sent), 1)
            self.assertEqual(len(signer.signed), 1)
            self.assertIsNone(store.get_pending_action("telegram:1"))

    def test_confirm_without_pending_action_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            service = MavaliEthService(
                make_config(tmpdir),
                rpc=FakeRpc(),
                signer=FakeSigner(),
                store=MavaliEthStore(str(Path(tmpdir) / "db.sqlite3")),
            )
            text = service.handle_prompt("telegram:1", "confirm")
            self.assertEqual(text, "There is no pending action to confirm.")

    def test_first_inbound_poll_sets_cursor_without_historic_notification(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            rpc = FakeRpc()
            service = MavaliEthService(
                make_config(tmpdir),
                rpc=rpc,
                signer=FakeSigner(),
                store=MavaliEthStore(str(Path(tmpdir) / "db.sqlite3")),
            )
            notifications = service.poll_inbound_transfers()
            self.assertEqual(notifications, [])

    def test_inbound_poll_notifies_once_for_new_confirmed_eth_transfer(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            rpc = FakeRpc()
            store = MavaliEthStore(str(Path(tmpdir) / "db.sqlite3"))
            service = MavaliEthService(
                make_config(tmpdir),
                rpc=rpc,
                signer=FakeSigner(),
                store=store,
            )
            service.poll_inbound_transfers()
            rpc.latest_block = 103
            tx = type(
                "Tx",
                (),
                {
                    "tx_hash": "0xinbound",
                    "from_address": "0x3333333333333333333333333333333333333333",
                    "to_address": "0x1111111111111111111111111111111111111111",
                    "value_wei": 40000000000000000,
                    "block_number": 102,
                },
            )()
            rpc.blocks[102] = [tx]
            rpc.receipts["0xinbound"] = True
            notifications = service.poll_inbound_transfers()
            self.assertEqual(len(notifications), 1)
            self.assertIn("0.04 ETH", notifications[0].message)
            notifications_again = service.poll_inbound_transfers()
            self.assertEqual(notifications_again, [])

