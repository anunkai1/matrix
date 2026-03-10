"""Domain models for a constrained Web3 execution substrate."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from decimal import Decimal
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class HttpRequestSpec:
    method: str
    url: str
    headers: Dict[str, str] = field(default_factory=dict)
    json_body: Optional[Dict[str, Any]] = None
    note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ExecutionStep:
    kind: str
    description: str
    request: Optional[HttpRequestSpec] = None
    requires_signature: bool = False
    requires_network: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        if self.request is not None:
            payload["request"] = self.request.to_dict()
        return payload


@dataclass(frozen=True)
class ExecutionPlan:
    adapter: str
    intent_kind: str
    summary: str
    steps: List[ExecutionStep]
    dry_run_only: bool = True
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "adapter": self.adapter,
            "intent_kind": self.intent_kind,
            "summary": self.summary,
            "dry_run_only": self.dry_run_only,
            "notes": list(self.notes),
            "steps": [step.to_dict() for step in self.steps],
        }


@dataclass(frozen=True)
class BridgeDepositIntent:
    source_chain: str
    source_chain_id: int
    source_token_symbol: str
    source_token_address: str
    source_amount_base_units: str
    amount_usd: Decimal
    executor_wallet_address: str
    recipient_wallet_address: str
    destination_chain: str = "polygon"
    destination_chain_id: int = 137
    destination_token_symbol: str = "USDC.e"
    destination_token_address: str = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"

    @property
    def adapter_name(self) -> str:
        return "polymarket_bridge"

    @property
    def protocol_name(self) -> str:
        return "polymarket_bridge"

    @property
    def chain_names(self) -> tuple[str, ...]:
        return (self.source_chain, self.destination_chain)

    @property
    def token_symbols(self) -> tuple[str, ...]:
        return (self.source_token_symbol, self.destination_token_symbol)

    @property
    def requested_slippage_bps(self) -> None:
        return None

    @property
    def estimated_notional_usd(self) -> Decimal:
        return self.amount_usd


@dataclass(frozen=True)
class SwapIntent:
    protocol: str
    chain: str
    chain_id: int
    wallet_address: str
    token_in_symbol: str
    token_in_address: str
    token_out_symbol: str
    token_out_address: str
    amount_base_units: str
    amount_usd: Decimal
    slippage_bps: int = 100

    @property
    def adapter_name(self) -> str:
        return self.protocol

    @property
    def protocol_name(self) -> str:
        return self.protocol

    @property
    def chain_names(self) -> tuple[str, ...]:
        return (self.chain,)

    @property
    def token_symbols(self) -> tuple[str, ...]:
        return (self.token_in_symbol, self.token_out_symbol)

    @property
    def requested_slippage_bps(self) -> int:
        return self.slippage_bps

    @property
    def estimated_notional_usd(self) -> Decimal:
        return self.amount_usd
