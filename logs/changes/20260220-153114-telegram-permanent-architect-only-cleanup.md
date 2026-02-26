# Change Record: Telegram Bridge Permanent Architect-Only Cleanup

## Timestamp
- 2026-02-20 15:31:14 AEST

## Scope
- Removed Home Assistant routing/code/docs artifacts and finalized permanent Architect-only runtime behavior for the Telegram bridge.

## Live Changes Applied
- Updated live env `/etc/default/telegram-architect-bridge`:
  - removed residual `TELEGRAM_HA_ENABLED` key (no HA keys remain)
  - backup: `/etc/default/telegram-architect-bridge.bak-20260220-153107-architect-only-final`
- Archived stale state files in `/home/architect/.local/state/telegram-architect-bridge/`:
  - `ha_conversations.json` -> `ha_conversations.json.bak-20260220-153107-architect-only`
  - `ha_conversations.json.bak-20260220-145256` -> `ha_conversations.json.bak-20260220-145256.bak-20260220-153107-architect-only`
  - `pending_actions.json` -> `pending_actions.json.bak-20260220-153107-architect-only`
- Restarted bridge service and verified healthy startup.

## Repo Changes
- Removed HA runtime helper module:
  - deleted `src/telegram_bridge/ha_control.py`
- Removed HA package artifact and validator:
  - deleted `infra/home_assistant/packages/architect_executor.yaml`
  - deleted `ops/home-assistant/validate_architect_package.sh`
- Refactored bridge runtime to Architect-only routing:
  - updated `src/telegram_bridge/main.py`
  - removed split chat routing and HA conversation handling branches
  - `/help` now reports Architect-only behavior for all allowlisted chats
  - startup logging now reports Architect-only routing
- Updated smoke test:
  - `src/telegram_bridge/smoke_test.sh` (removed HA compile/validator step)
- Updated docs and env templates:
  - `docs/telegram-architect-bridge.md`
  - `infra/env/telegram-architect-bridge.env.example`
  - `infra/env/telegram-architect-bridge.server3.redacted.env`
  - `README.md`

## Verification Evidence
- Validation:
  - `python3 -m py_compile src/telegram_bridge/main.py`
  - `bash src/telegram_bridge/smoke_test.sh` (pass)
- Service status:
  - `telegram-architect-bridge.service` active/running
- Startup log confirms:
  - `Bridge started. Allowed chats=[-5144577688, 211761499]`
  - `Architect-only routing active for all allowlisted chats.`
