# Mavali ETH MVP

Status: planning-only

## Document Role

This file is the planning and operator document for `mavali_eth`.

It should contain:

- decisions already made
- rationale for those decisions
- next actions before implementation

It should not try to act as the strict machine contract. That role belongs to [`infra/contracts/mavali-eth-mvp.contract.yaml`](/home/architect/matrix/infra/contracts/mavali-eth-mvp.contract.yaml).

## Purpose

Define the first usable version of `mavali_eth`: a dedicated Ethereum mainnet wallet bot/operator that is controlled through Telegram and CLI, uses plain-English interaction, and is designed to grow into a broader Web3 execution system later.

This document is human-readable and operator-focused. The strict runtime contract lives in [`infra/contracts/mavali-eth-mvp.contract.yaml`](/home/architect/matrix/infra/contracts/mavali-eth-mvp.contract.yaml).

## Decisions

## Product Shape

`mavali_eth` is not a general chat assistant and not yet a trading bot. For MVP it is a dedicated Ethereum mainnet wallet operator with:

- one isolated runtime/user
- one fresh long-lived wallet created on Server3
- one Telegram bot for private control
- one CLI surface with equivalent command capability
- one shared transaction ledger for both surfaces
- separate chat/session threads per surface

## MVP Scope

Included:

- create and persist a fresh Ethereum wallet on Server3
- unlock wallet automatically at service start using an encrypted key file plus env passphrase
- show wallet address
- show current ETH balance
- estimate funding guidance for gas
- accept natural-language ETH send requests
- restate intended action in plain English
- wait for explicit `confirm`
- send native ETH on Ethereum mainnet
- poll for inbound native ETH every 30 minutes
- notify only on newly detected confirmed inbound ETH
- report inbound sender address, amount, and tx hash
- support the same command model in Telegram and CLI

Excluded from MVP:

- ERC20 sends
- swaps
- approvals
- Uniswap execution
- bridging
- non-Ethereum chains
- arbitrary contract calls
- autonomous trading

## Runtime and Isolation

The MVP should run as an isolated runtime named `mavali_eth` with:

- dedicated Linux user: `mavali_eth`
- dedicated Telegram bot identity: `mavali_eth_bot`
- dedicated env file
- dedicated state directory
- dedicated logs
- dedicated systemd unit(s)
- shared codebase with the main `matrix` repo for the first version

Recommended runtime behavior:

- no prefix required in the owner's private Telegram chat
- only the owner's personal Telegram chat is allowlisted
- bot starts unlocked for remote usability
- bot can proactively report wallet address and current ETH balance on startup

## Control Model

The wallet is controlled only by direct owner-issued commands for MVP.

Command handling rules:

- natural language only
- read-only questions are supported
- if the request is ambiguous, ask follow-up questions
- if execution parameters are uncertain, ask for advice instead of guessing
- use raw `0x...` addresses only in MVP
- do not infer or resolve ENS names yet

Execution confirmation rules:

- every state-changing action must be restated in plain English first
- execution only proceeds after the literal confirmation token `confirm`
- confirmation applies only to the immediately preceding pending action
- a pending action expires after 10 minutes
- only one pending action may exist per session at a time

## Safety and Correctness

The owner explicitly wants a permissive wallet operator, but still requires correctness and predictability.

The MVP must prevent:

- malformed transactions
- wrong-chain execution
- hallucinated parameters
- user-surprising actions

The only hard execution caps requested for MVP are:

- gas cap, expressed in gwei
- slippage cap, retained in the contract for later swap support

When the gas cap would be exceeded:

- do not execute silently
- ask the owner whether to proceed

There is no broader token/protocol/address allowlist for MVP. The primary risk boundary is the small wallet bankroll used for testing.

## Startup and Unlocking

Wallet/key behavior:

- create a fresh wallet on Server3 during provisioning
- use one long-lived primary wallet for the runtime
- persist it unless manually rotated later
- store the wallet as an encrypted key file
- provide the decryption passphrase through env for MVP
- auto-unlock at service start

## Reporting and Observability

Telegram and CLI should share:

- same wallet
- same transaction ledger
- same wallet state

They should keep separate:

- chat/session threads
- pending-action confirmation scope

Inbound monitoring behavior:

- Ethereum mainnet only
- native ETH only
- confirmed receipts only
- polling cadence: every 30 minutes
- send a message only when a new confirmed inbound transfer is detected
- report:
  - sender address
  - amount
  - tx hash

## Example Interaction Shape

Read-only:

- "what is my wallet address"
- "what is my eth balance"
- "how much eth do I need for gas"

State-changing:

Owner:
`Send 0.03 ETH to 0xabc...`

Bot:
`I am about to send 0.03 ETH on Ethereum mainnet to 0xabc.... Estimated gas is X gwei / about Y ETH. Reply confirm within 10 minutes to execute.`

Owner:
`confirm`

Bot:
`Sent. Tx hash: 0x...`

## Rationale

Key rationale behind the MVP shape:

- keep the first cut narrow so implementation does not sprawl into a partial general Web3 system
- isolate runtime concerns early so wallet state, logs, env, and bot identity do not get entangled with existing bots
- use natural language plus explicit confirmation so the bot remains easy to operate remotely without silent execution
- keep the first financial surface to native ETH on Ethereum mainnet so the parser, signer, and receipt monitor stay simple
- treat bankroll size as the main risk boundary while still enforcing correctness, gas awareness, and confirmation discipline
- preserve expansion room so ERC20 support, approvals, swaps, and other EVM actions can be layered on later without replacing the core control model

## Next Actions

Before implementation starts, tighten the planning artifacts by resolving these points explicitly:

1. Define what `confirmed` means for inbound ETH reporting.
2. Define the exact gas-cap meaning, preferably `maxFeePerGas` in gwei.
3. Pin the Telegram owner allowlist field and where it will be supplied from.
4. Define strict raw-address parsing rules for natural-language send requests.
5. Define the mandatory fields that must appear in the bot's plain-English confirmation prompt.

## Expansion Path After MVP

The MVP is intentionally narrow so it can become the base for a broader Web3 execution system later.

Planned expansion order:

1. ERC20 balance and send support
2. exact-amount approvals
3. revoke approvals
4. Uniswap swaps
5. broader Ethereum wallet actions
6. additional EVM chains
7. protocol modules such as prediction markets and DEX integrations

## Source of Truth

For implementation behavior, prefer the structured contract in [`infra/contracts/mavali-eth-mvp.contract.yaml`](/home/architect/matrix/infra/contracts/mavali-eth-mvp.contract.yaml).

Use this spec for:

- planning discussion
- operator review
- rationale
- next actions and continuation context
