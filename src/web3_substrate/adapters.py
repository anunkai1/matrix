"""Protocol adapters for planning constrained Web3 actions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .models import BridgeDepositIntent, ExecutionPlan, ExecutionStep, HttpRequestSpec, SwapIntent


class ProtocolAdapter(Protocol):
    name: str

    def supports(self, intent) -> bool:
        ...

    def plan(self, intent) -> ExecutionPlan:
        ...


@dataclass(frozen=True)
class PolymarketBridgeAdapter:
    name: str = "polymarket_bridge"
    base_url: str = "https://bridge.polymarket.com"

    def supports(self, intent) -> bool:
        return isinstance(intent, BridgeDepositIntent)

    def plan(self, intent: BridgeDepositIntent) -> ExecutionPlan:
        supported_assets = ExecutionStep(
            kind="http_request",
            description="Query supported source chains/tokens and minimum deposit amounts.",
            request=HttpRequestSpec(
                method="GET",
                url=f"{self.base_url}/supported-assets",
                note="Use this before funding so the executor can refuse unsupported assets instead of guessing.",
            ),
            requires_network=True,
        )
        bridge_quote = ExecutionStep(
            kind="http_request",
            description="Request a bridge quote into Polymarket collateral (USDC.e on Polygon).",
            request=HttpRequestSpec(
                method="POST",
                url=f"{self.base_url}/quote",
                headers={"Content-Type": "application/json"},
                json_body={
                    "fromAmountBaseUnit": intent.source_amount_base_units,
                    "fromChainId": str(intent.source_chain_id),
                    "fromTokenAddress": intent.source_token_address,
                    "recipientAddress": intent.recipient_wallet_address,
                    "toChainId": str(intent.destination_chain_id),
                    "toTokenAddress": intent.destination_token_address,
                },
                note="Official docs describe this quote request as the deterministic way to estimate the deposit path.",
            ),
            requires_network=True,
        )
        create_deposit = ExecutionStep(
            kind="http_request",
            description="Create deposit addresses for the Polymarket wallet.",
            request=HttpRequestSpec(
                method="POST",
                url=f"{self.base_url}/deposit",
                headers={"Content-Type": "application/json"},
                json_body={"address": intent.recipient_wallet_address},
                note="Returns blockchain-specific deposit addresses. The EVM address is the one to fund from Ethereum.",
            ),
            requires_network=True,
        )
        fund_step = ExecutionStep(
            kind="sign_and_send",
            description=(
                f"Send {intent.source_amount_base_units} base units of {intent.source_token_symbol} on "
                f"{intent.source_chain} from the executor wallet to the returned EVM deposit address."
            ),
            requires_signature=True,
            metadata={
                "source_chain": intent.source_chain,
                "source_token_symbol": intent.source_token_symbol,
                "executor_wallet_address": intent.executor_wallet_address,
                "recipient_wallet_address": intent.recipient_wallet_address,
                "destination_chain": intent.destination_chain,
                "destination_token_symbol": intent.destination_token_symbol,
            },
        )
        return ExecutionPlan(
            adapter=self.name,
            intent_kind="bridge_deposit",
            summary=(
                f"Bridge {intent.source_token_symbol} from {intent.source_chain} into "
                f"{intent.destination_token_symbol} on {intent.destination_chain} for Polymarket."
            ),
            steps=[supported_assets, bridge_quote, create_deposit, fund_step],
            notes=[
                "Polymarket trading collateral is USDC.e on Polygon.",
                "This plan is safe-by-default: it prepares and validates the bridge path before any signed transfer.",
            ],
        )


@dataclass(frozen=True)
class UniswapTradeAdapter:
    name: str = "uniswap"
    base_url: str = "https://trade-api.gateway.uniswap.org/v1"

    def supports(self, intent) -> bool:
        return isinstance(intent, SwapIntent) and intent.protocol.lower() == self.name

    def plan(self, intent: SwapIntent) -> ExecutionPlan:
        quote_step = ExecutionStep(
            kind="http_request",
            description="Request a simulated Uniswap quote for the proposed swap.",
            request=HttpRequestSpec(
                method="POST",
                url=f"{self.base_url}/quote",
                headers={"Content-Type": "application/json", "x-api-key": "<set-uniswap-api-key>"},
                json_body={
                    "type": "EXACT_INPUT",
                    "amount": intent.amount_base_units,
                    "tokenInChainId": intent.chain_id,
                    "tokenOutChainId": intent.chain_id,
                    "tokenIn": intent.token_in_address,
                    "tokenOut": intent.token_out_address,
                    "swapper": intent.wallet_address,
                    "generatePermitAsTransaction": False,
                    "slippageTolerance": intent.slippage_bps,
                    "autoSlippage": "DEFAULT",
                    "routingPreference": "BEST_PRICE",
                },
                note="The quote response can include simulation results and permit2 payloads when needed.",
            ),
            requires_network=True,
        )
        approval_step = ExecutionStep(
            kind="allowance_check",
            description="Check ERC-20 approval/Permit2 requirements before building calldata.",
            requires_network=True,
            metadata={"wallet_address": intent.wallet_address, "token_in": intent.token_in_address},
        )
        swap_step = ExecutionStep(
            kind="http_request",
            description="Turn a valid quote into swap calldata, then sign and broadcast it.",
            request=HttpRequestSpec(
                method="POST",
                url=f"{self.base_url}/swap",
                headers={"Content-Type": "application/json", "x-api-key": "<set-uniswap-api-key>"},
                json_body={
                    "quote": "<quote-response-from-step-1>",
                    "simulateTransaction": True,
                },
                note="The signed permit and refreshed gas settings should be attached here when required by the quote.",
            ),
            requires_network=True,
            requires_signature=True,
        )
        return ExecutionPlan(
            adapter=self.name,
            intent_kind="swap",
            summary=(
                f"Swap {intent.token_in_symbol} to {intent.token_out_symbol} on {intent.chain} via Uniswap."
            ),
            steps=[quote_step, approval_step, swap_step],
            notes=[
                "Use quote -> approval/permit -> swap as the deterministic execution sequence.",
                "Uniswap quote responses can include simulation failures; those should hard-stop execution.",
            ],
        )


@dataclass(frozen=True)
class CowSwapAdapter:
    name: str = "cowswap"
    orderbook_url: str = "https://api.cow.fi/mainnet/api"

    def supports(self, intent) -> bool:
        return isinstance(intent, SwapIntent) and intent.protocol.lower() == self.name

    def plan(self, intent: SwapIntent) -> ExecutionPlan:
        fee_step = ExecutionStep(
            kind="orderbook_preflight",
            description="Fetch fee/price estimates from the CoW orderbook before signing an order.",
            requires_network=True,
            metadata={
                "orderbook_url": self.orderbook_url,
                "chain": intent.chain,
                "token_in": intent.token_in_address,
                "token_out": intent.token_out_address,
            },
        )
        sign_order = ExecutionStep(
            kind="sign_order",
            description="Create and sign a CoW order for the desired token pair and limit constraints.",
            requires_signature=True,
            metadata={
                "wallet_address": intent.wallet_address,
                "token_in_symbol": intent.token_in_symbol,
                "token_out_symbol": intent.token_out_symbol,
                "slippage_bps": intent.slippage_bps,
            },
        )
        post_order = ExecutionStep(
            kind="submit_order",
            description="Post the signed order to the CoW orderbook and monitor fill/cancellation state.",
            requires_network=True,
            metadata={"orderbook_url": self.orderbook_url},
        )
        return ExecutionPlan(
            adapter=self.name,
            intent_kind="swap",
            summary=(
                f"Create a protected {intent.token_in_symbol}->{intent.token_out_symbol} order via CoW Swap."
            ),
            steps=[fee_step, sign_order, post_order],
            notes=[
                "CoW is orderbook-based: sign an order first, then submit it for batch-auction settlement.",
                "Unlike AMM routing, the substrate should track order state until fill, expiry, or cancellation.",
            ],
        )
