# Change Log - Telegram Phase B Plugin Selection + WhatsApp Stub

Timestamp: 2026-03-01T10:14:15+10:00
Timezone: Australia/Brisbane

## Objective
- Implement safe Phase B configuration wiring for plugin selection and add a WhatsApp channel stub registration.

## Scope
- In scope:
  - `src/telegram_bridge/main.py`
  - `src/telegram_bridge/plugin_registry.py`
  - `src/telegram_bridge/whatsapp_channel_stub.py`
  - `tests/telegram_bridge/test_bridge_core.py`
  - `SERVER3_SUMMARY.md`
  - this `logs/changes` record
- Out of scope:
  - real WhatsApp transport/auth/runtime implementation
  - non-Codex engine implementation

## Changes Made
1. Added config/env plugin selectors:
   - New config fields: `channel_plugin`, `engine_plugin`.
   - New env keys:
     - `TELEGRAM_CHANNEL_PLUGIN` (default: `telegram`)
     - `TELEGRAM_ENGINE_PLUGIN` (default: `codex`)
2. Wired `run_bridge` to selected plugins:
   - Bridge now builds channel/engine from config values through registry.
   - Added fail-fast startup handling for unknown/invalid plugin selection with clear logs and structured event `bridge.plugin_selection_failed`.
3. Added WhatsApp stub plugin registration:
   - New `WhatsAppChannelStubAdapter` placeholder class.
   - Registered under channel name `whatsapp` in default registry.
   - Stub intentionally fails fast at construction with clear message to prevent accidental runtime use.
4. Expanded tests:
   - Registry channel list now includes `whatsapp`.
   - Added test asserting WhatsApp stub fails fast.
   - Added env/config parsing tests for plugin name defaults and overrides.

## Validation
- Unit tests:
  - `python3 -m unittest discover -s tests -p 'test_*.py'`
  - Result: `Ran 93 tests ... OK`
- Smoke test:
  - `bash src/telegram_bridge/smoke_test.sh`
  - Result: `self-test: ok`, `smoke-test: ok`

## Notes
- Behavior remains unchanged for default config (`telegram` + `codex`).
- WhatsApp support is intentionally non-runtime in this phase; implementation follows in next phase.
