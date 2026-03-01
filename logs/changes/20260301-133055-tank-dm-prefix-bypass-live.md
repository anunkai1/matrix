# Live Change Record - 2026-03-01T13:30:55+10:00

## Objective
Allow Tank to respond to all direct 1:1 messages without requiring the `tank` keyword, while keeping required-prefix protection in group chats.

## Repo State
- Branch: `main`
- Repo: `/home/architect/matrix`

## Changes Made
1. Added a new bridge config flag:
   - `TELEGRAM_REQUIRE_PREFIX_IN_PRIVATE` (default `true` for backward compatibility)
2. Updated message routing logic:
   - If `TELEGRAM_REQUIRE_PREFIX_IN_PRIVATE=false` and chat type is private, required-prefix check is skipped.
   - Group chats still enforce `TELEGRAM_REQUIRED_PREFIXES`.
3. Added test coverage:
   - load-config env parsing for the new flag
   - private chat no-prefix allowed when flag is false
   - group chat still requires prefix when flag is false
4. Updated Tank env files:
   - Live `/etc/default/telegram-tank-bridge` set `TELEGRAM_REQUIRE_PREFIX_IN_PRIVATE=false`
   - Mirror `infra/env/telegram-tank-bridge.server3.redacted.env` updated
   - Example `infra/env/telegram-tank-bridge.env.example` updated
5. Restarted Tank bridge service:
   - `sudo systemctl restart telegram-tank-bridge.service`

## Verification Evidence
- Unit tests:
  - `python3 -m unittest tests.telegram_bridge.test_bridge_core`
  - Result: `Ran 79 tests ... OK`
- Live env check:
  - `grep '^TELEGRAM_REQUIRE_PREFIX_IN_PRIVATE=' /etc/default/telegram-tank-bridge`
  - Result: `TELEGRAM_REQUIRE_PREFIX_IN_PRIVATE=false`
- Service check:
  - `systemctl is-active telegram-tank-bridge.service`
  - Result: `active`

## Repo Mirrors Updated
- `src/telegram_bridge/main.py`
- `src/telegram_bridge/handlers.py`
- `tests/telegram_bridge/test_bridge_core.py`
- `infra/env/telegram-tank-bridge.server3.redacted.env`
- `infra/env/telegram-tank-bridge.env.example`
- `SERVER3_SUMMARY.md`

## Rollback
- Set `TELEGRAM_REQUIRE_PREFIX_IN_PRIVATE=true` (or remove the key to use default strict behavior) in `/etc/default/telegram-tank-bridge`
- Restart `telegram-tank-bridge.service`
