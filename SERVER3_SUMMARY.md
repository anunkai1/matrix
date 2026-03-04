# Server3 Summary

Last updated: 2026-03-04 (AEST, +10:00)

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
- Repo workflow: direct-to-`main` with mandatory commit/push proof for non-exempt changes

## Operational Memory (Pinned)
- Routing keywords:
  - `HA ...` / `Home Assistant ...` for stateless HA operation mode
  - `Server3 TV ...` for desktop/browser control mode
  - `Nextcloud ...` for Nextcloud file/calendar operation mode
- Primary channel: `telegram`; WhatsApp runtime exists in parallel (`whatsapp-govorun-bridge.service` + `govorun-whatsapp-bridge.service`).
- Runtime observer is enabled on timer (`server3-runtime-observer.timer`) with Telegram proactive alert mode (`RUNTIME_OBSERVER_MODE=telegram_alerts`) and 30-minute reminder cooldown.
- TV desktop/browser reliability is hardened with deterministic helpers, existing-window reuse, and autoplay fallback tooling (`wmctrl`, `xdotool`, `yt-dlp`).
- Tank defaults are hardened: DM prefix bypass in private chats, isolated Joplin profile/path, reasoning effort `low`.
- Govorun WhatsApp progress depends on outbound message-key mapping for `/messages/edit`; compact elapsed wording is env-configured.
- Architect Google runtime integration is removed/disabled.
- Server time standard for operations is Brisbane (`Australia/Brisbane`, AEST/UTC+10).

## Recent Changes (Rolling Max 8)
- 2026-03-04: enabled Phase-2 proactive runtime observer alerts to Telegram by extending `ops/runtime_observer/runtime_observer.py` with alert/recovery delivery + cooldown state, adding `notify-test`, wiring observer unit fallback to `/etc/default/telegram-architect-bridge`, and activating live `/etc/default/server3-runtime-observer` in `telegram_alerts` mode with explicit chat routing.
- 2026-03-04: live-enabled `server3-runtime-observer.timer` on Server3 via `ops/runtime_observer/install_systemd.sh apply`, validated manual service run success and next scheduled trigger at `2026-03-04 12:10:00 AEST` (Phase-1 remains `collect_only`).
- 2026-03-04: added Phase-1 runtime observer control layer (`ops/runtime_observer/runtime_observer.py`) with KPI snapshot collection (`service_up`, `restart_count`, `telegram_retry_rate`, `telegram_edit_400_rate`, `wa_reconnect_rate`, `request_fail_rate`), plus systemd timer/service units and operator commands for current status + 24h summary; day-1 mode remains collect-only.
- 2026-03-04: prevented cross-group `Access denied` replies by adding upstream WhatsApp numeric allowlist support (`WA_ALLOWED_CHAT_IDS`) in `ops/whatsapp_govorun/bridge` and making non-allowlisted WhatsApp plugin requests silent-deny in `src/telegram_bridge/handlers.py`; live runtime now pins `WA_ALLOWED_CHAT_IDS=1434663945,335502052`.
- 2026-03-04: completed strict WhatsApp canonicalization cleanup by removing legacy `telegram-architect-whatsapp-bridge` unit/ops/env artifacts, adding canonical `govorun-whatsapp-bridge` env templates, and removing live alias symlinks from `/etc/systemd/system` and `/etc/default`.
- 2026-03-04: reduced active markdown redundancy by making `AGENTS.md` a minimal pointer to `ARCHITECT_INSTRUCTION.md`, trimming duplicated policy text in `README.md`, and consolidating repeated Govorun setup details in `docs/runbooks/telegram-whatsapp-dual-runtime.md` to reference the canonical ops runbook.
- 2026-03-04: drafted and activated `ARCHITECT_INSTRUCTION.md` as authoritative Server3 execution policy; aligned `AGENTS.md` to startup-checklist/pointer role and updated `README.md` policy references to remove authority ambiguity.
- 2026-03-04: addressed three follow-up code-review issues in WhatsApp/progress paths: made outbound edit-key cache dedupe-safe, enforced mapped-chat usage for `/messages/edit`, and replaced hardcoded compact elapsed wording with configurable env keys.

## Current Risks/Watchouts (Max 5)
- Browser autoplay can still be blocked by client policy and may require UI fallback interactions.
- WhatsApp progress edit behavior relies on valid outbound key mappings; mismatch paths should be treated as warning conditions.
- Keep `WA_ALLOWED_CHAT_IDS` (WhatsApp bridge) aligned with `TELEGRAM_ALLOWED_CHAT_IDS` (`/etc/default/govorun-whatsapp-bridge`) to avoid silent drops or policy leakage.
- Telegram/WhatsApp channels can show transient DNS/API retries or reconnect churn; services currently auto-recover but should be monitored during network instability.
- Runtime observer alert routing depends on `RUNTIME_OBSERVER_TELEGRAM_CHAT_IDS` (or Telegram env fallback) remaining valid for the active bot token.

## Archive Pointer
- `SERVER3_ARCHIVE.md` is the canonical long-term detailed history.
- For per-change rollout evidence, use `logs/changes/*.md`.
