# Server3 Summary

Last updated: 2026-03-18 (AEST, +10:00)

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
- Canonical runtime inventory now lives in `infra/server3-runtime-manifest.json`, with shared live inspection via `python3 ops/server3_runtime_status.py`
- Shared runtime core now lives in `/home/architect/matrix/src/telegram_bridge`; Tank/Govorun/Oracle run as per-runtime overlays, while Trinity now runs from its own dedicated code tree under `/home/trinity/trinitybot`.
- AgentSmith now runs as an isolated shared-core Telegram sibling runtime under `/home/agentsmith/agentsmithbot` with its own service/env/state.
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
- Tank defaults are hardened: DM prefix bypass in private chats, isolated Joplin profile/path, reasoning effort `low`.
- Architect memory now uses `shared:architect:main` as a shared archive identity while active Telegram chats write to per-chat live session keys under that namespace; live keys are merged back into the archive only on idle expiry, and CLI can still point directly at the shared archive.
- Local media services now use one canonical internal namespace: `/data/downloads` and `/data/media/...`; avoid reintroducing alternate path aliases like `/downloads`, `/tv`, `/movies`, or `/media`.
- Server3 state resilience now uses a monthly quiesced backup path (`server3-state-backup.service` / `server3-state-backup.timer`) that snapshots rebuild-critical host/app/runtime state to `/srv/external/server3-backups/state`; the Arr media payload stays on the external data disk and is intentionally excluded.
- Server time standard for operations is Brisbane (`Australia/Brisbane`, AEST/UTC+10).

## Recent Changes (Rolling Max 8)
- 2026-03-18: fixed a live `Mavali ETH` Telegram parsing bug where reply-context wrappers could cause prompts like `what's the ETH balance` to match quoted `wallet address` text from the replied-to message; `src/mavali_eth/service.py` now extracts the current user-message segment before intent matching, the regression test suite was updated, and `telegram-mavali-eth-bridge.service` was restarted on the fixed code.
- 2026-03-18: rolled out the live `Mavali ETH` runtime on Server3 by provisioning the `mavali_eth` user/root, installing the shared-core overlay shims and dedicated signing venv, staging the wallet keystore into `/home/mavali_eth/.local/state/telegram-mavali-eth-bridge/wallet.json`, writing `/etc/default/telegram-mavali-eth-bridge` with owner chat `211761499`, starting `telegram-mavali-eth-bridge.service`, enabling `mavali-eth-receipt-monitor.timer`, verifying CLI wallet/balance/gas reads, and sending a Telegram deployment smoke message to the owner chat; temporary RPC is `https://mainnet.gateway.tenderly.co`.
- 2026-03-18: changed Architect's shared Telegram memory behavior so `TELEGRAM_SHARED_MEMORY_KEY=shared:architect:main` now uses per-chat live session keys during active chats, reads the shared key as archive/background context, and merges each live key back into the shared archive only when the idle-expiry path clears that chat's session; this stops DM/group topic bleed during active sessions while preserving a combined archive for later sessions and CLI use.
- 2026-03-18: removed Govorun's remaining explicit default reply-length instructions from both the live runtime policy at `/home/govorun/govorunbot/AGENTS.md` and the active WhatsApp bridge env `/etc/default/govorun-whatsapp-bridge`, then restarted `govorun-whatsapp-bridge.service` so response length is no longer pinned there either.
- 2026-03-18: centralized trusted runtime Codex auth on Server3 behind one canonical shared file at `/etc/server3-codex/auth.json` with per-user `~/.codex/auth.json` symlinks managed by the new `ops/codex/install_shared_auth.sh` helper, keeping per-user history/state/config separate while making quota/auth behavior consistent across the runtime users.
- 2026-03-18: taught the shared bridge to surface known Codex executor quota failures directly to chat users instead of collapsing them into the generic `Execution failed` message, and to skip pointless automatic retry on that non-retriable path.
- 2026-03-18: widened bare-YouTube-link lightweight request matching so common follow-up phrasing like `summarise this` now still triggers the transcript-first YouTube auto-route instead of falling back to the generic executor path.
- 2026-03-18: added the new Telegram runtime `AgentSmith` as an isolated shared-core overlay with service `telegram-agentsmith-bridge.service`, runtime root `/home/agentsmith/agentsmithbot`, runtime-local AGENTS identity, private-chat allowlist `211761499`, and restore/restart coverage.

## Current Risks/Watchouts (Max 5)
- The external USB HDD at `/srv/external/server3-arr` is now the live Arr data disk for both `downloads` and `media`; avoid unplugging it while Server3 is running, and treat any future disk replacement as a full data-plane migration rather than a casual hot-swap.
- The monitoring stack binds Grafana specifically to `192.168.0.148:3000`; if Server3's LAN IP changes, update `/etc/default/server3-monitoring` and restart `server3-monitoring.service`.
- The new Server3 backup path is local-only on the attached USB backup disk at `/srv/external/server3-backups`; if the host and that backup disk are lost together, the rebuild path is gone.
- Tank keeps `/home/tank/tankbot/src` linked to the shared repo source tree; preserve `TELEGRAM_RUNTIME_ROOT=/home/tank/tankbot` in its unit/env so runtime identity does not collapse back to the shared repo root.
- `Mavali ETH` is live on a temporary public Ethereum RPC (`https://mainnet.gateway.tenderly.co`); replace it with a dedicated authenticated provider before treating the wallet runtime as durable production infrastructure.

## Archive Pointer
- `SERVER3_ARCHIVE.md` is the canonical long-term detailed history.
- For per-change rollout evidence, use `logs/changes/*.md`.
