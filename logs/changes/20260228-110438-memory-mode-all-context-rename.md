# Change Record - 2026-02-28

- Timestamp (Australia/Brisbane): 2026-02-28T11:04:38+10:00
- Change type: repo-only
- Objective: Rename ambiguous memory mode label `full` to clearer `all_context` while preserving backward compatibility.

## What Changed
- Updated memory engine mode canonical label:
  - `src/telegram_bridge/memory_engine.py`
  - canonical mode now `all_context`
  - legacy alias `full` is still accepted in `/memory mode ...`
  - existing legacy DB rows with `mode='full'` are normalized to `all_context` during schema ensure.
- Updated memory help/usage text:
  - `src/telegram_bridge/memory_engine.py`
  - command usage now shows `/memory mode all_context` and marks `/memory mode full` as legacy alias.
- Updated tests:
  - `tests/telegram_bridge/test_memory_engine.py`
  - default mode test renamed for clarity and legacy alias compatibility test added.
- Updated docs:
  - `README.md`
  - `docs/telegram-architect-bridge.md`
- Updated summary and lessons:
  - `SERVER3_SUMMARY.md`
  - `LESSONS.md`

## Verification
- Unit tests:
  - `python3 -m unittest tests/telegram_bridge/test_memory_engine.py`
- Source checks:
  - `rg -n "mode all_context|mode full|MODE_FULL_LEGACY_ALIAS" src/telegram_bridge/memory_engine.py tests/telegram_bridge/test_memory_engine.py docs/telegram-architect-bridge.md README.md`
- Behavior checks:
  - `/memory mode all_context` accepted.
  - `/memory mode full` still accepted and maps to canonical `all_context`.

## Notes
- Backward compatibility was intentionally preserved for existing users and stored state.
