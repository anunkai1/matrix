from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict


@dataclass(frozen=True)
class SendIntent:
    amount_wei: int
    amount_display: str
    destination_address: str


@dataclass(frozen=True)
class PendingAction:
    kind: str
    session_key: str
    created_at: float
    expires_at: float
    amount_wei: int
    amount_display: str
    destination_address: str
    estimated_gas_limit: int
    estimated_max_fee_per_gas_wei: int
    configured_gas_cap_wei: int
    above_gas_cap: bool

    def to_payload(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_payload(cls, payload: Dict[str, Any]) -> "PendingAction":
        return cls(
            kind=str(payload["kind"]),
            session_key=str(payload["session_key"]),
            created_at=float(payload["created_at"]),
            expires_at=float(payload["expires_at"]),
            amount_wei=int(payload["amount_wei"]),
            amount_display=str(payload["amount_display"]),
            destination_address=str(payload["destination_address"]),
            estimated_gas_limit=int(payload["estimated_gas_limit"]),
            estimated_max_fee_per_gas_wei=int(payload["estimated_max_fee_per_gas_wei"]),
            configured_gas_cap_wei=int(payload["configured_gas_cap_wei"]),
            above_gas_cap=bool(payload["above_gas_cap"]),
        )


@dataclass(frozen=True)
class CreatedWallet:
    address: str
    keystore_json: str


@dataclass(frozen=True)
class SignedTransaction:
    raw_tx_hex: str
    tx_hash: str
    from_address: str


@dataclass(frozen=True)
class InboundTransfer:
    tx_hash: str
    block_number: int
    sender_address: str
    recipient_address: str
    amount_wei: int

