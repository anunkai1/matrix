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
- Server time standard for operations is Brisbane (`Australia/Brisbane`, AEST/UTC+10).

## Recent Changes (Rolling Max 8)
- 2026-03-08: cleared residual decommissioned local boot wiring that was still loading after restart from ignored local payload paths outside git, removed the stale runtime residue, and verified core bridge services/timers recover cleanly without those old units re-entering the boot path.
- 2026-03-07: fixed Oracle Signal default-port drift in code by aligning shared bridge defaults with the shipped env templates and runbooks: `src/telegram_bridge/main.py` now defaults `SIGNAL_BRIDGE_API_BASE` to `http://127.0.0.1:18797`, `ops/signal_oracle/bridge/signal_oracle_bridge.py` now defaults the transport/API ports to `18080/18797`, and regression tests now lock those defaults so partially configured Oracle deployments no longer silently fall back to the obsolete `8080/8797` ports.
- 2026-03-07: cleaned active docs for drift by updating the top-level README and Server3 mental model to include the Oracle Signal runtime, correcting runtime observer documentation to the current delivery modes (`telegram_daily_summary`, `telegram_alerts`, `telegram_alerts_daily`) and live daily-summary posture, and refreshing the runtime observer env template comments so docs/config examples match the implemented modes.
- 2026-03-07: fixed Oracle Signal voice-note handling by classifying Signal AAC/M4A voice-note attachments as `voice` instead of generic documents in `ops/signal_oracle/bridge/signal_oracle_bridge.py`, enabling Oracle voice transcription env defaults for `transcribe_voice.sh`, and standardizing Oracle's dedicated faster-whisper runtime on Server3 to `/home/oracle/.local/share/telegram-voice/venv` with local Hugging Face cache `/home/oracle/.cache/huggingface` and model `tiny.en`.
- 2026-03-07: fixed Oracle Signal identity persistence bugs by making memory reset actually delete conversation messages/facts/summaries (not just the thread row), removing the hard-coded `Architect` assistant label from memory writes, and removing the Oracle-specific `TELEGRAM_RESPONSE_STYLE_HINT` override so persona/identity now come only from Oracle's `AGENTS.md`.
- 2026-03-07: fixed Oracle Signal in-chat `/restart` by adding `oracle-signal-bridge.service` to the shared restart-helper allowlist, adding Oracle-specific `TELEGRAM_RESTART_SCRIPT`/`TELEGRAM_RESTART_UNIT` env defaults, and provisioning a least-privilege sudoers rule for user `oracle` so restart requests no longer fall back to the removed local workspace path or the Architect unit.
- 2026-03-07: adjusted Oracle Signal compact progress rendering so blank `TELEGRAM_PROGRESS_ELAPSED_PREFIX`/`TELEGRAM_PROGRESS_ELAPSED_SUFFIX` now suppress the stale elapsed text entirely; Oracle Signal defaults now show `Oracle is thinking...` instead of `Oracle is thinking... Already 1s` on channels like Signal where progress edits do not update in-place.
- 2026-03-07: reduced the deployed Oracle Signal workspace at `/home/oracle/oraclebot` to a minimal runtime layout by changing `ops/signal_oracle/deploy_bridge.sh` to deploy only `src/telegram_bridge` while preserving Oracle's live `AGENTS.md` as the runtime persona/identity truth file, removing inherited Architect docs/tests/ops/instructions from the live Oracle workspace; documented the intentional minimal layout in `docs/runbooks/oracle-signal-operations.md`.

## Current Risks/Watchouts (Max 5)
- Browser autoplay can still be blocked by client policy and may require UI fallback interactions.
- WhatsApp progress edit behavior relies on valid outbound key mappings; mismatch paths should be treated as warning conditions.
- Keep group allowlists aligned (`WA_ALLOWED_CHAT_IDS`/`WA_ALLOWED_GROUPS` with `TELEGRAM_ALLOWED_CHAT_IDS`) while managing DM admission separately via `WA_ALLOWED_DMS` and `TELEGRAM_ALLOW_PRIVATE_CHATS_UNLISTED`.
- Telegram/WhatsApp channels can still show transient API retries or reconnect churn; DNS-side retry risk is reduced via custom NordVPN DNS but should still be monitored during network instability.
- Runtime observer alert routing depends on `RUNTIME_OBSERVER_TELEGRAM_CHAT_IDS` (or Telegram env fallback) remaining valid for the active bot token.

## Archive Pointer
- `SERVER3_ARCHIVE.md` is the canonical long-term detailed history.
- For per-change rollout evidence, use `logs/changes/*.md`.
