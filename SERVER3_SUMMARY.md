# Server3 Summary

Last updated: 2026-03-08 (AEST, +10:00)

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
- Repo workflow: direct-to-`main` with mandatory commit/push proof for non-exempt changes
- Runtime observer daily Telegram summary now appends a plain-English operator line indicating whether attention is needed.
- Runtime observer daily health delivery is centralized through `staker_alerts_bot` to chat `211761499` (single destination).
- AsterTrader bot restart routing is pinned to `telegram-aster-trader-bridge.service` via `TELEGRAM_RESTART_UNIT` to prevent `/restart` from targeting Architect service defaults.
- AsterTrader `/restart` now works in-chat with least-privilege sudoers allowlist (`/etc/sudoers.d/aster-trader-bridge-restart`) scoped to `restart_and_verify.sh --unit telegram-aster-trader-bridge.service`.

## Runtime Inventory
- Canonical manifest: `infra/server3-runtime-manifest.json`
- Shared live status command: `python3 ops/server3_runtime_status.py`
- Covered runtime groups: Architect, Tank, ASTER, Govorun transport/bridge, Oracle transport/bridge, network layer, guardrail timers, optional UI.

## Operational Memory (Pinned)
- Routing keywords:
  - `HA ...` / `Home Assistant ...` for stateless HA operation mode
  - `Server3 TV ...` for desktop/browser control mode
  - `Nextcloud ...` for Nextcloud file/calendar operation mode
  - `Trade ...` / `Aster Trade ...` for ASTER futures trading mode (script-gated)
- Primary channel: `telegram`; WhatsApp runtime exists in parallel (`whatsapp-govorun-bridge.service` + `govorun-whatsapp-bridge.service`).
- Runtime observer is enabled on timer (`server3-runtime-observer.timer`) with Telegram daily summary mode (`RUNTIME_OBSERVER_MODE=telegram_daily_summary`) scheduled for `08:05` AEST.
- Govorun cross-channel routing contract guard is enforced by `ops/chat-routing/validate_chat_routing_contract.py` with canonical policy in `infra/contracts/server3-chat-routing.contract.env`; daily drift timer is `server3-chat-routing-contract-check.timer`.
- TV desktop/browser reliability is hardened with deterministic helpers, existing-window reuse, and autoplay fallback tooling (`wmctrl`, `xdotool`, `yt-dlp`).
- Tank defaults are hardened: DM prefix bypass in private chats, isolated Joplin profile/path, reasoning effort `low`.
- `astertrader` shell launcher is live for user `aster-trader`; it runs full-access Codex against ASTER Telegram memory bucket `tg:211761499` by default, backed by `/home/aster-trader/.local/state/telegram-aster-trader-bridge/memory.sqlite3`.
- Architect Telegram + CLI now share one neutral memory identity on Server3 via `shared:architect:main`; the shared bucket merges the existing Architect Telegram chats and CLI history while starting a fresh unified Codex session thread.
- Govorun WhatsApp behavior is env-tunable: progress wording, busy-lock wording, and reply-tone guidance are configured via `/etc/default/govorun-whatsapp-bridge`.
- Server time standard for operations is Brisbane (`Australia/Brisbane`, AEST/UTC+10).

## Recent Changes (Rolling Max 8)
- 2026-03-08: added the canonical runtime manifest at `infra/server3-runtime-manifest.json` plus shared read-only inspection command `python3 ops/server3_runtime_status.py`, then repointed active docs to that operator-first inventory/status path without changing live runtime behavior.
- 2026-03-08: hardened Govorun politics enforcement after logs showed a fresh post-patch WhatsApp request still answered current affairs; added a pre-executor `TELEGRAM_BLOCKED_PROMPT_REGEX`/`TELEGRAM_BLOCKED_PROMPT_MESSAGE` gate in the bridge, synced the full live `src/telegram_bridge` runtime back to repo parity after a partial-file deploy exposed version skew, and verified the blocked-topic path now refuses `What happened in israel` before Codex execution.
- 2026-03-08: simplified the runtime observer cadence from every 5 minutes to once daily at `08:05` AEST while keeping `telegram_daily_summary` delivery mode, and updated the timer source-of-truth plus active docs to match the lower-noise operating model.
- 2026-03-08: added a compact operator-first runtime inventory to `SERVER3_SUMMARY.md` and mirrored it in `README.md` so fast health/readiness checks cover Architect, Tank, ASTER, Govorun, Oracle Signal, network, timers, and optional UI state without relying on scattered docs.
- 2026-03-08: refined the Govorun runtime politics boundary to use a warm, casual "tired of politics, let's talk about something better" tone, documented the rule in the WhatsApp Govorun runbook, and updated the live `/home/govorun/govorunbot/AGENTS.md` prompt file that the service watches for policy changes.
- 2026-03-08: fixed a post-restore off-repo runtime path-compatibility issue by restoring a legacy in-container download path alongside the current mount, then recreating the affected service and verifying retained payload metadata resumes cleanly against the host data again.
- 2026-03-08: restored a local-only runtime stack from retained on-disk host data/config outside git after earlier cleanup removed live availability too broadly; recreated the off-repo compose + boot path, verified the requested local web endpoints respond again, and kept the runtime separate from tracked project source.
- 2026-03-08: applied live ASTER trader env tuning by setting `ASTER_BACKBURNER_LEVERAGE=10` in `/etc/default/telegram-aster-trader-bridge`, restarting `telegram-aster-trader-bridge.service`, and verifying the new process environment loaded the updated value.

## Current Risks/Watchouts (Max 5)
- Browser autoplay can still be blocked by client policy and may require UI fallback interactions.
- WhatsApp progress edit behavior relies on valid outbound key mappings; mismatch paths should be treated as warning conditions.
- Keep group allowlists aligned (`WA_ALLOWED_CHAT_IDS`/`WA_ALLOWED_GROUPS` with `TELEGRAM_ALLOWED_CHAT_IDS`) while managing DM admission separately via `WA_ALLOWED_DMS` and `TELEGRAM_ALLOW_PRIVATE_CHATS_UNLISTED`.
- Telegram/WhatsApp channels can still show transient API retries or reconnect churn; DNS-side retry risk is reduced via custom NordVPN DNS but should still be monitored during network instability.
- Runtime observer alert routing depends on `RUNTIME_OBSERVER_TELEGRAM_CHAT_IDS` (or Telegram env fallback) remaining valid for the active bot token.

## Archive Pointer
- `SERVER3_ARCHIVE.md` is the canonical long-term detailed history.
- For per-change rollout evidence, use `logs/changes/*.md`.
