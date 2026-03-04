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
- 2026-03-04: fixed WhatsApp progress-message spam by making Node `/messages/edit` strict (no fallback fresh-send on edit miss/failure) and stopping repeated WhatsApp progress edit retries in Python after first edit error; group prefix-required behavior is unchanged.
- 2026-03-04: added `SRO` keyword guidance to Telegram `/help` (`/h`) output so operator-facing help explicitly references Server3 Runtime Observer wording.
- 2026-03-04: added runtime observer daily-digest capability with new modes `telegram_daily_summary` and `telegram_alerts_daily`, local-time scheduling (`RUNTIME_OBSERVER_DAILY_SUMMARY_HOUR_LOCAL` + `RUNTIME_OBSERVER_DAILY_SUMMARY_MINUTE_LOCAL`), window sizing (`RUNTIME_OBSERVER_DAILY_SUMMARY_WINDOW_HOURS`, default `24`), and summary lines that include warn/critical occurrence counts per KPI.
- 2026-03-04: hardened Govorun WhatsApp media contract across Node transport + Python policy by normalizing inbound `text/caption/photo/voice/document`, tightening `/media` outbound validation (`media_type`, URL/local-file ref checks, local size limit), and updating `src/telegram_bridge/handlers.py` prompt/media extraction so captioned media is not downgraded to text-only; live runtime copies were synced to `/home/govorun/whatsapp-govorun/app` and `/home/govorun/govorunbot/src/telegram_bridge`, then both WhatsApp services were restarted healthy.
- 2026-03-04: tuned runtime observer Telegram edit-400 KPI to reduce low-volume false paging by adding `RUNTIME_OBSERVER_TELEGRAM_EDIT_MIN_ATTEMPTS` (default `20`) and suppressing `telegram_edit_400_rate` alert severity when edit attempts are below threshold; status/alert output now includes `min_attempts` and suppression flag.
- 2026-03-04: documented current WhatsApp summon aliases in runbook by updating `docs/runbooks/whatsapp-govorun-operations.md` Trigger policy to explicitly include `govorun` alongside existing Cyrillic triggers.
- 2026-03-04: completed Govorun WhatsApp number migration to `61433720167` via fresh Baileys auth-state rotation + relink, then added English summon alias `govorun` alongside `@говорун,говорун` in live `/etc/default/govorun-whatsapp-bridge` (`TELEGRAM_REQUIRED_PREFIXES`) and verified both WhatsApp services healthy after restart.
- 2026-03-04: enabled Phase-2 proactive runtime observer alerts to Telegram by extending `ops/runtime_observer/runtime_observer.py` with alert/recovery delivery + cooldown state, adding `notify-test`, wiring observer unit fallback to `/etc/default/telegram-architect-bridge`, and activating live `/etc/default/server3-runtime-observer` in `telegram_alerts` mode with explicit chat routing.

## Current Risks/Watchouts (Max 5)
- Browser autoplay can still be blocked by client policy and may require UI fallback interactions.
- WhatsApp progress edit behavior relies on valid outbound key mappings; mismatch paths should be treated as warning conditions.
- Keep `WA_ALLOWED_CHAT_IDS` (WhatsApp bridge) aligned with `TELEGRAM_ALLOWED_CHAT_IDS` (`/etc/default/govorun-whatsapp-bridge`) to avoid silent drops or policy leakage.
- Telegram/WhatsApp channels can show transient DNS/API retries or reconnect churn; services currently auto-recover but should be monitored during network instability.
- Runtime observer alert routing depends on `RUNTIME_OBSERVER_TELEGRAM_CHAT_IDS` (or Telegram env fallback) remaining valid for the active bot token.

## Archive Pointer
- `SERVER3_ARCHIVE.md` is the canonical long-term detailed history.
- For per-change rollout evidence, use `logs/changes/*.md`.
