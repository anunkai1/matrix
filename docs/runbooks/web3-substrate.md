# Web3 Substrate MVP

## Goal
- Build a reusable execution substrate for future Web3 agent work.
- Treat Polymarket as the first adapter, not the entire architecture.
- Keep the first version dry-run-first and policy-constrained.

## Current shape
- Python package: `/home/architect/matrix/src/web3_substrate`
- Example planner: `/home/architect/matrix/ops/web3_substrate/example_plan.py`
- Tests: `/home/architect/matrix/tests/web3_substrate/test_substrate.py`

## Design
- `Web3Policy`
  - allowlisted adapters
  - allowlisted protocols
  - allowlisted chains
  - allowlisted tokens
  - max USD notional
  - max slippage
  - global dry-run mode
- `Web3ExecutionSubstrate`
  - validates intents against policy
  - routes to a registered protocol adapter
  - returns a deterministic execution plan
- Adapters
  - `polymarket_bridge`
  - `uniswap`
  - `cowswap`

## Why this shape
- It keeps the LLM at the intent/planning layer.
- It keeps exact API requests and signing boundaries deterministic.
- It is reusable across future protocol adapters.

## Current MVP status
- Polymarket bridge planning is grounded in current official bridge endpoints:
  - `GET /supported-assets`
  - `POST /quote`
  - `POST /deposit`
- Uniswap planning covers:
  - quote
  - approval/permit preflight
  - swap calldata generation
- CoW planning covers:
  - orderbook preflight
  - sign order
  - submit order

## Example
```bash
python3 ops/web3_substrate/example_plan.py --scenario polymarket
python3 ops/web3_substrate/example_plan.py --scenario uniswap
python3 ops/web3_substrate/example_plan.py --scenario cowswap
```

## Next implementation steps
1. Add a signer abstraction so the executor can sign only allowlisted actions.
2. Add real HTTP client execution with typed responses for Polymarket and Uniswap.
3. Add approval/allowance tracking and transaction reconciliation.
4. Add a Telegram/CLI overseer runtime that can inspect and approve plans.
