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
- Govorun WhatsApp behavior is env-tunable: progress wording and reply-tone guidance are configured via `/etc/default/govorun-whatsapp-bridge`.
- Architect Google runtime integration is removed/disabled.
- Server time standard for operations is Brisbane (`Australia/Brisbane`, AEST/UTC+10).

## Recent Changes (Rolling Max 8)
- 2026-03-05: added daily Govorun WhatsApp uplift scheduler for `09:00` Brisbane time using new sender script `ops/whatsapp_govorun/send_daily_uplift.py` plus systemd units `infra/systemd/govorun-whatsapp-daily-uplift.service` + `.timer`, installer `ops/whatsapp_govorun/install_daily_uplift_timer.sh`, and live env `/etc/default/govorun-whatsapp-daily-uplift` targeting `Путиловы` group JID.
- 2026-03-05: fixed WhatsApp 1:1 non-reply path by allowing private chats outside numeric allowlist when explicitly enabled (`TELEGRAM_ALLOW_PRIVATE_CHATS_UNLISTED=true`) in Python allowlist gating (`src/telegram_bridge/handlers.py`) and by scoping Node `WA_ALLOWED_CHAT_IDS` enforcement to groups only (`ops/whatsapp_govorun/bridge/src/index.mjs`); applied live code/env updates and restarted both WhatsApp services.
- 2026-03-05: enabled true WhatsApp 1:1 no-prefix handling by adding `chat.type` (`private`/`group`) to Node plugin-mode updates in `ops/whatsapp_govorun/bridge/src/index.mjs`, so Python prefix policy (`TELEGRAM_REQUIRE_PREFIX_IN_PRIVATE=false`) correctly bypasses prefix checks for private chats; synced Govorun env mirrors/docs and applied live runtime file update with service restart.
- 2026-03-05: set Govorun WhatsApp outbound reply prefix to `Даю справку:` (including automatic rewrite of legacy leading `Говорун:`/`говорун:`) in `src/telegram_bridge/handlers.py`, updated prefix regression tests in `tests/telegram_bridge/test_bridge_core.py`, and applied the same live patch to `/home/govorun/govorunbot/src/telegram_bridge/handlers.py` with `govorun-whatsapp-bridge.service` restart.
- 2026-03-04: fixed Govorun WhatsApp `/restart` by adding restart target overrides (`TELEGRAM_RESTART_SCRIPT`, `TELEGRAM_RESTART_UNIT`) in `src/telegram_bridge/session_manager.py`, extending `ops/telegram-bridge/restart_and_verify.sh` allowlist for `govorun-whatsapp-bridge.service`, adding scoped sudoers mirror `infra/system/sudoers/govorun-whatsapp-bridge`, and applying live env/runtime updates so restarts execute in correct order and unit context.
- 2026-03-04: added Govorun WhatsApp reply-tone control via env-driven prompt preface (`TELEGRAM_RESPONSE_STYLE_HINT`) in `src/telegram_bridge/executor.sh`, documented it in runbooks/env templates, applied live to `/home/govorun/govorunbot/src/telegram_bridge/executor.sh`, refined live hint wording to "info first + occasional short jokes + tiny mild sarcasm" with safety-topic sarcasm guardrails, and enabled immediate model profile override via `ARCHITECT_EXEC_ARGS` for both new and resumed chats (`--model gpt-5-codex-mini --config model_reasoning_effort="medium"`) in `/etc/default/govorun-whatsapp-bridge` with service restart.
- 2026-03-04: removed forced WhatsApp outbound reply name prefix from Python bridge (`src/telegram_bridge/handlers.py` `apply_outbound_reply_prefix` now pass-through), so Govorun answers without leading `Говорун:`; added/updated regression tests in `tests/telegram_bridge/test_bridge_core.py` and applied the same patch live to `/home/govorun/govorunbot/src/telegram_bridge/handlers.py` with service restart.
- 2026-03-04: added new WhatsApp group allowlist mapping `chat_id=53072088` to both live allowlists (`TELEGRAM_ALLOWED_CHAT_IDS` in `/etc/default/govorun-whatsapp-bridge` and `WA_ALLOWED_CHAT_IDS` in `/home/govorun/whatsapp-govorun/app/.env`) and restarted `whatsapp-govorun-bridge.service` + `govorun-whatsapp-bridge.service`; startup now reports `allowedChatIdsCount=3` (Node) and `Allowed chats=[53072088, 335502052, 1434663945]` (Python).

## Current Risks/Watchouts (Max 5)
- Browser autoplay can still be blocked by client policy and may require UI fallback interactions.
- WhatsApp progress edit behavior relies on valid outbound key mappings; mismatch paths should be treated as warning conditions.
- Keep group allowlists aligned (`WA_ALLOWED_CHAT_IDS`/`WA_ALLOWED_GROUPS` with `TELEGRAM_ALLOWED_CHAT_IDS`) while managing DM admission separately via `WA_ALLOWED_DMS` and `TELEGRAM_ALLOW_PRIVATE_CHATS_UNLISTED`.
- Telegram/WhatsApp channels can show transient DNS/API retries or reconnect churn; services currently auto-recover but should be monitored during network instability.
- Runtime observer alert routing depends on `RUNTIME_OBSERVER_TELEGRAM_CHAT_IDS` (or Telegram env fallback) remaining valid for the active bot token.

## Archive Pointer
- `SERVER3_ARCHIVE.md` is the canonical long-term detailed history.
- For per-change rollout evidence, use `logs/changes/*.md`.
