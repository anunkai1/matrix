from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Callable, List, Optional

from .config import MavaliEthConfig
from .json_rpc import EthereumJsonRpcClient
from .models import InboundTransfer, PendingAction
from .parsing import AddressParseError, parse_send_intent
from .signer import SignerBackend, SubprocessSignerBackend
from .store import MavaliEthStore


ONE_GWEI = 1_000_000_000


def format_eth_amount(wei_value: int) -> str:
    text = format((Decimal(int(wei_value)) / Decimal("1000000000000000000")).normalize(), "f")
    return text or "0"


def format_gwei_amount(wei_value: int) -> str:
    text = format((Decimal(int(wei_value)) / Decimal("1000000000")).normalize(), "f")
    return text or "0"


@dataclass(frozen=True)
class InboundNotification:
    tx_hash: str
    message: str


class MavaliEthService:
    def __init__(
        self,
        config: MavaliEthConfig,
        *,
        rpc: Optional[EthereumJsonRpcClient] = None,
        signer: Optional[SignerBackend] = None,
        store: Optional[MavaliEthStore] = None,
        now_fn: Optional[Callable[[], float]] = None,
    ) -> None:
        self.config = config
        self.rpc = rpc or EthereumJsonRpcClient(config.rpc_url)
        self.signer = signer or SubprocessSignerBackend(config)
        self.store = store or MavaliEthStore(config.db_path)
        self.now_fn = now_fn or time.time

    def _now(self) -> float:
        return float(self.now_fn())

    def _ensure_chain_id(self) -> None:
        chain_id = self.rpc.get_chain_id()
        if chain_id != self.config.chain_id:
            raise RuntimeError(
                f"Wrong chain. Expected Ethereum mainnet chain id {self.config.chain_id}, got {chain_id}."
            )

    def ensure_wallet_address(self) -> str:
        stored = self.store.get_metadata("wallet_address")
        if stored:
            return stored.lower()

        keystore_path = Path(self.config.keystore_path)
        if keystore_path.exists():
            address = self.signer.read_address(str(keystore_path))
            self.store.set_metadata("wallet_address", address)
            return address

        if not self.config.keystore_passphrase:
            raise RuntimeError("MAVALI_ETH_KEYSTORE_PASSPHRASE is not configured.")

        created = self.signer.create_wallet(self.config.keystore_passphrase)
        keystore_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = keystore_path.with_suffix(".tmp")
        tmp_path.write_text(created.keystore_json, encoding="utf-8")
        os.chmod(tmp_path, 0o600)
        os.replace(tmp_path, keystore_path)
        self.store.set_metadata("wallet_address", created.address)
        return created.address

    def _wallet_balance_message(self) -> str:
        address = self.ensure_wallet_address()
        balance_wei = self.rpc.get_balance_wei(address)
        return f"Your ETH balance is {format_eth_amount(balance_wei)} ETH at {address}."

    def _wallet_address_message(self) -> str:
        address = self.ensure_wallet_address()
        return f"Your wallet address is {address}."

    def _funding_guidance_message(self) -> str:
        suggested_fee = self.rpc.get_suggested_max_fee_per_gas_wei()
        gas_cost_wei = 21_000 * max(suggested_fee, self.config.gas_cap_wei)
        return (
            f"A simple ETH transfer normally needs about 21000 gas. "
            f"At the current estimate that is about {format_eth_amount(gas_cost_wei)} ETH for gas. "
            f"The configured maxFeePerGas cap is {self.config.gas_cap_gwei} gwei."
        )

    def _help_message(self) -> str:
        return (
            "I can show your wallet address, show your ETH balance, estimate ETH needed for gas, "
            "and prepare native ETH sends on Ethereum mainnet. "
            "Example: `send 0.03 ETH to 0x...`"
        )

    def handle_prompt(self, session_key: str, prompt: str) -> str:
        text = " ".join((prompt or "").strip().split())
        if not text:
            return self._help_message()
        lowered = text.lower()

        if lowered == "confirm":
            return self.confirm_pending_action(session_key)

        if "wallet address" in lowered or lowered in {"address", "what is my address", "what is my wallet address"}:
            return self._wallet_address_message()

        if "balance" in lowered:
            return self._wallet_balance_message()

        if "gas" in lowered and any(token in lowered for token in ("need", "how much", "fund")):
            return self._funding_guidance_message()

        try:
            send_intent = parse_send_intent(text)
        except (ValueError, AddressParseError) as exc:
            return str(exc)
        if send_intent is not None:
            return self.prepare_send_action(session_key, send_intent.amount_wei, send_intent.amount_display, send_intent.destination_address)

        return self._help_message()

    def prepare_send_action(self, session_key: str, amount_wei: int, amount_display: str, destination_address: str) -> str:
        self._ensure_chain_id()
        from_address = self.ensure_wallet_address()
        gas_limit = self.rpc.estimate_transfer_gas(from_address, destination_address, amount_wei)
        suggested_max_fee = self.rpc.get_suggested_max_fee_per_gas_wei()
        expires_at = self._now() + (self.config.pending_action_expiry_minutes * 60)
        pending = PendingAction(
            kind="send_native_eth",
            session_key=session_key,
            created_at=self._now(),
            expires_at=expires_at,
            amount_wei=amount_wei,
            amount_display=amount_display,
            destination_address=destination_address,
            estimated_gas_limit=gas_limit,
            estimated_max_fee_per_gas_wei=suggested_max_fee,
            configured_gas_cap_wei=self.config.gas_cap_wei,
            above_gas_cap=suggested_max_fee > self.config.gas_cap_wei,
        )
        self.store.put_pending_action(pending)
        approx_gas_cost_wei = gas_limit * suggested_max_fee
        lines = [
            f"I am about to send {amount_display} ETH on Ethereum mainnet to {destination_address}.",
            (
                f"Estimated gas is about {format_gwei_amount(suggested_max_fee)} gwei "
                f"/ {format_eth_amount(approx_gas_cost_wei)} ETH."
            ),
            f"The configured maxFeePerGas cap is {self.config.gas_cap_gwei} gwei.",
        ]
        if pending.above_gas_cap:
            lines.append(
                "Current estimated gas exceeds the configured cap. "
                "Reply `confirm` only if you want me to proceed anyway with the current estimate."
            )
        lines.append(
            f"This confirmation expires in {self.config.pending_action_expiry_minutes} minutes. Reply confirm to execute."
        )
        return " ".join(lines)

    def confirm_pending_action(self, session_key: str) -> str:
        pending = self.store.get_pending_action(session_key, now=self._now())
        if pending is None:
            return "There is no pending action to confirm."
        if pending.kind != "send_native_eth":
            self.store.clear_pending_action(session_key)
            return "The pending action format is invalid and was cleared."

        self._ensure_chain_id()
        from_address = self.ensure_wallet_address()
        current_fee = self.rpc.get_suggested_max_fee_per_gas_wei()
        gas_limit = self.rpc.estimate_transfer_gas(from_address, pending.destination_address, pending.amount_wei)
        priority_fee = min(ONE_GWEI, current_fee)
        tx_dict = {
            "chainId": self.config.chain_id,
            "type": 2,
            "nonce": self.rpc.get_transaction_count(from_address),
            "to": pending.destination_address,
            "value": pending.amount_wei,
            "gas": gas_limit,
            "maxFeePerGas": current_fee,
            "maxPriorityFeePerGas": priority_fee,
        }
        if not self.config.keystore_passphrase:
            raise RuntimeError("MAVALI_ETH_KEYSTORE_PASSPHRASE is not configured.")
        signed = self.signer.sign_transaction(
            self.config.keystore_path,
            self.config.keystore_passphrase,
            tx_dict,
        )
        tx_hash = self.rpc.send_raw_transaction(signed.raw_tx_hex)
        self.store.record_outbound_transaction(
            tx_hash=tx_hash,
            session_key=session_key,
            destination_address=pending.destination_address,
            amount_wei=pending.amount_wei,
            gas_limit=gas_limit,
            max_fee_per_gas_wei=current_fee,
            created_at=self._now(),
        )
        self.store.clear_pending_action(session_key)
        return (
            f"Sent {pending.amount_display} ETH to {pending.destination_address}. "
            f"Tx hash: {tx_hash}"
        )

    def poll_inbound_transfers(self) -> List[InboundNotification]:
        address = self.ensure_wallet_address()
        latest_block = self.rpc.get_latest_block_number()
        confirmed_tip = latest_block - self.config.confirmation_count + 1
        if confirmed_tip < 0:
            return []

        last_checked_raw = self.store.get_metadata("last_checked_confirmed_block")
        if last_checked_raw is None:
            self.store.set_metadata("last_checked_confirmed_block", str(confirmed_tip))
            return []

        last_checked = int(last_checked_raw)
        if confirmed_tip <= last_checked:
            return []

        notifications: List[InboundNotification] = []
        for block_number in range(last_checked + 1, confirmed_tip + 1):
            for tx in self.rpc.get_block_transactions(block_number):
                if tx.to_address.lower() != address.lower():
                    continue
                if tx.value_wei <= 0:
                    continue
                if self.store.inbound_receipt_exists(tx.tx_hash):
                    continue
                if not self.rpc.transaction_succeeded(tx.tx_hash):
                    continue
                transfer = InboundTransfer(
                    tx_hash=tx.tx_hash,
                    block_number=tx.block_number,
                    sender_address=tx.from_address,
                    recipient_address=tx.to_address,
                    amount_wei=tx.value_wei,
                )
                self.store.record_inbound_receipt(transfer)
                notifications.append(
                    InboundNotification(
                        tx_hash=transfer.tx_hash,
                        message=(
                            f"Confirmed inbound ETH received: {format_eth_amount(transfer.amount_wei)} ETH "
                            f"from {transfer.sender_address}. Tx hash: {transfer.tx_hash}"
                        ),
                    )
                )

        self.store.set_metadata("last_checked_confirmed_block", str(confirmed_tip))
        return notifications
