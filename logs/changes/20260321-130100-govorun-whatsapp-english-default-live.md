# 2026-03-21 13:01:00 AEST - Govorun WhatsApp English Default Live

## Request
- Make Govorun on WhatsApp default to English without changing the other Telegram/sibling bot runtimes.

## Changes
- Added Govorun runtime persona source-of-truth:
  - `infra/runtime_personas/govorun.AGENTS.md`
- Installed live Govorun runtime persona:
  - `/home/govorun/govorunbot/AGENTS.md`
- Updated live Govorun WhatsApp bridge env:
  - `/etc/default/govorun-whatsapp-bridge`
  - added `TELEGRAM_RESPONSE_STYLE_HINT` that pins English as the default reply language
  - changed progress wording to `Govorun is thinking / Already / s`
  - changed busy-lock and voice low-confidence messages to English
- Updated repo mirrors/docs:
  - `infra/env/govorun-whatsapp-bridge.server3.redacted.env`
  - `infra/env/govorun-whatsapp-bridge.env.example`
  - `docs/runbooks/whatsapp-govorun-operations.md`
  - `docs/server3-mental-model.md`

## Verification
- `bash /home/architect/matrix/ops/telegram-bridge/restart_and_verify.sh --unit govorun-whatsapp-bridge.service`
  - passed
- `systemctl status govorun-whatsapp-bridge.service`
  - active/running after restart
- Direct live executor smoke test as the real `govorun` runtime user:
  - prompt: `What language should you use by default when replying here? Answer in one short sentence.`
  - output: `I should reply in English by default.`

## Notes
- The change is isolated to Govorun's runtime-local `AGENTS.md` and Govorun's WhatsApp env, so it does not affect the Telegram bots or other sibling runtimes.
- `TELEGRAM_VOICE_WHISPER_LANGUAGE` remains `ru` for now so Russian summon words/voice behavior stay intact; typed replies and bridge UI strings now default to English.
