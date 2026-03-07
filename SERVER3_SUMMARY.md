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
- Architect Telegram + CLI now share one neutral memory identity on Server3 via `shared:architect:main`; the shared bucket merges the existing Architect Telegram chats and CLI history while starting a fresh unified Codex session thread.
- Govorun WhatsApp behavior is env-tunable: progress wording, busy-lock wording, and reply-tone guidance are configured via `/etc/default/govorun-whatsapp-bridge`.
- Architect Google runtime integration is removed/disabled.
- Server time standard for operations is Brisbane (`Australia/Brisbane`, AEST/UTC+10).

## Recent Changes (Rolling Max 8)
- 2026-03-07: fixed Oracle Signal in-chat `/restart` by adding `oracle-signal-bridge.service` to the shared restart-helper allowlist, adding Oracle-specific `TELEGRAM_RESTART_SCRIPT`/`TELEGRAM_RESTART_UNIT` env defaults, and provisioning a least-privilege sudoers rule for user `oracle` so restart requests no longer fall back to the removed local workspace path or the Architect unit.
- 2026-03-07: adjusted Oracle Signal compact progress rendering so blank `TELEGRAM_PROGRESS_ELAPSED_PREFIX`/`TELEGRAM_PROGRESS_ELAPSED_SUFFIX` now suppress the stale elapsed text entirely; Oracle Signal defaults now show `Oracle is thinking...` instead of `Oracle is thinking... Already 1s` on channels like Signal where progress edits do not update in-place.
- 2026-03-07: reduced the deployed Oracle Signal workspace at `/home/oracle/oraclebot` to a minimal runtime layout by changing `ops/signal_oracle/deploy_bridge.sh` to deploy only `src/telegram_bridge` plus a blank `AGENTS.md`, removing inherited Architect docs/tests/ops/instructions from the live Oracle workspace; documented the intentional minimal layout in `docs/runbooks/oracle-signal-operations.md`.
- 2026-03-07: fixed live Oracle Signal executor startup failure caused by the dedicated `oracle` runtime user missing Codex CLI auth (`~/.codex/auth.json`), provisioned the runtime auth on Server3, and hardened Oracle Signal ops so startup now fails fast with an explicit operator error when auth is absent; documented the required bootstrap step in `docs/runbooks/oracle-signal-operations.md` and enforced it in `ops/signal_oracle/start_service.sh`.
- 2026-03-07: added repo support for a new dedicated Signal persona/runtime `oracle` using the existing shared Python bridge plus a new local Signal transport sidecar around `signal-cli`: new `signal` channel plugin and shared HTTP adapter (`src/telegram_bridge/signal_channel.py`, `src/telegram_bridge/http_channel.py`, `src/telegram_bridge/plugin_registry.py`), shared-bridge config/handler upgrades for `sig:` memory keys, optional unlisted Signal DM/group admission, chat-only keyword-routing disable, and no-edit progress fallback (`src/telegram_bridge/main.py`, `src/telegram_bridge/handlers.py`, `src/telegram_bridge/memory_engine.py`), transport service/runtime assets (`ops/signal_oracle/bridge/signal_oracle_bridge.py`, `infra/systemd/*signal-oracle*.service`, `infra/env/*signal-oracle*.env.example`, `ops/signal_oracle/*.sh`), new operations runbook (`docs/runbooks/oracle-signal-operations.md`), regression coverage in `tests/telegram_bridge/test_bridge_core.py`, `tests/telegram_bridge/test_memory_engine.py`, and `tests/signal_oracle_bridge/test_signal_oracle_bridge.py`, plus follow-up default-port correction in repo templates/runbook from `8080/8797` to dedicated local ports `18080/18797` after discovering Docker already occupied `8080` on Server3.
- 2026-03-07: added natural-language shared-memory recall for Architect bridge + CLI so plain-English prompts like “what were my last 5 messages?”, “what were your last 5 messages?”, “what do you remember from today?”, “what facts do you remember?”, and “what’s the latest summary?” are intercepted before Codex execution and answered directly from SQLite shared memory using Brisbane-time windowing; added regression coverage in `tests/telegram_bridge/test_memory_engine.py`, `tests/telegram_bridge/test_bridge_core.py`, and `tests/architect_cli/test_main.py`.
- 2026-03-07: added operator-facing mental map doc `docs/server3-mental-model.md` that explains Server3 by layers (entry points, shared bridge core, deterministic operation modes, platform/safety layer), documents the main runtimes/personas (Architect, Tank, ASTER, Govorun), shows how request routing works across Telegram/WhatsApp/CLI, and points to the canonical files/docs for each subsystem; linked from `README.md` as a primary orientation document.
- 2026-03-06: added ASTER trading runtime support in repo with free-form `Trade ...` / `Aster Trade ...` keyword routing in bridge (`src/telegram_bridge/handlers.py`), deterministic backend (`src/telegram_bridge/aster_trading.py`, `ops/trading/aster/assistant_entry.py`, `ops/trading/aster/trade_cli.sh`) that enforces confirmation tickets + risk guards (max notional, max leverage, daily realized-loss stop), improved notional sizing to nearest valid lot-step with overshoot protection (`ASTER_NOTIONAL_MAX_OVERSHOOT_PCT`, default `0.15`) to reduce underfill while preventing oversized fills for tiny requests, Telegram-friendly line-by-line preview with bold-uppercase field labels, default confirmation timeout increased to 120 seconds (`ASTER_CONFIRM_TTL_SECONDS`), and live runtime speed tuning via low reasoning override (`ARCHITECT_EXEC_ARGS="--config model_reasoning_effort=\"low\""`), plus new service/env templates (`infra/systemd/telegram-aster-trader-bridge.service`, `infra/env/telegram-aster-trader-bridge.env.example`), operations runbook (`docs/runbooks/aster-trader-operations.md`), restart helper allowlist update (`ops/telegram-bridge/restart_and_verify.sh`), regression tests (`tests/telegram_bridge/test_bridge_core.py`, `tests/telegram_bridge/test_aster_trading.py`), CI fix to install `requests` in `.github/workflows/telegram-bridge-ci.yml` so unit tests can import `src/telegram_bridge/aster_trading.py` on GitHub runners, and live ASTER bot tuning change on Server3 to set `/etc/default/telegram-aster-trader-bridge` `ARCHITECT_EXEC_ARGS` from `model_reasoning_effort="low"` to `model_reasoning_effort="high"` with service restart.
- 2026-03-05: hardened Server3 DNS path for Telegram reliability by extending `ops/nordvpn/apply_server3_au.sh` with configurable custom DNS (`--dns`, default `1.1.1.1 1.0.0.1`, optional `--dns off`), updating NordVPN runbook/target-state docs (`docs/nordvpn-server3.md`, `infra/system/nordvpn/server3.nordvpn.target-state.md`), and applying live NordVPN DNS settings so resolver state is no longer tied only to NordVPN-assigned DNS endpoints.
- 2026-03-05: added canonical Govorun chat-routing contract enforcement across Telegram/WhatsApp env files with new contract `infra/contracts/server3-chat-routing.contract.env`, validator `ops/chat-routing/validate_chat_routing_contract.py`, daily drift-check systemd units (`server3-chat-routing-contract-check.service` + `.timer`) and installer `ops/chat-routing/install_contract_check_timer.sh`; wired preflight checks into Govorun service paths (`ops/whatsapp_govorun/install_user_service.sh`, `ops/whatsapp_govorun/start_service.sh`, and `ops/telegram-bridge/restart_and_verify.sh` for `govorun-whatsapp-bridge.service`) with regression tests in `tests/chat_routing/test_validate_chat_routing_contract.py`.
- 2026-03-05: added configurable busy-lock response text via new `TELEGRAM_BUSY_MESSAGE` in bridge config loading (`src/telegram_bridge/main.py`) with regression coverage in `tests/telegram_bridge/test_bridge_core.py`; documented/env-templated for Govorun WhatsApp (`infra/env/govorun-whatsapp-bridge*.env*`, `docs/runbooks/whatsapp-govorun-operations.md`) and applied live to `/etc/default/govorun-whatsapp-bridge` with `govorun-whatsapp-bridge.service` restart so concurrent-request replies are now in Govorun character.
- 2026-03-05: hardened Govorun WhatsApp integration in repo with reliability fixes: channel-aware memory namespacing (`tg:` vs `wa:`) in Python handlers/memory usage, pairing-code redaction from Node auth logs, Node bridge media-file retention controls (`WA_FILE_MAX_TOTAL_BYTES`, `WA_FILE_RETENTION_SECONDS`) with startup + periodic cleanup, explicit API `400 invalid_json`/`413 request_too_large` handling, best-effort outbound quoted-reply support via `reply_to_message_id` mapping in Node (`/messages` + `/media`), safer message-edit targeting (only known outbound messages), and local outbound media send-path optimization (avoid full-file reads in-process); added regression tests in `tests/telegram_bridge/test_bridge_core.py` and updated WhatsApp env/runbook docs.

## Current Risks/Watchouts (Max 5)
- Browser autoplay can still be blocked by client policy and may require UI fallback interactions.
- WhatsApp progress edit behavior relies on valid outbound key mappings; mismatch paths should be treated as warning conditions.
- Keep group allowlists aligned (`WA_ALLOWED_CHAT_IDS`/`WA_ALLOWED_GROUPS` with `TELEGRAM_ALLOWED_CHAT_IDS`) while managing DM admission separately via `WA_ALLOWED_DMS` and `TELEGRAM_ALLOW_PRIVATE_CHATS_UNLISTED`.
- Telegram/WhatsApp channels can still show transient API retries or reconnect churn; DNS-side retry risk is reduced via custom NordVPN DNS but should still be monitored during network instability.
- Runtime observer alert routing depends on `RUNTIME_OBSERVER_TELEGRAM_CHAT_IDS` (or Telegram env fallback) remaining valid for the active bot token.

## Archive Pointer
- `SERVER3_ARCHIVE.md` is the canonical long-term detailed history.
- For per-change rollout evidence, use `logs/changes/*.md`.
