# Change Log - Phase D WhatsApp Bridge API Endpoints

Timestamp: 2026-03-01T10:59:32+10:00
Timezone: Australia/Brisbane

## Objective
- Implement WhatsApp bridge HTTP endpoints expected by the new matrix WhatsApp channel plugin.

## Scope
- In scope:
  - `ops/whatsapp_govorun/bridge/src/index.mjs`
  - `ops/whatsapp_govorun/bridge/src/common.mjs`
  - `ops/whatsapp_govorun/bridge/README.md`
  - `docs/runbooks/whatsapp-govorun-operations.md`
  - `SERVER3_SUMMARY.md`
  - this `logs/changes` record
- Out of scope:
  - Discord/Slack/Signal adapters
  - Claude engine adapter
  - live systemd/env deployment changes

## Changes Made
1. Added bridge API server endpoints in WhatsApp runtime:
   - `GET /health`
   - `GET /updates`
   - `POST /messages`
   - `POST /media`
   - `POST /messages/edit` (compat no-op)
   - `POST /chat-action` (compat no-op)
   - `GET /files/meta`
   - `GET /files/content`
2. Added API auth and queueing:
   - Optional bearer auth via `WA_API_AUTH_TOKEN`.
   - In-memory update queue with offset + long-poll semantics for plugin polling.
3. Added plugin-mode routing in runtime:
   - New `WA_PLUGIN_MODE` gate.
   - In plugin mode, incoming WA messages are queued for API polling instead of local Codex auto-reply.
4. Added media/file support for plugin pull flow:
   - Incoming media download/store path for image/voice/document metadata + content endpoints.
5. Added new config keys in bridge runtime config builder:
   - `WA_FILES_DIR`
   - `WA_PLUGIN_MODE`
   - `WA_API_HOST`
   - `WA_API_PORT`
   - `WA_API_AUTH_TOKEN`
   - `WA_API_MAX_UPDATES_PER_POLL`
   - `WA_API_MAX_QUEUE_SIZE`
   - `WA_API_MAX_LONG_POLL_SECONDS`
   - `WA_FILE_MAX_BYTES`
6. Updated docs:
   - Bridge README with API contract and env keys.
   - Operations runbook with plugin API mode settings.

## Validation
- Node syntax checks:
  - `node --check ops/whatsapp_govorun/bridge/src/index.mjs`
  - `node --check ops/whatsapp_govorun/bridge/src/common.mjs`
- Python suite:
  - `python3 -m unittest discover -s tests -p 'test_*.py'`
  - Result: `Ran 96 tests ... OK`
- Smoke:
  - `bash src/telegram_bridge/smoke_test.sh`
  - Result: `self-test: ok`, `smoke-test: ok`

## Notes
- Default Telegram runtime remains unchanged.
- WhatsApp plugin path now has endpoint contract support from the Node bridge runtime.
