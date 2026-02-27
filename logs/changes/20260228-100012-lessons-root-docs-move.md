# Change Record - 2026-02-28

- Timestamp (Australia/Brisbane): 2026-02-28T10:00:12+10:00
- Change type: repo-only
- Objective: Place lessons log with main top-level docs while keeping backward-compatible references.

## What Changed
- Set canonical lessons path to root-level doc:
  - `LESSONS.md`
- Kept compatibility redirect file:
  - `docs/instructions/lessons.md`
  - now points to `LESSONS.md`
- Updated authoritative instruction references in:
  - `ARCHITECT_INSTRUCTION.md`
  - lessons path now `LESSONS.md`
- Updated running summary:
  - `SERVER3_SUMMARY.md`

## Verification
- `test -f LESSONS.md`
  - Result: pass
- `test -f docs/instructions/lessons.md`
  - Result: pass (redirect stub)
- `rg -n "LESSONS.md|docs/instructions/lessons.md" ARCHITECT_INSTRUCTION.md`
  - Result: authoritative references use `LESSONS.md`.

## Notes
- Historical logs may reference previous locations (`tasks/lessons.md`, `docs/instructions/lessons.md`) as part of audit history.
