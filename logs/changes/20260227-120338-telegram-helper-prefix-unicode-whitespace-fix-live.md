# Live Change Record - 2026-02-27T12:03:38+10:00

## Objective
Fix helper bot non-replies caused by prefix parsing failures when Telegram messages include Unicode whitespace (for example mobile non-breaking space) after mention prefixes.

## Repo State
- Branch: `main`
- Repo: `/home/architect/matrix`

## Root Cause
- Helper bridge was receiving updates but logging `bridge.request_ignored` with reason `prefix_required`.
- Prefix parser only accepted ASCII space/tab delimiters and rejected Unicode whitespace (`\u00a0`) after prefixes like `@mavali_helper_bot`.

## Code Changes
1. Updated prefix parsing in `src/telegram_bridge/handlers.py`:
   - Accepts any Unicode whitespace after configured prefixes.
   - Keeps `:` and `-` delimiters behavior.
2. Added regression tests in `tests/telegram_bridge/test_bridge_core.py`:
   - `@helper\u00a0...` accepted.
   - prefix-only with Unicode whitespace resolves correctly.

## Validation
- `python3 -m unittest tests.telegram_bridge.test_bridge_core` -> passed
- `python3 -m unittest discover -s tests -p 'test_*.py'` -> passed
- `python3 src/telegram_bridge/main.py --self-test` -> `self-test: ok`
- parser spot-check:
  - `@mavali_helper_bot\u00a0hi` -> `(True, 'hi')`

## Live Rollout
1. Restarted helper service:
   - `UNIT_NAME=telegram-helper-bridge.service bash ops/telegram-bridge/restart_and_verify.sh`
2. Verified service healthy:
   - `ActiveState=active`
   - `SubState=running`
   - `ExecMainStartTimestamp=Fri 2026-02-27 12:03:18 AEST`
   - `MainPID=444019` (at verification time)

## Notes
- This fix only affects helper prefix matching behavior.
- Access-control allowlist behavior remains unchanged.
