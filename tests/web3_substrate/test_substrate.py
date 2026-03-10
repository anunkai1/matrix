import json
import sys
import unittest
from decimal import Decimal
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from web3_substrate import (  # noqa: E402
    BridgeDepositIntent,
    CowSwapAdapter,
    PolymarketBridgeAdapter,
    PolicyViolation,
    SwapIntent,
    UniswapTradeAdapter,
    Web3ExecutionSubstrate,
    Web3Policy,
)


def make_policy(**overrides):
    base = {
        "allowed_adapters": ["polymarket_bridge", "uniswap", "cowswap"],
        "allowed_protocols": ["polymarket_bridge", "uniswap", "cowswap"],
        "allowed_chains": ["ethereum", "polygon"],
        "allowed_tokens": ["usdc", "usdc.e", "usdt", "eth", "weth"],
        "max_notional_usd": Decimal("100"),
        "max_slippage_bps": 150,
        "dry_run_only": True,
    }
    base.update(overrides)
    return Web3Policy.from_lists(**base)


class Web3SubstrateTests(unittest.TestCase):
    def make_substrate(self, **policy_overrides):
        return Web3ExecutionSubstrate.with_adapters(
            policy=make_policy(**policy_overrides),
            adapters=[PolymarketBridgeAdapter(), UniswapTradeAdapter(), CowSwapAdapter()],
        )

    def test_polymarket_deposit_plan_contains_bridge_endpoints(self):
        substrate = self.make_substrate()
        intent = BridgeDepositIntent(
            source_chain="ethereum",
            source_chain_id=1,
            source_token_symbol="USDT",
            source_token_address="0xdAC17F958D2ee523a2206206994597C13D831ec7",
            source_amount_base_units="100000000",
            amount_usd=Decimal("100"),
            executor_wallet_address="0x1111111111111111111111111111111111111111",
            recipient_wallet_address="0x2222222222222222222222222222222222222222",
        )

        plan = substrate.plan(intent)

        self.assertEqual(plan.adapter, "polymarket_bridge")
        self.assertTrue(plan.dry_run_only)
        self.assertEqual(plan.steps[0].request.url, "https://bridge.polymarket.com/supported-assets")
        self.assertEqual(plan.steps[1].request.url, "https://bridge.polymarket.com/quote")
        self.assertEqual(plan.steps[2].request.url, "https://bridge.polymarket.com/deposit")
        self.assertTrue(plan.steps[3].requires_signature)

    def test_uniswap_swap_plan_builds_quote_and_swap_requests(self):
        substrate = self.make_substrate()
        intent = SwapIntent(
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

        plan = substrate.plan(intent)

        self.assertEqual(plan.adapter, "uniswap")
        self.assertEqual(plan.steps[0].request.url, "https://trade-api.gateway.uniswap.org/v1/quote")
        self.assertEqual(plan.steps[2].request.url, "https://trade-api.gateway.uniswap.org/v1/swap")
        self.assertTrue(plan.steps[2].requires_signature)

    def test_policy_rejects_slippage_above_limit(self):
        substrate = self.make_substrate(max_slippage_bps=50)
        intent = SwapIntent(
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

        with self.assertRaises(PolicyViolation):
            substrate.plan(intent)

    def test_policy_rejects_notional_above_cap(self):
        substrate = self.make_substrate(max_notional_usd=Decimal("25"))
        intent = BridgeDepositIntent(
            source_chain="ethereum",
            source_chain_id=1,
            source_token_symbol="USDT",
            source_token_address="0xdAC17F958D2ee523a2206206994597C13D831ec7",
            source_amount_base_units="100000000",
            amount_usd=Decimal("100"),
            executor_wallet_address="0x1111111111111111111111111111111111111111",
            recipient_wallet_address="0x2222222222222222222222222222222222222222",
        )

        with self.assertRaises(PolicyViolation):
            substrate.plan(intent)

    def test_plan_serializes_to_json(self):
        substrate = self.make_substrate()
        intent = SwapIntent(
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

        plan = substrate.plan(intent)
        rendered = json.dumps(plan.to_dict(), sort_keys=True)

        self.assertIn("cowswap", rendered)
        self.assertIn("sign_order", rendered)


if __name__ == "__main__":
    unittest.main()
