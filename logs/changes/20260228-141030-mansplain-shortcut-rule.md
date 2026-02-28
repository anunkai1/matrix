# Server3 Change Record - Mansplain Shortcut Rule

Timestamp: 2026-02-28T14:10:30+10:00
Timezone: Australia/Brisbane

## Objective
- Persist a user shortcut phrase so `mansplain:` reliably forces beginner-friendly explanations.

## Scope
- In scope:
  - `ARCHITECT_INSTRUCTION.md`
  - `SERVER3_SUMMARY.md`
  - this `logs/changes` record
- Out of scope:
  - no runtime/service/env/code-path changes

## Changes Made
1. Added new persistent shortcut section in `ARCHITECT_INSTRUCTION.md`:
   - trigger: `mansplain:`
   - behavior: plain-language, logical, low-jargon explanation style
2. Added rolling summary entry noting the new shortcut rule.
3. Added this trace record for auditability.

## Validation
- `ARCHITECT_INSTRUCTION.md` now contains explicit shortcut semantics and behavior rules.

## Notes
- Existing unrelated local source-file modifications were intentionally left untouched.
