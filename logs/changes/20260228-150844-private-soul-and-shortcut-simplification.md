# Server3 Change Record - Private SOUL Wiring and Shortcut Simplification

Timestamp: 2026-02-28T15:08:44+10:00
Timezone: Australia/Brisbane

## Objective
- Keep `SOUL.md` private/local-only while still making it part of startup behavior.
- Simplify shortcut policy to the single current shortcut (`mansplain:`).

## Scope
- In scope:
  - local-only file `private/SOUL.md` (not committed)
  - `ARCHITECT_INSTRUCTION.md`
  - `SERVER3_SUMMARY.md`
  - this `logs/changes` record
- Out of scope:
  - no runtime/service/env/code-path changes

## Changes Made
1. Created local private guidance file:
   - `private/SOUL.md`
2. Updated session-start rule in `ARCHITECT_INSTRUCTION.md`:
   - read `private/SOUL.md` if present
   - explicitly treat it as local-only and non-committed
3. Simplified shortcut section from general "phrases" to current single shortcut model:
   - `mansplain:` retained
   - added rule to add more shortcuts only when explicitly requested
4. Added rolling summary entry for this policy/docs update.

## Validation
- `private/SOUL.md` exists locally.
- `ARCHITECT_INSTRUCTION.md` includes startup read rule for `private/SOUL.md` and single-shortcut policy language.

## Notes
- `private/*` is already ignored by repo `.gitignore`, so private file remains local-only by default.
