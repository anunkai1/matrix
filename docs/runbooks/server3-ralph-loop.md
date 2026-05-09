# Server3 Ralph Autopilot

`Ralph` means `Reliability, Availability, Latency, Price, Health`.

Canonical name:
- `Server3 Ralph Autopilot`
- short name in conversation: `Ralph`

Purpose:
- continuously inspect live Architect bridge telemetry
- rank the highest-value operational optimization target
- refresh a machine-readable backlog plus a human-readable latest report
- report its activity back to Telegram

Scope:
- reads live bridge/system telemetry
- writes ranked outputs under `RALPH_LOOP_STATE_DIR`
- can run one autonomous optimization pass and then re-rank

Execution contract:
- Ralph measure/rank mode is live now.
- Ralph execute mode is live now with broad owner-authorized autonomy on Server3.

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
- execution results: `/var/lib/server3-ralph-loop/execution_results.jsonl`

Commands:
- run once: `python3 /home/architect/matrix/ops/ralph_loop/ralph_loop.py collect`
- execute top live target once: `python3 /home/architect/matrix/ops/ralph_loop/ralph_loop.py execute`
- execute a named target once: `python3 /home/architect/matrix/ops/ralph_loop/ralph_loop.py execute --candidate-id progress_edit_noise`
- generate/send the daily report now: `python3 /home/architect/matrix/ops/ralph_loop/ralph_loop.py notify-daily`
- install timer: `bash /home/architect/matrix/ops/ralph_loop/install_systemd.sh apply`
- remove timer: `bash /home/architect/matrix/ops/ralph_loop/install_systemd.sh rollback`

Default cadence:
- `server3-ralph-loop.timer` runs hourly with a small randomized delay
- the live service is now wired to `execute`, so each timer fire can rank, act once, verify, record a result, and re-rank
- `server3-ralph-daily-report.timer` sends one Markdown daily report document at `20:15` AEST

Current intent:
- keep the next optimization target fresh without owner prompting
- let Ralph pick one live target, run a real Codex optimization pass, verify it, commit and push successful work, record the outcome, then re-rank from fresh telemetry

Commit behavior:
- Ralph keeps commit/push responsibility in the loop layer, not inside the Codex worker prompt
- a successful `applied` run now stages only the files created by that run, commits them, and pushes the current branch to `origin`
- if the worktree is already dirty, Ralph still runs and reports the pre-existing dirty paths
- if a run touches files that were already dirty before the run, Ralph reports the result but skips commit/push for that pass rather than mixing autonomous work with existing local edits

Target selection behavior:
- Ralph still ranks targets from live telemetry first
- some targets can be permanently excluded from execute mode when the owner explicitly accepts that they are upstream-dominated and not worth further autonomous work
- the live execution-skip rule currently applies to `codex_exec_latency`
- Ralph still reports the raw latency problem in telemetry through `raw_top_candidate_id`, but it will not select that target for autonomous fixes

Telegram reporting:
- each hourly execute run sends a short status update to the configured chat/topic
- the daily report is a `.md` document covering the last 24 hours of Ralph results, findings, applied fixes, commits, and attention items
- live daily delivery is centralized through `staker_alerts_bot` to chat `211761499`
