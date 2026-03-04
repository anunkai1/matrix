# Govorun WhatsApp DM without prefix: chat.type propagation fix (live + repo mirror)

## Objective
Enable 1:1 WhatsApp chats to work without summon prefix while keeping group-prefix enforcement intact.

## Root Cause
- Python prefix policy checks private-chat bypass using `message.chat.type == "private"`.
- In WhatsApp plugin-mode updates, Node payload only sent `chat.id` (no `chat.type`).
- As a result, Python treated DM updates as non-private and still applied prefix enforcement.

## Changes Applied
1. Node update payload fix:
   - File: `ops/whatsapp_govorun/bridge/src/index.mjs`
   - In `buildIncomingMessagePayload(...)`, `chat` now includes:
     - `type: "private"` for DMs
     - `type: "group"` for groups
2. Env mirror synchronization (existing live behavior documented):
   - File: `infra/env/govorun-whatsapp-bridge.server3.redacted.env`
   - Added mirrored keys:
     - `TELEGRAM_REQUIRED_PREFIXES=@говорун,говорун,govorun`
     - `TELEGRAM_REQUIRED_PREFIX_IGNORE_CASE=true`
     - `TELEGRAM_REQUIRE_PREFIX_IN_PRIVATE=false`
3. Ops docs/example updates:
   - `docs/runbooks/whatsapp-govorun-operations.md`
   - `infra/env/govorun-whatsapp-bridge.env.example`
4. Rolling summary update:
   - `SERVER3_SUMMARY.md`

## Live Apply
- Deployed updated Node runtime file to:
  - `/home/govorun/whatsapp-govorun/app/src/index.mjs`
- Restarted in safe order:
  1. `whatsapp-govorun-bridge.service`
  2. `govorun-whatsapp-bridge.service`

## Verification
- Syntax checks:
  - `node --check ops/whatsapp_govorun/bridge/src/index.mjs`
  - `sudo -u govorun node --check /home/govorun/whatsapp-govorun/app/src/index.mjs`
- Live code presence:
  - `type: isGroup ? 'group' : 'private'` present in deployed runtime file.
- Live policy flags confirmed:
  - `TELEGRAM_REQUIRE_PREFIX_IN_PRIVATE=false`
  - `TELEGRAM_REQUIRED_PREFIXES=@говорун,говорун,govorun`
- Services after restart:
  - `whatsapp-govorun-bridge.service` active
  - `govorun-whatsapp-bridge.service` active

## Residual Risk
- End-to-end DM behavior was validated through code-path and live runtime checks, but not with a fresh manual WhatsApp DM send in this change window.
