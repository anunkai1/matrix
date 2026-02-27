# Change Record - 2026-02-28

- Timestamp (Australia/Brisbane): 2026-02-28T09:53:42+10:00
- Change type: repo-only
- Objective: Remove deprecated lessons compatibility stub and delete now-empty `tasks/` folder.

## What Changed
- Removed file:
  - `tasks/lessons.md`
- Removed empty directory:
  - `tasks/`
- Updated summary:
  - `SERVER3_SUMMARY.md`
  - added rolling entry noting full cleanup after lessons migration to `docs/instructions/lessons.md`.

## Verification
- `test ! -e tasks/lessons.md && test ! -d tasks`
  - Result: pass
- `test -f docs/instructions/lessons.md`
  - Result: pass

## Notes
- `ARCHITECT_INSTRUCTION.md` already points to `docs/instructions/lessons.md` as the canonical lessons path.
- Historical logs may still mention `tasks/lessons.md`; these are retained as audit history.
