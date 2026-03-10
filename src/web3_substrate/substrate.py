"""Top-level planner for constrained Web3 execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable

from .adapters import ProtocolAdapter
from .models import ExecutionPlan
from .policy import Web3Policy


@dataclass
class Web3ExecutionSubstrate:
    policy: Web3Policy
    adapters: Dict[str, ProtocolAdapter] = field(default_factory=dict)

    @classmethod
    def with_adapters(cls, policy: Web3Policy, adapters: Iterable[ProtocolAdapter]) -> "Web3ExecutionSubstrate":
        registry = {adapter.name.lower(): adapter for adapter in adapters}
        return cls(policy=policy, adapters=registry)

    def register_adapter(self, adapter: ProtocolAdapter) -> None:
        self.adapters[adapter.name.lower()] = adapter

    def plan(self, intent) -> ExecutionPlan:
        self.policy.assert_intent_allowed(intent)
        adapter_name = str(getattr(intent, "adapter_name", "")).strip().lower()
        adapter = self.adapters.get(adapter_name)
        if adapter is None:
            raise KeyError(f"no adapter registered for {adapter_name}")
        if not adapter.supports(intent):
            raise TypeError(f"adapter {adapter_name} does not support {type(intent).__name__}")

        plan = adapter.plan(intent)
        if self.policy.dry_run_only:
            return ExecutionPlan(
                adapter=plan.adapter,
                intent_kind=plan.intent_kind,
                summary=plan.summary,
                steps=plan.steps,
                dry_run_only=True,
                notes=list(plan.notes) + ["Global substrate policy is dry-run only."],
            )
        return plan
