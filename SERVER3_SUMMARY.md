# Server3 Summary

Last updated: 2026-03-10 (AEST, +10:00)

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
- Server time standard for operations is Brisbane (`Australia/Brisbane`, AEST/UTC+10).

## Recent Changes (Rolling Max 8)
- 2026-03-10: hardened follow-up handling for replied media by teaching the shared bridge to reuse photo/document/voice payloads from replied-to messages, and teaching the Govorun WhatsApp Node transport to preserve quoted media metadata so later questions about the same image/file no longer depend only on a one-shot temp download.
- 2026-03-10: tightened Govorun WhatsApp reply brevity by updating the live Govorun runtime `AGENTS.md` plus the bridge `TELEGRAM_RESPONSE_STYLE_HINT`, with the tracked WhatsApp env example aligned to keep replies short by default unless more detail is requested.
- 2026-03-09: fully purged ASTER from Server3 by removing the live `aster-trader` runtime/user artifacts and the shared-core ASTER routing/code/docs/tests/templates so the remaining Telegram, Signal, and WhatsApp runtimes no longer carry dormant ASTER baggage.
- 2026-03-09: enabled always-on Architect Joplin sync by adding the `joplin-architect-sync` systemd service/timer, with the local profile `/home/architect/.config/joplin` now syncing to Nextcloud every 5 minutes even when no Joplin client is open.
- 2026-03-09: fixed `telegram-bridge-ci` after the Govorun AGENTS-only executor change by updating the executor regression tests to assert the new contract: prompts no longer embed `AGENTS.md` text and overlay executions now run from `TELEGRAM_RUNTIME_ROOT`.
- 2026-03-08: completed the shared-core overlay cutover for Server3 bridge runtimes by adding `src/telegram_bridge/runtime_paths.py`, teaching the bridge/executor to separate shared-core paths from per-runtime roots, adding `ops/runtime_overlays/sync_server3_runtime_overlays.py`, updating overlay unit env to carry `TELEGRAM_RUNTIME_ROOT`/`TELEGRAM_SHARED_CORE_ROOT`, live-syncing the overlay runtimes, handling Tank's existing `/home/tank/tankbot/src -> /home/architect/matrix/src` symlink layout safely, and verifying the major runtimes remained at expected state.
- 2026-03-08: continued the Phase 2 shared-core cleanup without live behavior changes by extracting pure prefix-gating and keyword-route resolution from `src/telegram_bridge/handlers.py` into `src/telegram_bridge/runtime_routing.py`, adding focused routing tests, and keeping handler behavior and exports compatible.
- 2026-03-08: continued the Phase 2 shared-core cleanup without live behavior changes by extracting assistant/profile and keyword-routing policy helpers from `src/telegram_bridge/handlers.py` into `src/telegram_bridge/runtime_profile.py`, keeping handler exports compatible, adding focused runtime-profile tests, and preserving the current env/routing/service contracts.
- 2026-03-08: started Phase 2 shared-core cleanup without changing live behavior by extracting bridge env parsing and runtime defaults from `src/telegram_bridge/main.py` into `src/telegram_bridge/runtime_config.py`, keeping `main.py` as the bootstrap path, adding focused config tests, and documenting the clearer shared-core boundary.
- 2026-03-08: added the canonical runtime manifest at `infra/server3-runtime-manifest.json` plus shared read-only inspection command `python3 ops/server3_runtime_status.py`, then repointed active docs to that operator-first inventory/status path without changing live runtime behavior.
- 2026-03-08: switched Govorun back to AGENTS-only politics control by fixing the shared executor to run Codex from `/home/govorun/govorunbot` instead of the shared repo root, removing the regex blocker path, adding optional `TELEGRAM_POLICY_RESET_MEMORY_ON_CHANGE` support, clearing the current Govorun memory/session state, and hardening the live `/home/govorun/govorunbot/AGENTS.md` politics rule so a clean direct `What happened in israel` run now refuses without searching.
- 2026-03-08: simplified the runtime observer cadence from every 5 minutes to once daily at `08:05` AEST while keeping `telegram_daily_summary` delivery mode, and updated the timer source-of-truth plus active docs to match the lower-noise operating model.
- 2026-03-08: added a compact operator-first runtime inventory to `SERVER3_SUMMARY.md` and mirrored it in `README.md` so fast health/readiness checks cover the active bridge, sibling runtimes, network, timers, and optional UI state without relying on scattered docs.
- 2026-03-08: fixed a post-restore off-repo runtime path-compatibility issue by restoring a legacy in-container download path alongside the current mount, then recreating the affected service and verifying retained payload metadata resumes cleanly against the host data again.

## Current Risks/Watchouts (Max 5)
- Tank keeps `/home/tank/tankbot/src` linked to the shared repo source tree; preserve `TELEGRAM_RUNTIME_ROOT=/home/tank/tankbot` in its unit/env so runtime identity does not collapse back to the shared repo root.
- Browser autoplay can still be blocked by client policy and may require UI fallback interactions.
- WhatsApp progress edit behavior relies on valid outbound key mappings; mismatch paths should be treated as warning conditions.
- Keep group allowlists aligned (`WA_ALLOWED_CHAT_IDS`/`WA_ALLOWED_GROUPS` with `TELEGRAM_ALLOWED_CHAT_IDS`) while managing DM admission separately via `WA_ALLOWED_DMS` and `TELEGRAM_ALLOW_PRIVATE_CHATS_UNLISTED`.
- Telegram/WhatsApp channels can still show transient API retries or reconnect churn; DNS-side retry risk is reduced via custom NordVPN DNS but should still be monitored during network instability.
- Runtime observer alert routing depends on `RUNTIME_OBSERVER_TELEGRAM_CHAT_IDS` (or Telegram env fallback) remaining valid for the active bot token.

## Archive Pointer
- `SERVER3_ARCHIVE.md` is the canonical long-term detailed history.
- For per-change rollout evidence, use `logs/changes/*.md`.
