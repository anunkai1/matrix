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
- Runtime observer is enabled on timer (`server3-runtime-observer.timer`) with Telegram daily summary mode (`RUNTIME_OBSERVER_MODE=telegram_daily_summary`) scheduled for `08:05` AEST.
- TV desktop/browser reliability is hardened with deterministic helpers, existing-window reuse, and autoplay fallback tooling (`wmctrl`, `xdotool`, `yt-dlp`).
- Tank defaults are hardened: DM prefix bypass in private chats, isolated Joplin profile/path, reasoning effort `low`.
- Govorun WhatsApp progress depends on outbound message-key mapping for `/messages/edit`; compact elapsed wording is env-configured.
- Architect Google runtime integration is removed/disabled.
- Server time standard for operations is Brisbane (`Australia/Brisbane`, AEST/UTC+10).

## Recent Changes (Rolling Max 8)
- 2026-03-04: removed forced WhatsApp outbound reply name prefix from Python bridge (`src/telegram_bridge/handlers.py` `apply_outbound_reply_prefix` now pass-through), so Govorun answers without leading `Говорун:`; added/updated regression tests in `tests/telegram_bridge/test_bridge_core.py` and applied the same patch live to `/home/govorun/govorunbot/src/telegram_bridge/handlers.py` with service restart.
- 2026-03-04: added owner persona preferences to `AGENTS.md` (keep Govorun-like cartoon persona in user-facing answers and use the requested "came from an egg / ancient dinosaurs like pteradactyl" line when asked who made you), without changing policy authority in `ARCHITECT_INSTRUCTION.md`.
- 2026-03-04: added new WhatsApp group allowlist mapping `chat_id=53072088` to both live allowlists (`TELEGRAM_ALLOWED_CHAT_IDS` in `/etc/default/govorun-whatsapp-bridge` and `WA_ALLOWED_CHAT_IDS` in `/home/govorun/whatsapp-govorun/app/.env`) and restarted `whatsapp-govorun-bridge.service` + `govorun-whatsapp-bridge.service`; startup now reports `allowedChatIdsCount=3` (Node) and `Allowed chats=[53072088, 335502052, 1434663945]` (Python).
- 2026-03-04: forced Govorun WhatsApp whisper language to Russian (`TELEGRAM_VOICE_WHISPER_LANGUAGE=ru`) so Russian-spoken summon prefix `говорун` is transcribed in Cyrillic-compatible form instead of English-biased output; applied live in `/etc/default/govorun-whatsapp-bridge` and restarted bridge runtime.
- 2026-03-04: lowered Govorun WhatsApp voice low-confidence threshold to `0.35` and changed low-confidence user prompt to `Не понял что вы промурлычили, скажите ещё раз`; wired new config field/env `TELEGRAM_VOICE_LOW_CONFIDENCE_MESSAGE` and applied live in `/etc/default/govorun-whatsapp-bridge`.
- 2026-03-04: enabled WhatsApp voice-prefix alias learning assist by allowing `/voice-alias` commands to bypass summon-prefix gating in WhatsApp groups and by auto-observing repeated near-prefix transcript misses (for example `govoron` -> `govorun`) into standard voice-alias suggestions that can be approved via `/voice-alias approve <id>`.
- 2026-03-04: enabled Govorun WhatsApp voice-note transcription by wiring live `/etc/default/govorun-whatsapp-bridge` with `TELEGRAM_VOICE_TRANSCRIBE_CMD` + dedicated whisper runtime env (`TELEGRAM_VOICE_WHISPER_VENV`, socket/log path, `HF_HOME=/home/govorun/.cache/huggingface`) and setting `TELEGRAM_VOICE_WHISPER_MODEL=medium`; voice-prefix enforcement now silently ignores non-prefixed WhatsApp transcripts after transcription while still executing prefixed transcripts.
- 2026-03-04: made WhatsApp `/help` and `/h` output minimal and command-only (`/start`, `/help`, `/status`, `/reset`, `/cancel`, `/restart`) by channel-specific help rendering in `src/telegram_bridge/handlers.py`; removed non-applicable WhatsApp help lines (voice-alias, TV helpers, routing keywords, memory help) for `channel_plugin=whatsapp`.

## Current Risks/Watchouts (Max 5)
- Browser autoplay can still be blocked by client policy and may require UI fallback interactions.
- WhatsApp progress edit behavior relies on valid outbound key mappings; mismatch paths should be treated as warning conditions.
- Keep `WA_ALLOWED_CHAT_IDS` (WhatsApp bridge) aligned with `TELEGRAM_ALLOWED_CHAT_IDS` (`/etc/default/govorun-whatsapp-bridge`) to avoid silent drops or policy leakage.
- Telegram/WhatsApp channels can show transient DNS/API retries or reconnect churn; services currently auto-recover but should be monitored during network instability.
- Runtime observer alert routing depends on `RUNTIME_OBSERVER_TELEGRAM_CHAT_IDS` (or Telegram env fallback) remaining valid for the active bot token.

## Archive Pointer
- `SERVER3_ARCHIVE.md` is the canonical long-term detailed history.
- For per-change rollout evidence, use `logs/changes/*.md`.
