# Server3 Summary

Last updated: 2026-03-13 (AEST, +10:00)

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
- Shared runtime core now lives in `/home/architect/matrix/src/telegram_bridge`; Tank/Govorun/Oracle run as per-runtime overlays with preserved service names, env paths, AGENTS, and state roots.
- Repo workflow: direct-to-`main` with mandatory commit/push proof for non-exempt changes
- Runtime observer daily Telegram summary now appends a plain-English operator line indicating whether attention is needed.
- Runtime observer daily health delivery is centralized through `staker_alerts_bot` to chat `211761499` (single destination).

## Runtime Inventory
- Canonical manifest: `infra/server3-runtime-manifest.json`
- Shared live status command: `python3 ops/server3_runtime_status.py`
- Covered runtime groups: Architect, Tank, Govorun transport/bridge, Oracle transport/bridge, network layer, guardrail timers, optional UI.

## Operational Memory (Pinned)
- Routing keywords:
  - `HA ...` / `Home Assistant ...` for stateless HA operation mode
  - `Server3 TV ...` for desktop/browser control mode
  - `Nextcloud ...` for Nextcloud file/calendar operation mode
- Primary channel: `telegram`; WhatsApp runtime exists in parallel (`whatsapp-govorun-bridge.service` + `govorun-whatsapp-bridge.service`).
- Runtime observer is enabled on timer (`server3-runtime-observer.timer`) with Telegram daily summary mode (`RUNTIME_OBSERVER_MODE=telegram_daily_summary`) scheduled for `08:05` AEST.
- Govorun cross-channel routing contract guard is enforced by `ops/chat-routing/validate_chat_routing_contract.py` with canonical policy in `infra/contracts/server3-chat-routing.contract.env`; daily drift timer is `server3-chat-routing-contract-check.timer`.
- TV desktop/browser reliability is hardened with deterministic helpers, existing-window reuse, and autoplay fallback tooling (`wmctrl`, `xdotool`, `yt-dlp`).
- Tank defaults are hardened: DM prefix bypass in private chats, isolated Joplin profile/path, reasoning effort `low`.
- Architect Telegram + CLI now share one neutral memory identity on Server3 via `shared:architect:main`; the shared bucket merges the existing Architect Telegram chats and CLI history while starting a fresh unified Codex session thread.
- Govorun WhatsApp behavior is env-tunable: progress wording, busy-lock wording, and reply-tone guidance are configured via `/etc/default/govorun-whatsapp-bridge`.
- Local media services now use one canonical internal namespace: `/data/downloads` and `/data/media/...`; avoid reintroducing alternate path aliases like `/downloads`, `/tv`, `/movies`, or `/media`.
- Server time standard for operations is Brisbane (`Australia/Brisbane`, AEST/UTC+10).

## Recent Changes (Rolling Max 8)
- 2026-03-13: added the official `Node Exporter Full` Grafana dashboard (`gnetId=1860`, revision `42`) to the LAN-only Server3 monitoring stack and verified it is live in the `Server3` folder alongside `Server3 Node Overview`.
- 2026-03-13: deployed a LAN-only Server3 monitoring stack with `server3-monitoring.service`, Dockerized `node_exporter` + Prometheus + Grafana, a provisioned `Server3 Node Overview` dashboard, Grafana bound to `192.168.0.148:3000`, Prometheus bound to `127.0.0.1:9090`, and live config in `/etc/default/server3-monitoring`.
- 2026-03-11: implemented the first `mavali_eth` MVP code path in the shared repo by adding a deterministic Ethereum wallet engine plugin, shared SQLite pending/ledger state, JSON-RPC wallet reads, signer-helper integration, a CLI surface, a receipt-monitor script, runtime env/unit/timer templates, and an operator runbook; the spec now reflects that `mavali_eth` is repo-implemented and live rollout is pending real env/RPC provisioning on Server3.
- 2026-03-11: pinned the remaining `mavali_eth` planning decisions by defining inbound ETH as `2` confirmations, pinning the Telegram owner env field, defining strict raw `0x...` address parsing, and defining the mandatory transaction-confirmation prompt fields in both the human spec and the contract.
- 2026-03-11: completed a final local media cleanup pass by aligning the downloader's remaining default save-path fields with `/data/downloads`, removing an empty orphan movie-library folder, and pruning stale duplicate catalog rows so the active library tree now has one row per live media path.
- 2026-03-11: completed the local media path normalization end to end by moving the catalog service from `/media` to `/data/media`, updating persisted library paths, and verifying the downloader, importers, request service, and catalog all respond cleanly with the library now indexed only under `/data/media/...`.
- 2026-03-10: completed a second-pass recovery of the local library stack after the importer path repair by clearing a bad Docker runtime state, restoring the downloader, indexer, importer, request, and catalog services, and verifying the recovered `Survivor AU` episodes 7 and 8 now exist in the live library paths and are indexed by the catalog; remaining importer warnings on the recovered backlog are duplicate-destination notices rather than broken import paths.
- 2026-03-10: repaired a Server3 download/import path drift by restoring legacy `/data/...` compatibility mounts for the local library importers, then backfilled previously downloaded valid episodes into the live library paths so the catalog can see them again.
- 2026-03-10: added a planning-only spec at `docs/specs/server3-browser-automation-mvp.md` for an OpenClaw-style browser-control layer on Server3, capturing the intended scope, architecture, rationale, and next actions before any implementation work starts.
- 2026-03-10: clarified the `mavali_eth` planning split so `docs/specs/mavali-eth-mvp.md` now acts as the human/operator planning doc with decisions, rationale, and next actions, while `infra/contracts/mavali-eth-mvp.contract.yaml` stays limited to the current agreed runtime behavior.

## Current Risks/Watchouts (Max 5)
- The monitoring stack binds Grafana specifically to `192.168.0.148:3000`; if Server3's LAN IP changes, update `/etc/default/server3-monitoring` and restart `server3-monitoring.service`.
- `mavali_eth` is implemented in-repo but not provisioned live; its signing path depends on a dedicated venv/helper (`ops/mavali_eth/install_runtime_venv.sh` + `ops/mavali_eth/eth_account_helper.py`) and is not available until that runtime is installed.
- Tank keeps `/home/tank/tankbot/src` linked to the shared repo source tree; preserve `TELEGRAM_RUNTIME_ROOT=/home/tank/tankbot` in its unit/env so runtime identity does not collapse back to the shared repo root.
- WhatsApp progress edit behavior relies on valid outbound key mappings; mismatch paths should be treated as warning conditions.
- Keep group allowlists aligned (`WA_ALLOWED_CHAT_IDS`/`WA_ALLOWED_GROUPS` with `TELEGRAM_ALLOWED_CHAT_IDS`) while managing DM admission separately via `WA_ALLOWED_DMS` and `TELEGRAM_ALLOW_PRIVATE_CHATS_UNLISTED`.

## Archive Pointer
- `SERVER3_ARCHIVE.md` is the canonical long-term detailed history.
- For per-change rollout evidence, use `logs/changes/*.md`.
