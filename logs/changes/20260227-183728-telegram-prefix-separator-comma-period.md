# Live Change Record - 2026-02-27T18:37:28+10:00

## Objective
Allow required-prefix Telegram requests to accept comma and period separators right after a matched prefix (for example `tank, ...` and `tank. ...`).

## Repo State
- Branch: `main`
- Repo: `/home/architect/matrix`

## Root Cause Evidence
- Prefix parsing accepted only Unicode whitespace, `:`, and `-` after required prefixes.
- Requests using natural punctuation right after a prefix were ignored as `prefix_required`.

## Changes Applied (Repo)
1. Updated required-prefix parser separators:
   - `src/telegram_bridge/handlers.py`
   - accepted punctuation now: `:`, `-`, `,`, `.` (plus Unicode whitespace)
2. Added regression coverage:
   - `tests/telegram_bridge/test_bridge_core.py`
   - added passing cases for `@helper, summarize this` and `@helper. summarize this`
3. Updated operator docs:
   - `docs/telegram-architect-bridge.md`
   - documented accepted separators after prefix matches
4. Updated running summary:
   - `SERVER3_SUMMARY.md`

## Verification
- Command:
  - `python3 -m unittest -q tests.telegram_bridge.test_bridge_core`
- Outcome:
  - `Ran 37 tests ... OK`
  - includes passing comma/period separator cases in `test_strip_required_prefix_variants`.

## Notes
- This change is committed in repo state; running bridge services require restart/redeploy to apply updated parser behavior.
