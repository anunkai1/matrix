# Change Record - 2026-02-28

- Timestamp (Australia/Brisbane): 2026-02-28T11:41:46+10:00
- Change type: repo + live-state
- Objective: Improve memory-summary quality with a structured format, then regenerate existing live summaries so current behavior is immediately useful.

## What Changed
- Updated summary generation in:
  - `src/telegram_bridge/memory_engine.py`
  - New structured summary sections:
    - `Objective`
    - `Decisions Made`
    - `Current State`
    - `Open Items`
    - `User Preferences`
    - `Risks/Blockers`
  - Added noise cleanup/dedupe helpers for summary lines.
  - Added `MemoryEngine.regenerate_summaries(...)` to rebuild existing `chat_summaries` rows.
- Added regeneration helper script:
  - `ops/telegram-bridge/regenerate_summaries.py`
- Updated docs:
  - `docs/telegram-architect-bridge.md` (helper listed + usage example)
- Updated tests:
  - `tests/telegram_bridge/test_memory_engine.py`
  - Added structured-summary assertions and regeneration test.
- Updated rolling/session docs:
  - `SERVER3_SUMMARY.md`
  - `LESSONS.md`

## Live Change Applied
- Target path:
  - `/home/architect/.local/state/telegram-architect-bridge/memory.sqlite3`
- Command run:
  - `python3 ops/telegram-bridge/regenerate_summaries.py --db /home/architect/.local/state/telegram-architect-bridge/memory.sqlite3`
- Result:
  - `regenerated_summaries=6 scope=all keys`

## Verification
- Before regeneration:
  - `SELECT COUNT(*), SUM(summary_text LIKE 'User topics:%') FROM chat_summaries;`
  - Result: `6 | 6`
- After regeneration:
  - `SELECT COUNT(*), SUM(summary_text LIKE 'Objective:%') FROM chat_summaries;`
  - Result: `6 | 6`
- Conversation-key distribution unchanged:
  - `tg:211761499 -> 4`
  - `tg:-5144577688 -> 2`
- Tests:
  - `python3 -m unittest tests/telegram_bridge/test_memory_engine.py` -> pass
  - `python3 -m unittest tests/telegram_bridge/test_bridge_core.py` -> pass

## Notes
- Regeneration rewrites existing summary text/JSON fields only; it does not delete messages/facts or change summary row counts.
