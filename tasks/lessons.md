# Lessons Log

Purpose: capture recurring mistake patterns and prevention rules after user corrections.

## Entry Template (Minimal Schema)

Use one section per lesson:

### YYYY-MM-DDTHH:MM:SS+10:00 - Short Lesson Title
- Mistake pattern: what went wrong
- Prevention rule: the concrete rule to avoid repeat
- Where/when applied: exact workflow step, file area, or decision point where rule must be used

## Lessons

<!-- Add new lessons below this line using the template above. -->

### 2026-02-22T20:24:56+10:00 - Approval Gate Output Clarity
- Mistake pattern: I paused at the mandatory approval gate but did not immediately make the blocked state and next action obvious enough.
- Prevention rule: When waiting for required approval, reply with explicit status (`paused pending approval`) and one clear action command the user can send.
- Where/when applied: Immediately after any AI Prompt for Action where execution is blocked until user confirmation.
