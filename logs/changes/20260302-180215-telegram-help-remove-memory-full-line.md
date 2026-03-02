# Live Change Record - 2026-03-02T18:02:15+10:00

## Objective
Clean up Telegram `/h` help output by removing the legacy memory-mode alias line for `full`.

## Repo State
- Branch: `main`
- Repo: `/home/architect/matrix`

## Repo Changes Applied
- Removed legacy help line from runtime memory help list:
  - `src/telegram_bridge/memory_engine.py`
- Removed corresponding line from bridge command docs:
  - `docs/telegram-architect-bridge.md`
- Added regression assertion so help output does not reintroduce the line:
  - `tests/telegram_bridge/test_bridge_core.py`

## Behavioral Notes
- `/memory mode full` alias support remains functional in parser/behavior.
- Only the displayed help/documentation line was removed.

## Verification Outcomes
1. `python3 -m unittest tests.telegram_bridge.test_bridge_core`
   - Result: `Ran 85 tests ... OK`
2. `python3 -m unittest tests.telegram_bridge.test_memory_engine`
   - Result: `Ran 14 tests ... OK`

## Repo Mirrors Updated
- `src/telegram_bridge/memory_engine.py`
- `docs/telegram-architect-bridge.md`
- `tests/telegram_bridge/test_bridge_core.py`
- `SERVER3_SUMMARY.md`
- `logs/changes/20260302-180215-telegram-help-remove-memory-full-line.md`
