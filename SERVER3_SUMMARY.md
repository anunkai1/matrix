# Server3 Summary

Last updated: 2026-03-05 (AEST, +10:00)

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
- Runtime observer is enabled on timer (`server3-runtime-observer.timer`) with Telegram daily summary mode (`RUNTIME_OBSERVER_MODE=telegram_daily_summary`) scheduled for `08:05` AEST.
- TV desktop/browser reliability is hardened with deterministic helpers, existing-window reuse, and autoplay fallback tooling (`wmctrl`, `xdotool`, `yt-dlp`).
- Tank defaults are hardened: DM prefix bypass in private chats, isolated Joplin profile/path, reasoning effort `low`.
- Govorun WhatsApp behavior is env-tunable: progress wording, busy-lock wording, and reply-tone guidance are configured via `/etc/default/govorun-whatsapp-bridge`.
- Architect Google runtime integration is removed/disabled.
- Server time standard for operations is Brisbane (`Australia/Brisbane`, AEST/UTC+10).

## Recent Changes (Rolling Max 8)
- 2026-03-05: added configurable busy-lock response text via new `TELEGRAM_BUSY_MESSAGE` in bridge config loading (`src/telegram_bridge/main.py`) with regression coverage in `tests/telegram_bridge/test_bridge_core.py`; documented/env-templated for Govorun WhatsApp (`infra/env/govorun-whatsapp-bridge*.env*`, `docs/runbooks/whatsapp-govorun-operations.md`) and applied live to `/etc/default/govorun-whatsapp-bridge` with `govorun-whatsapp-bridge.service` restart so concurrent-request replies are now in Govorun character.
- 2026-03-05: hardened Govorun WhatsApp integration in repo with reliability fixes: channel-aware memory namespacing (`tg:` vs `wa:`) in Python handlers/memory usage, pairing-code redaction from Node auth logs, Node bridge media-file retention controls (`WA_FILE_MAX_TOTAL_BYTES`, `WA_FILE_RETENTION_SECONDS`) with startup + periodic cleanup, explicit API `400 invalid_json`/`413 request_too_large` handling, best-effort outbound quoted-reply support via `reply_to_message_id` mapping in Node (`/messages` + `/media`), safer message-edit targeting (only known outbound messages), and local outbound media send-path optimization (avoid full-file reads in-process); added regression tests in `tests/telegram_bridge/test_bridge_core.py` and updated WhatsApp env/runbook docs.
- 2026-03-05: scheduled monthly system package maintenance at `04:00` AEST via new `server3-monthly-apt-upgrade.service` + `server3-monthly-apt-upgrade.timer` (OnCalendar `*-*-01 04:00:00`) and installer `ops/system-maintenance/install_monthly_apt_upgrade_timer.sh`; runtime script `ops/system-maintenance/run_monthly_apt_upgrade.sh` runs `apt-get update` then `apt-get upgrade -y`.
- 2026-03-05: fixed WhatsApp reply-thread context handling by adding inbound `reply_to_message` normalization in Node bridge (`ops/whatsapp_govorun/bridge/src/common.mjs` + `index.mjs`) and prompt assembly in Python (`src/telegram_bridge/handlers.py`) so Govorun sees quoted/original message content (not only the new reply text); added regression tests in `tests/telegram_bridge/test_bridge_core.py`.
- 2026-03-05: finalized explicit tone rule for daily Govorun 09:00 WhatsApp message in code + runbook: fun/funny/light/warm/enjoyable, exactly one short fun fact, prefer funny/interesting history-culture, animals, science, space, wholesome stories, life hacks, avoid heavy topics, and no sarcasm at people; fixed short format `Доброе утро...` + `Даю справку: ...`.
- 2026-03-05: added daily Govorun WhatsApp uplift scheduler for `09:00` Brisbane time using new sender script `ops/whatsapp_govorun/send_daily_uplift.py` plus systemd units `infra/systemd/govorun-whatsapp-daily-uplift.service` + `.timer`, installer `ops/whatsapp_govorun/install_daily_uplift_timer.sh`, and live env `/etc/default/govorun-whatsapp-daily-uplift` targeting `Путиловы` group JID.
- 2026-03-05: fixed WhatsApp 1:1 non-reply path by allowing private chats outside numeric allowlist when explicitly enabled (`TELEGRAM_ALLOW_PRIVATE_CHATS_UNLISTED=true`) in Python allowlist gating (`src/telegram_bridge/handlers.py`) and by scoping Node `WA_ALLOWED_CHAT_IDS` enforcement to groups only (`ops/whatsapp_govorun/bridge/src/index.mjs`); applied live code/env updates and restarted both WhatsApp services.
- 2026-03-05: enabled true WhatsApp 1:1 no-prefix handling by adding `chat.type` (`private`/`group`) to Node plugin-mode updates in `ops/whatsapp_govorun/bridge/src/index.mjs`, so Python prefix policy (`TELEGRAM_REQUIRE_PREFIX_IN_PRIVATE=false`) correctly bypasses prefix checks for private chats; synced Govorun env mirrors/docs and applied live runtime file update with service restart.

## Current Risks/Watchouts (Max 5)
- Browser autoplay can still be blocked by client policy and may require UI fallback interactions.
- WhatsApp progress edit behavior relies on valid outbound key mappings; mismatch paths should be treated as warning conditions.
- Keep group allowlists aligned (`WA_ALLOWED_CHAT_IDS`/`WA_ALLOWED_GROUPS` with `TELEGRAM_ALLOWED_CHAT_IDS`) while managing DM admission separately via `WA_ALLOWED_DMS` and `TELEGRAM_ALLOW_PRIVATE_CHATS_UNLISTED`.
- Telegram/WhatsApp channels can show transient DNS/API retries or reconnect churn; services currently auto-recover but should be monitored during network instability.
- Runtime observer alert routing depends on `RUNTIME_OBSERVER_TELEGRAM_CHAT_IDS` (or Telegram env fallback) remaining valid for the active bot token.

## Archive Pointer
- `SERVER3_ARCHIVE.md` is the canonical long-term detailed history.
- For per-change rollout evidence, use `logs/changes/*.md`.
