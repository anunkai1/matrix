#!/usr/bin/env python3
"""Render a dry-run execution plan for the new Web3 substrate."""

from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from web3_substrate import (  # noqa: E402
    BridgeDepositIntent,
    CowSwapAdapter,
    PolymarketBridgeAdapter,
    SwapIntent,
    UniswapTradeAdapter,
    Web3ExecutionSubstrate,
    Web3Policy,
)


def build_substrate() -> Web3ExecutionSubstrate:
    policy = Web3Policy.from_lists(
        allowed_adapters=["polymarket_bridge", "uniswap", "cowswap"],
        allowed_protocols=["polymarket_bridge", "uniswap", "cowswap"],
        allowed_chains=["ethereum", "polygon"],
        allowed_tokens=["usdc", "usdc.e", "usdt", "eth", "weth"],
        max_notional_usd=Decimal("100"),
        max_slippage_bps=150,
        dry_run_only=True,
    )
    return Web3ExecutionSubstrate.with_adapters(
        policy=policy,
        adapters=[PolymarketBridgeAdapter(), UniswapTradeAdapter(), CowSwapAdapter()],
    )


def build_intent(name: str):
    if name == "polymarket":
        return BridgeDepositIntent(
            source_chain="ethereum",
            source_chain_id=1,
            source_token_symbol="USDT",
            source_token_address="0xdAC17F958D2ee523a2206206994597C13D831ec7",
            source_amount_base_units="100000000",
            amount_usd=Decimal("100"),
            executor_wallet_address="0x1111111111111111111111111111111111111111",
            recipient_wallet_address="0x2222222222222222222222222222222222222222",
        )
    if name == "uniswap":
        return SwapIntent(
            protocol="uniswap",
            chain="ethereum",
            chain_id=1,
            wallet_address="0x1111111111111111111111111111111111111111",
            token_in_symbol="USDT",
            token_in_address="0xdAC17F958D2ee523a2206206994597C13D831ec7",
            token_out_symbol="WETH",
            token_out_address="0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
            amount_base_units="50000000",
            amount_usd=Decimal("50"),
            slippage_bps=100,
        )
    if name == "cowswap":
        return SwapIntent(
            protocol="cowswap",
            chain="ethereum",
            chain_id=1,
            wallet_address="0x1111111111111111111111111111111111111111",
            token_in_symbol="USDT",
            token_in_address="0xdAC17F958D2ee523a2206206994597C13D831ec7",
            token_out_symbol="WETH",
            token_out_address="0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
            amount_base_units="50000000",
            amount_usd=Decimal("50"),
            slippage_bps=100,
        )
    raise ValueError(f"unknown scenario: {name}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Preview a dry-run Web3 substrate plan.")
    parser.add_argument(
        "--scenario",
        choices=["polymarket", "uniswap", "cowswap"],
        default="polymarket",
        help="Which example scenario to render.",
    )
    args = parser.parse_args()

    substrate = build_substrate()
    plan = substrate.plan(build_intent(args.scenario))
    print(json.dumps(plan.to_dict(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
