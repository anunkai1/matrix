# Change Record - 2026-02-28

- Timestamp (Australia/Brisbane): 2026-02-28T10:32:23+10:00
- Change type: repo-only
- Objective: Remove the now-unneeded lessons redirect stub and keep `LESSONS.md` as the single canonical path.

## What Changed
- Deleted compatibility redirect file:
  - `docs/instructions/lessons.md`
- Kept canonical lessons file:
  - `LESSONS.md`
- Updated rolling summary:
  - `SERVER3_SUMMARY.md`

## Verification
- `test -f LESSONS.md`
  - Result: pass
- `test ! -f docs/instructions/lessons.md`
  - Result: pass
- `rg -n "LESSONS.md" ARCHITECT_INSTRUCTION.md`
  - Result: pass (authoritative references remain on root `LESSONS.md`).

## Notes
- Historical logs and archive entries may still mention `docs/instructions/lessons.md` as past state; this is expected audit history.
