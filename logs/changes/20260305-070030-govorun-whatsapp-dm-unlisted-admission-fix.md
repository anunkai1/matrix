# Govorun WhatsApp DM non-reply fix: unlisted private-chat admission (live + repo mirror)

## Objective
Resolve "not replying" for 1:1 WhatsApp chats while keeping group access controls.

## Root Cause
- Private chat prefix bypass was configured (`TELEGRAM_REQUIRE_PREFIX_IN_PRIVATE=false`), but private 1:1 chats still did not reply.
- Two gates blocked new DMs:
  1) Node bridge applied `WA_ALLOWED_CHAT_IDS` to both groups and DMs.
  2) Python bridge denied any chat id not in `TELEGRAM_ALLOWED_CHAT_IDS`.

## Changes Applied
1. Python bridge allowlist gating (configurable private-chat bypass):
   - `src/telegram_bridge/main.py`
     - Added config flag: `TELEGRAM_ALLOW_PRIVATE_CHATS_UNLISTED` (default `false`).
   - `src/telegram_bridge/handlers.py`
     - Allowlisted-chat check now permits private chats when `allow_private_chats_unlisted=true`.
2. Node bridge group-only numeric allowlist enforcement:
   - `ops/whatsapp_govorun/bridge/src/index.mjs`
   - `WA_ALLOWED_CHAT_IDS` is now enforced for groups only.
   - DM admission continues to be controlled by `WA_ALLOWED_DMS` + `WA_DM_ALWAYS_RESPOND`.
3. Tests:
   - `tests/telegram_bridge/test_bridge_core.py`
     - Added config/env coverage for `TELEGRAM_ALLOW_PRIVATE_CHATS_UNLISTED`.
     - Added private unlisted-chat acceptance test.
4. Env/docs mirrors:
   - `infra/env/govorun-whatsapp-bridge.server3.redacted.env`
   - `infra/env/govorun-whatsapp-bridge.env.example`
   - `infra/env/whatsapp-govorun-bridge.env.example`
   - `infra/env/whatsapp-govorun-bridge.server3.redacted.env`
   - `docs/runbooks/whatsapp-govorun-operations.md`
   - `SERVER3_SUMMARY.md`

## Live Apply
- Updated live files:
  - `/home/govorun/govorunbot/src/telegram_bridge/main.py`
  - `/home/govorun/govorunbot/src/telegram_bridge/handlers.py`
  - `/home/govorun/whatsapp-govorun/app/src/index.mjs`
- Updated live env:
  - `/etc/default/govorun-whatsapp-bridge`: `TELEGRAM_ALLOW_PRIVATE_CHATS_UNLISTED=true`
- Restarted services in safe order:
  1) `whatsapp-govorun-bridge.service`
  2) `govorun-whatsapp-bridge.service`

## Verification
- Unit tests:
  - `python3 -m unittest -q tests.telegram_bridge.test_bridge_core`
  - `Ran 107 tests ... OK`
- Syntax checks:
  - `node --check ops/whatsapp_govorun/bridge/src/index.mjs`
  - `sudo -u govorun node --check /home/govorun/whatsapp-govorun/app/src/index.mjs`
- Live runtime state:
  - `systemctl is-active whatsapp-govorun-bridge.service govorun-whatsapp-bridge.service` -> both `active`
  - `/etc/default/govorun-whatsapp-bridge` confirms:
    - `TELEGRAM_REQUIRE_PREFIX_IN_PRIVATE=false`
    - `TELEGRAM_ALLOW_PRIVATE_CHATS_UNLISTED=true`

## Residual Risk
- End-to-end user DM confirmation still requires a fresh real WhatsApp 1:1 message after rollout.
