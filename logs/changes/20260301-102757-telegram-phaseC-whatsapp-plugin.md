# Change Log - Telegram Phase C Real WhatsApp Plugin Integration

Timestamp: 2026-03-01T10:27:57+10:00
Timezone: Australia/Brisbane

## Objective
- Replace the WhatsApp channel stub with a real WhatsApp channel adapter integrated into the plugin architecture.

## Scope
- In scope:
  - `src/telegram_bridge/whatsapp_channel.py`
  - `src/telegram_bridge/plugin_registry.py`
  - `src/telegram_bridge/main.py`
  - `tests/telegram_bridge/test_bridge_core.py`
  - `SERVER3_SUMMARY.md`
  - this `logs/changes` record
- Out of scope:
  - Discord/Slack/Signal channel work
  - Claude engine adapter
  - live WhatsApp bridge daemon rollout changes

## Changes Made
1. Replaced WhatsApp stub with real adapter:
   - Added `WhatsAppChannelAdapter` implementing full channel adapter surface (`get_updates`, send text/media/voice, edit, chat action, file metadata/download).
   - Adapter uses HTTP JSON calls to a local WhatsApp bridge API.
2. Added WhatsApp plugin safety gates:
   - Requires `WHATSAPP_PLUGIN_ENABLED=true` to activate.
   - Requires `WHATSAPP_BRIDGE_API_BASE` and supports optional `WHATSAPP_BRIDGE_AUTH_TOKEN`.
   - Uses `WHATSAPP_POLL_TIMEOUT_SECONDS` for long poll timeout behavior.
3. Registry wiring updated:
   - Default plugin registry now builds real `whatsapp` adapter instead of stub.
4. Config wiring updated:
   - Added WhatsApp plugin config fields into core config load path.
   - Startup logging/event payload now includes WhatsApp plugin enabled state.
5. Tests expanded:
   - Validate registry behavior for disabled/enabled WhatsApp plugin.
   - Validate env parsing for WhatsApp plugin settings.
   - Validate WhatsApp adapter JSON POST send path and message-id extraction.

## Validation
- Unit tests:
  - `python3 -m unittest discover -s tests -p 'test_*.py'`
  - Result: `Ran 96 tests ... OK`
- Smoke test:
  - `bash src/telegram_bridge/smoke_test.sh`
  - Result: `self-test: ok`, `smoke-test: ok`

## Notes
- Default runtime remains unchanged (`telegram` + `codex`).
- WhatsApp plugin is now real and selectable, but still safe-by-default (disabled unless explicitly enabled).
