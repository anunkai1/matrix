# Change Record - 2026-02-28

- Timestamp (Australia/Brisbane): 2026-02-28T08:27:36+10:00
- Change type: repo-only
- Objective: Close H1 by enforcing required-prefix gating for voice/media requests that previously bypassed checks when prompt text was empty.

## What Changed
- Updated prefix gate condition in `src/telegram_bridge/handlers.py`:
  - from `if prompt_input and config.required_prefixes:`
  - to `if prompt_input is not None and config.required_prefixes:`
  - Result: voice-without-caption (empty prompt string) is now checked and rejected when prefixes are required.
- Added regression tests in `tests/telegram_bridge/test_bridge_core.py`:
  - `test_handle_update_ignores_voice_without_prefix_when_required`
  - `test_handle_update_accepts_prefixed_voice_caption_when_required`

## Verification
- `python3 -m unittest tests/telegram_bridge/test_bridge_core.py -v`
  - Result: `Ran 40 tests` -> `OK`
- `python3 -m unittest discover -s tests -v`
  - Result: `Ran 52 tests` -> `OK`

## Notes
- No live `/etc` or systemd changes were applied in this change set.
- This change only addresses H1 (prefix bypass on voice/media); H2-H9 remain pending.
