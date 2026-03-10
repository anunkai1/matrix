"""Safety/policy checks for Web3 execution planning."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Iterable, List


class PolicyViolation(ValueError):
    """Raised when an intent falls outside the configured execution policy."""


def _normalize_many(values: Iterable[str]) -> frozenset[str]:
    return frozenset(str(value).strip().lower() for value in values if str(value).strip())


@dataclass(frozen=True)
class Web3Policy:
    allowed_adapters: frozenset[str] = field(default_factory=frozenset)
    allowed_protocols: frozenset[str] = field(default_factory=frozenset)
    allowed_chains: frozenset[str] = field(default_factory=frozenset)
    allowed_tokens: frozenset[str] = field(default_factory=frozenset)
    max_notional_usd: Decimal = Decimal("100")
    max_slippage_bps: int = 150
    dry_run_only: bool = True

    @classmethod
    def from_lists(
        cls,
        *,
        allowed_adapters: Iterable[str],
        allowed_protocols: Iterable[str],
        allowed_chains: Iterable[str],
        allowed_tokens: Iterable[str],
        max_notional_usd: Decimal,
        max_slippage_bps: int = 150,
        dry_run_only: bool = True,
    ) -> "Web3Policy":
        return cls(
            allowed_adapters=_normalize_many(allowed_adapters),
            allowed_protocols=_normalize_many(allowed_protocols),
            allowed_chains=_normalize_many(allowed_chains),
            allowed_tokens=_normalize_many(allowed_tokens),
            max_notional_usd=max_notional_usd,
            max_slippage_bps=max_slippage_bps,
            dry_run_only=dry_run_only,
        )

    def validate_intent(self, intent) -> List[str]:
        violations: List[str] = []

        adapter_name = str(getattr(intent, "adapter_name", "")).strip().lower()
        if self.allowed_adapters and adapter_name not in self.allowed_adapters:
            violations.append(f"adapter_not_allowed:{adapter_name}")

        protocol_name = str(getattr(intent, "protocol_name", "")).strip().lower()
        if self.allowed_protocols and protocol_name not in self.allowed_protocols:
            violations.append(f"protocol_not_allowed:{protocol_name}")

        for chain in getattr(intent, "chain_names", ()):
            normalized_chain = str(chain).strip().lower()
            if self.allowed_chains and normalized_chain not in self.allowed_chains:
                violations.append(f"chain_not_allowed:{normalized_chain}")

        for token in getattr(intent, "token_symbols", ()):
            normalized_token = str(token).strip().lower()
            if self.allowed_tokens and normalized_token not in self.allowed_tokens:
                violations.append(f"token_not_allowed:{normalized_token}")

        estimated_notional = Decimal(str(getattr(intent, "estimated_notional_usd", "0")))
        if estimated_notional > self.max_notional_usd:
            violations.append(
                f"notional_too_large:{estimated_notional.normalize()}>{self.max_notional_usd.normalize()}"
            )

        requested_slippage = getattr(intent, "requested_slippage_bps", None)
        if requested_slippage is not None and int(requested_slippage) > int(self.max_slippage_bps):
            violations.append(f"slippage_too_large:{requested_slippage}>{self.max_slippage_bps}")

        return violations

    def assert_intent_allowed(self, intent) -> None:
        violations = self.validate_intent(intent)
        if violations:
            raise PolicyViolation("; ".join(violations))
