# Server3 Ralph Loop

`Ralph` means `Reliability, Availability, Latency, Price, Health`.

Purpose:
- continuously inspect live Architect bridge telemetry
- rank the highest-value operational optimization target
- refresh a machine-readable backlog plus a human-readable latest report

Scope:
- reads live bridge/system telemetry
- writes ranked outputs under `RALPH_LOOP_STATE_DIR`
- does not edit code or deploy changes by itself

Execution contract:
- Ralph measure/rank mode is live now.
- Ralph execute mode is intended to operate with broad owner-authorized autonomy on Server3.

Allowed in execute mode:
- edit repo files anywhere needed for the selected optimization target
- edit non-repo files on Server3 when required for the fix, including env files, service files, state files, and runbook/config paths
- restart or reload services when needed to complete or validate a change
- run repeated investigate/edit/test/measure cycles without waiting for owner confirmation
- make multi-file changes when the optimization target spans several layers
- deploy validated fixes to the live Server3 runtime
- keep iterating on the current top target until it is either improved, blocked by a real external constraint, or superseded by fresher telemetry

Not allowed in execute mode:
- actions outside Server3 or outside the named runtime/service scope unless the task explicitly expands there
- destructive or irreversible actions without a clear operational reason and recoverable path
- credential, payment, or security-sensitive changes that require a human trust decision
- silently continuing after failed verification as if a fix landed

Practical meaning:
- this is not a small-box refactor bot contract
- it is an owner-authorized autonomous operator contract for Server3 optimization work
- the remaining limits are only the hard stop conditions from the workspace policy, not extra Ralph-specific guardrails

Primary files:
- loop script: `ops/ralph_loop/ralph_loop.py`
- latest report: `/var/lib/server3-ralph-loop/latest.md`
- latest backlog: `/var/lib/server3-ralph-loop/optimization_backlog.json`
- history: `/var/lib/server3-ralph-loop/history.jsonl`

Commands:
- run once: `python3 /home/architect/matrix/ops/ralph_loop/ralph_loop.py collect`
- install timer: `bash /home/architect/matrix/ops/ralph_loop/install_systemd.sh apply`
- remove timer: `bash /home/architect/matrix/ops/ralph_loop/install_systemd.sh rollback`

Default cadence:
- `server3-ralph-loop.timer` runs hourly with a small randomized delay

Current intent:
- keep the next optimization target fresh without owner prompting
- feed autonomous engineering passes with real operational evidence instead of guesswork
