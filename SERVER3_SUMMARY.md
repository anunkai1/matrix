# Server3 Summary

Last updated: 2026-03-22 (AEST, +10:00)

## Purpose
- Fast restart context optimized for execution speed, clarity, and recovery value.
- Keep this file compact and operator-first; move deep history to `SERVER3_ARCHIVE.md`.

## Summary Policy (Operator-First)
- Keep only items that materially improve execution speed, correctness, or recovery.
- Structure limits:
  - `Operational Memory (Pinned)`: 6-10 items
  - `Recent Changes (Rolling Max 8)`: newest high-value deltas only
  - `Current Risks/Watchouts (Max 5)`: active operational caveats only
- Do not trim by age alone; trim by reuse and operational impact.

## Current Snapshot
- Primary active component: `telegram-architect-bridge.service`
- Runtime pattern: Telegram long polling + local `codex exec`
- Core capabilities: text/photo/voice/document handling, per-chat memory persistence, optional persistent workers, optional canonical session model, safe queued `/restart`
- Browser Brain live mode is now `existing_session` on local CDP port `9223`; the visible `tv` Brave helper is the intended on-screen login path for sites like `x.com`.
- Telegram reply-context wrappers now use English labels (`Reply Context`, `Original Message Author`, `Message User Replied To`, `Current User Message`) while downstream parsers remain backward-compatible with older Russian wrappers.
- Canonical runtime inventory now lives in `infra/server3-runtime-manifest.json`, with shared live inspection via `python3 ops/server3_runtime_status.py`
- Shared runtime core now lives in `/home/architect/matrix/src/telegram_bridge`; Tank/Govorun/Oracle run as per-runtime overlays, while Trinity now runs from its own dedicated code tree under `/home/trinity/trinitybot`.
- AgentSmith now runs as an isolated shared-core Telegram sibling runtime under `/home/agentsmith/agentsmithbot` with its own service/env/state.
- Runtime personas now live canonically in `infra/runtime_personas`, companion runtime docs now live canonically in `docs/runtime_docs`, and the live runtime roots consume those tracked files through repo-backed symlinks verified by `bash ops/runtime_personas/check_runtime_repo_links.sh`.
- Repo workflow: direct-to-`main` with mandatory commit/push proof for non-exempt changes
- Runtime observer daily Telegram summary now appends a plain-English operator line indicating whether attention is needed.
- Runtime observer daily health delivery is centralized through `staker_alerts_bot` to chat `211761499` (single destination).

## Runtime Inventory
- Canonical manifest: `infra/server3-runtime-manifest.json`
- Shared live status command: `python3 ops/server3_runtime_status.py`
- Covered runtime groups: Architect, AgentSmith, Tank, Trinity, Govorun transport/bridge, Oracle transport/bridge, network layer, guardrail timers, optional UI.

## Operational Memory (Pinned)
- Routing keywords:
  - `HA ...` / `Home Assistant ...` for stateless HA operation mode
  - bare YouTube links for transcript-first YouTube analysis mode with `yt-dlp` captions first and local transcription fallback
  - `Server3 TV ...` for desktop/browser control mode
  - `Nextcloud ...` for Nextcloud file/calendar operation mode
- Primary channel: `telegram`; WhatsApp runtime exists in parallel (`whatsapp-govorun-bridge.service` + `govorun-whatsapp-bridge.service`).
- Runtime observer is enabled on timer (`server3-runtime-observer.timer`) with Telegram daily summary mode (`RUNTIME_OBSERVER_MODE=telegram_daily_summary`) scheduled for `08:05` AEST.
- Govorun cross-channel routing contract guard is enforced by `ops/chat-routing/validate_chat_routing_contract.py` with canonical policy in `infra/contracts/server3-chat-routing.contract.env`; daily drift timer is `server3-chat-routing-contract-check.timer`.
- TV desktop/browser reliability is hardened with deterministic helpers, existing-window reuse, and autoplay fallback tooling (`wmctrl`, `xdotool`, `yt-dlp`).
- Browser Brain `x.com`/manual-login recovery path is: keep Browser Brain in `existing_session` mode, start the visible TV-side Brave helper, let the user log in manually there if needed, then attach Browser Brain over local CDP; do not try to run Browser Brain itself headed on Server3.
- Tank defaults are hardened: DM prefix bypass in private chats, isolated Joplin profile/path, reasoning effort `low`.
- Runtime policy/doc drift should now be checked with `bash /home/architect/matrix/ops/runtime_personas/check_runtime_repo_links.sh` before assuming a live root has diverged from Git.
- Architect memory now uses `shared:architect:main` as a shared archive identity while active Telegram chats write to per-chat live session keys under that namespace; live keys are merged back into the archive only on idle expiry, and CLI can still point directly at the shared archive.
- Local media services now use one canonical internal namespace: `/data/downloads` and `/data/media/...`; avoid reintroducing alternate path aliases like `/downloads`, `/tv`, `/movies`, or `/media`.
- Server3 state resilience now uses a monthly quiesced backup path (`server3-state-backup.service` / `server3-state-backup.timer`) that snapshots rebuild-critical host/app/runtime state to `/srv/external/server3-backups/state`; the Arr media payload stays on the external data disk and is intentionally excluded.
- Server time standard for operations is Brisbane (`Australia/Brisbane`, AEST/UTC+10).

## Recent Changes (Rolling Max 8)
- 2026-03-22: added a direct mainnet Uniswap execution path to `mavali_eth` for immediate ERC20 swaps, wiring `swap ... on uniswap` through live route quoting, exact-amount approvals, optional ETH->WETH wrap, a fixed `0.50%` slippage ceiling, and a hard `15 gwei` gas-price cap so the runtime now has a true onchain swap engine for cases where CowSwap’s resting-order model is the wrong fit.
- 2026-03-23: hardened `mavali_eth` Uniswap execution after the Tenderly no-op incident by adding `eth_getCode` provider preflight checks, refusing to stage or confirm against an RPC that exposes empty router/factory/token code, centralizing transaction submission logic, caching ERC20 metadata reads, and treating below-minimum or zero-output receipts as failed executions instead of falsely reporting a confirmed swap.
- 2026-03-23: removed duplicated mainnet token catalogs from the `mavali_eth` CowSwap and Uniswap modules by extracting a shared token registry, so aliases like `link` / `chainlink`, symbol formatting, and decimals no longer drift independently across protocol adapters.
- 2026-03-23: extracted the remaining `mavali_eth` protocol-heavy confirmation flows into dedicated CowSwap and Polymarket action handlers, so `service.py` now delegates all three major protocol adapters instead of embedding their funded-path orchestration inline.
- 2026-03-23: extracted the `mavali_eth` Uniswap preview/confirm path into a dedicated `uniswap_actions.py` handler so `service.py` now delegates that protocol flow instead of carrying provider preflight, gas-cap checks, wrap/approve/swap orchestration, and output validation inline.
- 2026-03-23: extracted `mavali_eth` EIP-1559 submission and receipt-waiting into a dedicated transaction executor module so native sends, ERC20 actions, and protocol adapters now share one execution path instead of keeping that plumbing embedded in the main service class.
- 2026-03-22: corrected `mavali_eth` CowSwap semantics so `swap ... on cowswap` now uses website-style market-mode inputs (market-class appData plus optimal quote handling) while keeping `limit swap ... on cowswap` as an explicit orderbook option; live verification showed the corrected market-mode order shape posts successfully, but the test UID `0x425151bbcafdf170134abcf2a12ddfd1eb9b74c6fff9b58ec60322b8accf28c1c88325e86fb245ecd41673043e63c2359b9e350c69bfe9ce` still sat open until manual cancellation, so CoW remains unsuitable here if we require a guaranteed immediate-fill primitive.
- 2026-03-22: made `mavali_eth` execution-ready for the final Polymarket boundary by adding a real live-post helper path (`polymarket-post-market-order`) with reconciliation data, wiring `confirm` to use it only when the new `MAVALI_ETH_ENABLE_POLYMARKET_LIVE_POST` gate is explicitly enabled, and keeping the default deployed behavior below the funded-trade boundary while hardening post-attempt failure handling against duplicate submission.
- 2026-03-22: extended `mavali_eth` authenticated Polymarket visibility again by adding runtime commands for `show polymarket open orders` and `show polymarket recent trades`, wiring them through the existing authenticated signer/account-state path, and keeping the system below the funded-trade boundary while giving the operator live order/trade detail instead of counts only.
- 2026-03-22: simplified `mavali_eth` documentation strategy by adding a short current-state/operator doc at `docs/runbooks/mavali-eth-current-state.md` and explicitly demoting the larger specs/checklists back to supporting-reference status instead of treating every markdown file as a top-level operator document.
- 2026-03-22: narrowed `telegram-bridge-ci` to bridge-relevant paths by changing the workflow to watch only `src/telegram_bridge/**`, `src/architect_cli/**`, and `tests/telegram_bridge/**`, and by scoping its unit-test discovery to `tests/telegram_bridge` so unrelated `mavali_eth` test changes no longer retrigger the stale bridge lane while the bridge-suite cleanup remains separate work.
- 2026-03-22: extended `mavali_eth` further into the Polymarket execution path by teaching the helper/signer to build real signed market-order payloads from the live keystore, updating `confirm` on a Polymarket preview to stage that signed order in the execution journal without posting it, and keeping the funded-trade boundary intact while reducing the remaining live gap to the final post-order step.
- 2026-03-22: extended `mavali_eth` from Polymarket visibility into safe order-preparation by adding public CLOB orderbook lookup plus depth-based market-order preview commands (`show polymarket orderbook <market>`, `preview polymarket buy 5 yes on <market>`), staging those previews in the generic action/journal layer, and hard-stopping `confirm` at an approval gate so the runtime can inspect real book depth and collateral sufficiency without posting a funded order yet.
- 2026-03-22: expanded `mavali_eth` from ETH-only wallet handling into the first reusable Web3 substrate slice by adding generic contract-capable RPC helpers, ERC20 metadata/balance/allowance/transfer/approve primitives, generalized pending-action and execution-journal storage, inbound ERC20 receipt monitoring, a Polymarket API spike tool, and the first live read-only Polymarket runtime integration covering active-market listing, public event search, exact market detail, wallet-linked positions, closed positions, and total position value with focused unit coverage across `tests/mavali_eth/*` plus the bridge plugin test.

## Current Risks/Watchouts (Max 5)
- The external USB HDD at `/srv/external/server3-arr` is now the live Arr data disk for both `downloads` and `media`; avoid unplugging it while Server3 is running, and treat any future disk replacement as a full data-plane migration rather than a casual hot-swap.
- The monitoring stack binds Grafana specifically to `192.168.0.148:3000`; if Server3's LAN IP changes, update `/etc/default/server3-monitoring` and restart `server3-monitoring.service`.
- The new Server3 backup path is local-only on the attached USB backup disk at `/srv/external/server3-backups`; if the host and that backup disk are lost together, the rebuild path is gone.
- Tank keeps `/home/tank/tankbot/src` linked to the shared repo source tree; preserve `TELEGRAM_RUNTIME_ROOT=/home/tank/tankbot` in its unit/env so runtime identity does not collapse back to the shared repo root.
- `Mavali ETH` is live on a temporary public Ethereum RPC (`https://mainnet.gateway.tenderly.co`); replace it with a dedicated authenticated provider before treating the wallet runtime as durable production infrastructure.

## Archive Pointer
- `SERVER3_ARCHIVE.md` is the canonical long-term detailed history.
- For per-change rollout evidence, use `logs/changes/*.md`.
