# Govorun Runtime (Server3)

Repo-backed companion README for the live Govorun runtime root at `/home/govorun/govorunbot`.

## Current Live Shape

- Channel: WhatsApp through the local Govorun transport API
- Services:
  - `whatsapp-govorun-bridge.service` (Node transport/API)
  - `govorun-whatsapp-bridge.service` (Python shared-bridge runtime)
- Runtime roots:
  - transport app: `/home/govorun/whatsapp-govorun/app`
  - Govorun bridge root: `/home/govorun/govorunbot`
- Shared core: `/home/architect/matrix/src/telegram_bridge`
- Persona source: `infra/runtime_personas/govorun.AGENTS.md`
- Default language: reply in Russian by default; only switch when the user explicitly asks for translation or quoted text in another language
- Current live posture: WhatsApp Govorun is pinned back to Russian-only default replies

## Runtime Behavior

- Group chats require a summon prefix such as `@говорун`, `говорун`, or `govorun`
- Private chats can reply without prefix when `TELEGRAM_REQUIRE_PREFIX_IN_PRIVATE=false`
- Unlisted DMs can be admitted with `TELEGRAM_ALLOW_PRIVATE_CHATS_UNLISTED=true`
- Bare YouTube links are auto-routed into transcript-first YouTube analysis
- `Browser Brain ...` and `Server3 Browser ...` requests are available through the shared bridge route
- Voice notes require `TELEGRAM_VOICE_TRANSCRIBE_CMD`; Russian transcription quality is best when `TELEGRAM_VOICE_WHISPER_LANGUAGE=ru`
- The bridge watches `/home/govorun/govorunbot/AGENTS.md` through `TELEGRAM_POLICY_WATCH_FILES` so policy changes can clear stale session state

## Key Config And State

- Govorun bridge env: `/etc/default/govorun-whatsapp-bridge`
- WhatsApp transport env: `/home/govorun/whatsapp-govorun/app/.env`
- Chat-routing contract: `infra/contracts/server3-chat-routing.contract.env`
- Bridge state dir: `/home/govorun/.local/state/govorun-whatsapp-bridge`
- Canonical session DB: `/home/govorun/.local/state/govorun-whatsapp-bridge/chat_sessions.sqlite3`
- Memory DB: `/home/govorun/.local/state/govorun-whatsapp-bridge/memory.sqlite3`

## Common Operations

- Restart transport: `ops/whatsapp_govorun/start_service.sh`
- Restart Govorun bridge: `sudo systemctl restart govorun-whatsapp-bridge.service`
- Check both services:
  - `sudo systemctl status whatsapp-govorun-bridge.service --no-pager -n 50`
  - `sudo systemctl status govorun-whatsapp-bridge.service --no-pager -n 50`
- Re-run WhatsApp auth: `ops/whatsapp_govorun/run_auth.sh`
- Validate routing contract: `python3 ops/chat-routing/validate_chat_routing_contract.py`

## Daily Uplift Timer

- Units:
  - `govorun-whatsapp-daily-uplift.service`
  - `govorun-whatsapp-daily-uplift.timer`
- Env file: `/etc/default/govorun-whatsapp-daily-uplift`
- Script: `ops/whatsapp_govorun/send_daily_uplift.py`

## Related Docs

- `docs/runbooks/whatsapp-govorun-operations.md`
- `docs/runbooks/telegram-whatsapp-dual-runtime.md`
- `docs/runbooks/runtime-doc-source-of-truth.md`
- `infra/runtime_personas/govorun.AGENTS.md`
- `SERVER3_SUMMARY.md`
