# Change Record - 2026-02-28

- Timestamp (Australia/Brisbane): 2026-02-28T09:50:03+10:00
- Change type: repo-only
- Objective: Move lessons log from `tasks/` into instruction docs area, while preserving backward compatibility.

## What Changed
- Created canonical lessons file at:
  - `docs/instructions/lessons.md`
  - content copied from prior `tasks/lessons.md`
- Updated authoritative instruction references in:
  - `ARCHITECT_INSTRUCTION.md`
  - changed path references from `tasks/lessons.md` to `docs/instructions/lessons.md`
- Replaced old path with compatibility stub:
  - `tasks/lessons.md`
  - now points to the canonical path and instructs not to add lessons there.
- Updated running summary:
  - `SERVER3_SUMMARY.md`

## Verification
- `rg -n "tasks/lessons.md|docs/instructions/lessons.md" ARCHITECT_INSTRUCTION.md`
  - Result: references now target `docs/instructions/lessons.md`.
- `test -f docs/instructions/lessons.md && test -f tasks/lessons.md`
  - Result: both files exist.

## Notes
- This is a documentation/instruction path migration only; no runtime behavior changes.
