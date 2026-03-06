# Server3 Summary

Last updated: 2026-03-07 (AEST, +10:00)

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
- Runtime observer daily Telegram summary now appends a plain-English operator line indicating whether attention is needed.
- Runtime observer daily health delivery is centralized through `staker_alerts_bot` to chat `211761499` (single destination).
- AsterTrader bot restart routing is pinned to `telegram-aster-trader-bridge.service` via `TELEGRAM_RESTART_UNIT` to prevent `/restart` from targeting Architect service defaults.
- AsterTrader `/restart` now works in-chat with least-privilege sudoers allowlist (`/etc/sudoers.d/aster-trader-bridge-restart`) scoped to `restart_and_verify.sh --unit telegram-aster-trader-bridge.service`.

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
- Govorun WhatsApp behavior is env-tunable: progress wording, busy-lock wording, and reply-tone guidance are configured via `/etc/default/govorun-whatsapp-bridge`.
- Architect Google runtime integration is removed/disabled.
- Server time standard for operations is Brisbane (`Australia/Brisbane`, AEST/UTC+10).

## Recent Changes (Rolling Max 8)
- 2026-03-06: added ASTER trading runtime support in repo with free-form `Trade ...` / `Aster Trade ...` keyword routing in bridge (`src/telegram_bridge/handlers.py`), deterministic backend (`src/telegram_bridge/aster_trading.py`, `ops/trading/aster/assistant_entry.py`, `ops/trading/aster/trade_cli.sh`) that enforces confirmation tickets + risk guards (max notional, max leverage, daily realized-loss stop), improved notional sizing to nearest valid lot-step with overshoot protection (`ASTER_NOTIONAL_MAX_OVERSHOOT_PCT`, default `0.15`) to reduce underfill while preventing oversized fills for tiny requests, Telegram-friendly line-by-line preview with bold-uppercase field labels, default confirmation timeout increased to 120 seconds (`ASTER_CONFIRM_TTL_SECONDS`), and live runtime speed tuning via low reasoning override (`ARCHITECT_EXEC_ARGS="--config model_reasoning_effort=\"low\""`), plus new service/env templates (`infra/systemd/telegram-aster-trader-bridge.service`, `infra/env/telegram-aster-trader-bridge.env.example`), operations runbook (`docs/runbooks/aster-trader-operations.md`), restart helper allowlist update (`ops/telegram-bridge/restart_and_verify.sh`), regression tests (`tests/telegram_bridge/test_bridge_core.py`, `tests/telegram_bridge/test_aster_trading.py`), CI fix to install `requests` in `.github/workflows/telegram-bridge-ci.yml` so unit tests can import `src/telegram_bridge/aster_trading.py` on GitHub runners, and live ASTER bot tuning change on Server3 to set `/etc/default/telegram-aster-trader-bridge` `ARCHITECT_EXEC_ARGS` from `model_reasoning_effort="low"` to `model_reasoning_effort="high"` with service restart.
- 2026-03-05: hardened Server3 DNS path for Telegram reliability by extending `ops/nordvpn/apply_server3_au.sh` with configurable custom DNS (`--dns`, default `1.1.1.1 1.0.0.1`, optional `--dns off`), updating NordVPN runbook/target-state docs (`docs/nordvpn-server3.md`, `infra/system/nordvpn/server3.nordvpn.target-state.md`), and applying live NordVPN DNS settings so resolver state is no longer tied only to NordVPN-assigned DNS endpoints.
- 2026-03-05: added canonical Govorun chat-routing contract enforcement across Telegram/WhatsApp env files with new contract `infra/contracts/server3-chat-routing.contract.env`, validator `ops/chat-routing/validate_chat_routing_contract.py`, daily drift-check systemd units (`server3-chat-routing-contract-check.service` + `.timer`) and installer `ops/chat-routing/install_contract_check_timer.sh`; wired preflight checks into Govorun service paths (`ops/whatsapp_govorun/install_user_service.sh`, `ops/whatsapp_govorun/start_service.sh`, and `ops/telegram-bridge/restart_and_verify.sh` for `govorun-whatsapp-bridge.service`) with regression tests in `tests/chat_routing/test_validate_chat_routing_contract.py`.
- 2026-03-05: added configurable busy-lock response text via new `TELEGRAM_BUSY_MESSAGE` in bridge config loading (`src/telegram_bridge/main.py`) with regression coverage in `tests/telegram_bridge/test_bridge_core.py`; documented/env-templated for Govorun WhatsApp (`infra/env/govorun-whatsapp-bridge*.env*`, `docs/runbooks/whatsapp-govorun-operations.md`) and applied live to `/etc/default/govorun-whatsapp-bridge` with `govorun-whatsapp-bridge.service` restart so concurrent-request replies are now in Govorun character.
- 2026-03-05: hardened Govorun WhatsApp integration in repo with reliability fixes: channel-aware memory namespacing (`tg:` vs `wa:`) in Python handlers/memory usage, pairing-code redaction from Node auth logs, Node bridge media-file retention controls (`WA_FILE_MAX_TOTAL_BYTES`, `WA_FILE_RETENTION_SECONDS`) with startup + periodic cleanup, explicit API `400 invalid_json`/`413 request_too_large` handling, best-effort outbound quoted-reply support via `reply_to_message_id` mapping in Node (`/messages` + `/media`), safer message-edit targeting (only known outbound messages), and local outbound media send-path optimization (avoid full-file reads in-process); added regression tests in `tests/telegram_bridge/test_bridge_core.py` and updated WhatsApp env/runbook docs.
- 2026-03-05: scheduled monthly system package maintenance at `04:00` AEST via new `server3-monthly-apt-upgrade.service` + `server3-monthly-apt-upgrade.timer` (OnCalendar `*-*-01 04:00:00`) and installer `ops/system-maintenance/install_monthly_apt_upgrade_timer.sh`; runtime script `ops/system-maintenance/run_monthly_apt_upgrade.sh` runs `apt-get update` then `apt-get upgrade -y`.
- 2026-03-05: fixed WhatsApp reply-thread context handling by adding inbound `reply_to_message` normalization in Node bridge (`ops/whatsapp_govorun/bridge/src/common.mjs` + `index.mjs`) and prompt assembly in Python (`src/telegram_bridge/handlers.py`) so Govorun sees quoted/original message content (not only the new reply text); added regression tests in `tests/telegram_bridge/test_bridge_core.py`.
- 2026-03-05: finalized explicit tone rule for daily Govorun 09:00 WhatsApp message in code + runbook: fun/funny/light/warm/enjoyable, exactly one short fun fact, prefer funny/interesting history-culture, animals, science, space, wholesome stories, life hacks, avoid heavy topics, and no sarcasm at people; fixed short format `Доброе утро...` + `Даю справку: ...`.

## Current Risks/Watchouts (Max 5)
- Browser autoplay can still be blocked by client policy and may require UI fallback interactions.
- WhatsApp progress edit behavior relies on valid outbound key mappings; mismatch paths should be treated as warning conditions.
- Keep group allowlists aligned (`WA_ALLOWED_CHAT_IDS`/`WA_ALLOWED_GROUPS` with `TELEGRAM_ALLOWED_CHAT_IDS`) while managing DM admission separately via `WA_ALLOWED_DMS` and `TELEGRAM_ALLOW_PRIVATE_CHATS_UNLISTED`.
- Telegram/WhatsApp channels can still show transient API retries or reconnect churn; DNS-side retry risk is reduced via custom NordVPN DNS but should still be monitored during network instability.
- Runtime observer alert routing depends on `RUNTIME_OBSERVER_TELEGRAM_CHAT_IDS` (or Telegram env fallback) remaining valid for the active bot token.

## Archive Pointer
- `SERVER3_ARCHIVE.md` is the canonical long-term detailed history.
- For per-change rollout evidence, use `logs/changes/*.md`.
