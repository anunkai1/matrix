# Server3 Change Record - Remove mansplain Shortcut

Timestamp: 2026-02-28T15:19:36+10:00
Timezone: Australia/Brisbane

## Objective
- Remove the `mansplain:` shortcut completely from active instruction/policy files.

## Scope
- In scope:
  - `ARCHITECT_INSTRUCTION.md`
  - local-only `private/SOUL.md`
  - `SERVER3_SUMMARY.md`
  - this `logs/changes` record
- Out of scope:
  - runtime/service/env/code-path changes

## Changes Made
1. Removed the `mansplain:` shortcut section from `ARCHITECT_INSTRUCTION.md`.
2. Removed the `Shortcut currently in use` block from local `private/SOUL.md`.
3. Added a rolling summary entry noting that no shortcut is currently configured.

## Validation
- `ARCHITECT_INSTRUCTION.md` no longer contains active shortcut trigger text.
- `private/SOUL.md` no longer contains a shortcut block.

## Notes
- `private/SOUL.md` remains local-only and is not committed.
