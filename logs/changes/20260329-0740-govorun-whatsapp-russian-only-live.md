# 2026-03-29 07:40 AEST - Govorun WhatsApp Russian-only live

## Request
- Make only WhatsApp Govorun Russian-only again; keep the other bots in English.

## Current State Inspected
- Confirmed the repo-backed Govorun runtime persona still defaulted to English in `infra/runtime_personas/govorun.AGENTS.md`.
- Confirmed the Govorun WhatsApp bridge env mirror still pinned English reply/UI behavior in `infra/env/govorun-whatsapp-bridge.server3.redacted.env`.
- Confirmed the Govorun-specific response style hint is injected by `src/telegram_bridge/executor.sh`, so changing Govorun's env and runtime-local persona is sufficient without touching the shared bridge core or other runtimes.

## Change Applied
- Switched Govorun's runtime-local persona source-of-truth back to Russian-only replies.
- Translated Govorun-only WhatsApp bridge user-facing strings back to Russian:
  - `TELEGRAM_RESPONSE_STYLE_HINT`
  - `TELEGRAM_PROGRESS_LABEL`
  - `TELEGRAM_PROGRESS_ELAPSED_PREFIX`
  - `TELEGRAM_PROGRESS_ELAPSED_SUFFIX`
  - `TELEGRAM_BUSY_MESSAGE`
  - `TELEGRAM_VOICE_LOW_CONFIDENCE_MESSAGE`
- Updated the Govorun runbook and summary to reflect the Russian-only WhatsApp policy.

## Verification
- `bash /home/architect/matrix/ops/telegram-bridge/restart_and_verify.sh --unit govorun-whatsapp-bridge.service`
  - passed at `2026-03-29 10:05:23 AEST`
  - chat-routing contract check passed before restart
  - service returned `active/running` with new main PID `3210472`
- `sudo systemctl status govorun-whatsapp-bridge.service --no-pager -n 10`
  - confirmed `Active: active (running)` since `2026-03-29 10:05:23 AEST`
- Direct executor smoke test as runtime user `govorun`
  - prompt: `What language should you use by default when replying here? Answer in one short sentence.`
  - output: `По умолчанию я отвечаю здесь на русском языке.`

## Notes
- Scope is intentionally limited to Govorun's WhatsApp runtime persona and Govorun-specific WhatsApp env strings.
- No Telegram sibling runtime policy was changed.
