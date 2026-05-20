# Server3 Dream Loop V2 Goal Brief

Use this file as the single implementation brief for the bridge `/goal` command when you want the full `v2` dream-loop scope completed in one run.

## Goal

Implement dream-loop spec `v2` exactly to the current boundary defined in [docs/specs/server3-dream-loop.md](/home/architect/matrix/docs/specs/server3-dream-loop.md).

`v2` is complete only when all of the following are true:

- a declared check registry exists as a first-class implementation object
- the runner uses that registry to select and execute fixed and conditional checks rather than relying only on hard-coded orchestration
- the minimum required `v2` check set exists in the registry:
  - `truth_files_fingerprint`
  - `runtime_manifest_vs_status`
  - `runtime_observer_truth`
  - `policy_watch_truth`
  - `telegram_context_routing_truth`
  - `server3_summary_truth`
- each registry entry includes at minimum:
  - `check_id`
  - `truth_area`
  - `mode`
  - `trigger`
  - `inputs`
  - `executor`
  - `mismatch_rule`
  - `correction_target`
  - `severity`
- every `correction_target` explicitly declares whether it writes to truth state, health state, run state, or an approved secondary rendered document
- `latest_truth_state.json` includes registry-driven check results, approved rendered-doc alignment facts, and stale-context warning state for eligible scopes
- `latest_health_state.json` keeps health truth separate from structural truth and only adds new health checks through the registry
- `latest_run_state.json` records executed registry checks, skipped registry checks, and reasons
- `server3_summary_truth` validates only explicitly mapped `SERVER3_SUMMARY.md` fields against structured truth or approved live inputs already in scope
- `SERVER3_SUMMARY.md` is the only approved secondary truth surface in `v2`
- unmapped prose in `SERVER3_SUMMARY.md` is not rewritten
- stale-context warning state is persisted per eligible scope
- persisted stale-context state includes both outstanding-warning state and handled-by-reset state
- `/truth_status` works as a read-only scope-aware view over current dream-loop truth/run/stale state
- `/reset` clears stale carried context for the current scope and marks the outstanding stale warning as handled
- tests cover registry execution, summary-alignment mapping, stale-context state transitions, `/truth_status`, and `/reset`

## Boundaries

Do not add any of the following unless the spec is changed first:

- open-ended scanning of the whole repo
- free-form capability inference without a declared check
- automatic rewriting of arbitrary docs outside approved correction targets
- broader approved secondary docs beyond `SERVER3_SUMMARY.md`
- proactive Telegram stale-context warning delivery
- broader conversational commands beyond `/truth_status` and `/reset`
- commit/push automation
- unrelated bridge, runtime, or repo refactors

## Implementation Standard

- inspect current code before editing
- make the smallest scoped changes that satisfy `v2`
- preserve existing `v1` artifacts and bounded-runner behavior unless `v2` explicitly extends them
- verify behavior with targeted tests before declaring the goal complete
- if blocked by a real ambiguity or failing prerequisite, state the blocker clearly and stop
