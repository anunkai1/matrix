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

### 2026-02-26T08:58:28+10:00 - Approval Gate Must Include Approval Target
- Mistake pattern: I repeated approval-gate messaging issues by logging similar lessons more than once without enforcing one strict paused-state output format.
- Prevention rule: At any approval pause, output `Status`, `Approval for` (one-sentence objective + exact scope/files), `Next action` with the exact approval phrase, and `No commands will run` line before stopping.
- Where/when applied: Immediately after every AI Prompt for Action when execution is blocked waiting for user approval.

### 2026-02-23T07:24:07+10:00 - One-Shot Timer Verification
- Mistake pattern: I initially reported no scheduled action existed because I checked active timers/repo notes but not unit journal history.
- Prevention rule: For any schedule verification, check both current units and historical evidence (`systemctl status <unit>` and `journalctl -u <timer> -u <service>` in the target time window).
- Where/when applied: Incident/ops checks when user asks whether a timed HA action was planned or executed.
