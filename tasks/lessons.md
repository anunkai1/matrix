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

### 2026-02-27T08:08:01+10:00 - Urgent HA Actions Must Use Stable Credentials and Fast Preflight
- Mistake pattern: I let simple HA requests fail late because scripts depended on a changing env file and I troubleshot before applying an immediate fallback action.
- Prevention rule: Keep HA ops on a dedicated stable env path, run API preflight before scheduling, and for urgent user requests execute the direct action first when safe.
- Where/when applied: Every HA on/off/mode/temperature request and before creating any HA schedule timer.

### 2026-02-27T08:48:27+10:00 - Avoid Ad-Hoc systemd-run Shell Payloads for HA Climate Mode
- Mistake pattern: A one-off inline `systemd-run` climate mode command failed at execution due shell/env interpolation behavior in the transient unit.
- Prevention rule: Use dedicated versioned scripts (`set_climate_mode.sh` and `schedule_climate_mode.sh`) with explicit arguments and preflight checks, not ad-hoc inline command strings.
- Where/when applied: Any future HA climate mode request, especially scheduled `--at`/`--in` actions.

### 2026-02-27T09:38:29+10:00 - Require Explicit HA Prefix for Deterministic Chat Routing
- Mistake pattern: Free-form chat requests could still flow into generic execution paths even after HA scripts were hardened.
- Prevention rule: Reserve `HA` / `Home Assistant` as explicit routing triggers and force those requests into stateless HA-script-only policy mode.
- Where/when applied: Telegram bridge message routing before memory/command handling in `src/telegram_bridge/handlers.py`.

### 2026-02-27T11:39:12+10:00 - Confirm Bot Purpose Before Recommending Security Model
- Mistake pattern: I assumed a narrowly scoped HA bot design before confirming the user wanted a general helper bot with mixed advice/file + HA use.
- Prevention rule: For new bot/service requests, confirm intended capability scope first (general assistant vs single-domain ops) before proposing privilege boundaries and routing model.
- Where/when applied: Initial design step for any new Telegram bot/service rollout on Server3, before drafting implementation plan.
