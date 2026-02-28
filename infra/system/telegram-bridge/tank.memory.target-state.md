# Tank Memory Target State (Server3)

Last verified: 2026-02-28T13:03:11+10:00 (Australia/Brisbane)

## Paths
- Memory DB: `/home/tank/.local/state/telegram-tank-bridge/memory.sqlite3`
- Runtime code: `/home/tank/tankbot/src/telegram_bridge/memory_engine.py`

## Expected Runtime Behavior
- Canonical mode label is `all_context`.
- Legacy alias `full` is accepted for backward compatibility.
- Summary formatter supports structured sections:
  - `Objective`
  - `Decisions Made`
  - `Current State`
  - `Open Items`
  - `User Preferences`
  - `Risks/Blockers`

## Verified Live State
- `chat_summaries` row count: `0` (no summary rows present at verification time).
- `memory_config` rows are canonicalized as `all_context`.
- `regenerate_summaries.py` run result: `regenerated_summaries=0` (no-op due zero summary rows).
