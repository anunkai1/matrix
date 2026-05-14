# Server3 Dream Loop

Status: proposed

## Document Role

This file is the planning and operator document for the Server3 nightly truth-alignment loop.

It explains:

- what problem the loop solves
- what counts as truth
- what the loop scans each night
- how the loop decides when something is out of alignment
- what it updates
- what it does not update
- how it fits the current bridge, session, and runtime workflows
- how stale-session warnings and `/refresh` fit into the design

## Purpose

The goal is to keep Architect aligned to reality without forcing expensive checks on every reply.

The design is:

- use current code and live runtime state as the primary truth
- use one nightly alignment pass to refresh stable truth across days and sessions
- warn users when truth changed in a way that may leave old carried context stale
- keep daytime replies fast by using the nightly truth baseline unless a task depends on fresh live state

This is a truth-maintenance system, not a new assistant runtime.

## The Problem

Architect can carry context across time through:

- current conversation state
- persistent bridge sessions
- canonical session state
- human-written summary and policy files

Those are useful, but they can drift away from reality.

Examples of drift:

- a doc says a capability exists, but the code no longer supports it
- a summary says a runtime works one way, but the live config changed
- a long-lived session still carries older beliefs after files changed
- an operator statement in conversation is wrong, but it sounds confident

The system needs a repeatable way to pull declared truth back toward actual truth.

## Core Principle

Conversation is input.

Truth comes from:

1. current code
2. current live runtime state
3. direct system signals such as status, logs, tests, and failures
4. verified changes made during the current working flow
5. saved summary truth
6. older memory and older conversation

A statement is not true because it was just said.

It is true when the system shows it is true.

## What The Dream Loop Is

The dream loop is a nightly alignment pass that:

1. inspects the real system
2. compares declared truth against observed truth
3. classifies each mismatch
4. updates the correct truth layer
5. records a clean daily baseline for the next day

It is not meant to solve every live operational problem at night.

Its job is alignment, not open-ended automation.

## Goals

- Keep Architect aligned to the current system across days and sessions.
- Reduce stale beliefs in persistent bridge sessions.
- Make stale-context risk visible to users instead of silently clearing sessions.
- Keep stable docs consistent with stable reality.
- Keep temporary live health issues separate from permanent docs.
- Avoid unnecessary live checks during normal daytime replies.
- Make drift visible and auditable.

## Non-Goals

- Do not rewrite the whole repo each night.
- Do not auto-edit every doc file.
- Do not treat temporary failures as permanent truth.
- Do not auto-add lessons without a real validated lesson.
- Do not force live verification before every normal reply.
- Do not replace operator judgment for destructive changes.

## Truth Layers

The loop must keep these layers separate.

### 1. Structural Truth

This is what the system is built to be.

Examples:

- code paths
- runtime manifest
- service definitions
- capability docs
- stable summary docs

Structural truth changes when the system is intentionally changed.

### 2. Operational Truth

This is what the system is doing right now or has been doing recently.

Examples:

- service up or down
- recent request failures
- Telegram retry spikes
- recent restart bursts
- temporary degraded health

Operational truth is often temporary and should not automatically rewrite stable docs.

### 3. Session Truth

This is what the active working flow has just verified.

Examples:

- code changed during the current session
- a service restarted successfully
- a file was just updated and confirmed

Session truth can outrank the nightly baseline, but only when it is real and verified.

### 4. Conversation Claims

These are statements made in chat.

They are useful input, but they are not truth by themselves.

If a claim conflicts with code or runtime state, the code or runtime state wins.

## Current System Fit

The dream loop should fit the current Server3 architecture, not replace it.

Current relevant pieces:

- `ARCHITECT_INSTRUCTION.md`
  - authoritative local operating rules
- `SERVER3_SUMMARY.md`
  - compact human summary of current stable truth
- `LESSONS.md`
  - mistake-prevention log
- `infra/server3-runtime-manifest.json`
  - canonical runtime inventory
- `ops/server3_runtime_status.py`
  - live runtime and service status inspection
- `ops/runtime_observer/runtime_observer.py`
  - background health snapshot and daily summary collector
- `src/telegram_bridge/session_manager.py`
  - existing watched-file session handling that can be adapted for stale-context warnings
- `src/telegram_bridge/bridge_runtime_setup.py`
  - startup-time watched-file state handling that can be adapted for stale-context warnings

The dream loop should consume those systems, not duplicate them.

## What The Dream Loop Scans

The nightly pass should scan a small set of high-value truth sources.

### A. Local Truth Rules

- `ARCHITECT_INSTRUCTION.md`
- `SERVER3_SUMMARY.md`
- `LESSONS.md`
- `private/SOUL.md`

Purpose:

- know the current declared rules
- know the current summary claims
- know the current collaboration guidance

### B. Runtime Shape

- `infra/server3-runtime-manifest.json`
- `python3 ops/server3_runtime_status.py --json`

Purpose:

- know what runtimes should exist
- know what units are expected
- know what is actually active now

### C. Operational Health

- `python3 ops/runtime_observer/runtime_observer.py status --json`
- `python3 ops/runtime_observer/runtime_observer.py summary --hours 24 --json`
- current observer snapshots from the state directory

Purpose:

- know whether the system has been healthy
- know whether there is fresh evidence of drift, failure, or instability

### D. Repo State

- current branch
- dirty tracked files
- selected file existence checks
- selected config/path checks where capabilities depend on them

Purpose:

- know whether local reality differs from docs
- know whether there are uncommitted changes that already altered truth

### E. Session Risk

- current watched truth files
- current truth fingerprint
- whether long-lived sessions may still carry pre-alignment beliefs

Purpose:

- know whether stale-context warning delivery is needed after truth files change

## What The Dream Loop Does Not Need To Scan

- the whole repo every night
- every log file on the machine
- every old archive document
- every chat history file
- every Telegram message

The loop should stay focused on the files and commands that define stable truth and current health.

## Alignment Logic

For each mismatch, the loop must answer four questions.

1. Is this mismatch real?
2. Is it structural or temporary?
3. Which truth layer is supposed to hold this fact?
4. Does the mismatch require stale-context warning delivery?

### If The Mismatch Is Structural

Examples:

- summary doc says a runtime works one way, but code or manifest says otherwise
- capability docs name the wrong current behavior
- a summary file is stale after a deliberate code/config change

Action:

- update the stable truth doc or summary file
- record what changed and why
- mark that stale-context warnings may need to be sent to active chats

### If The Mismatch Is Operational

Examples:

- service is down
- retry rate spiked
- requests failed in the last 24 hours

Action:

- write it into the nightly state report
- do not rewrite permanent summary docs just because of a temporary health issue

### If The Mismatch Is Only A Conversation Claim

Examples:

- a user says the system works one way
- prior chat text claims a capability that the code does not support

Action:

- do not promote the claim into truth
- leave stable docs unchanged
- rely on code/runtime truth

## Stale Session Handling

The system should not silently discard session context when truth files change.

Instead, it should:

1. detect that watched truth files changed
2. detect that active chats may still be carrying older session context
3. send a clear warning message to those chats
4. let the user decide whether to drop the old context

This keeps the system transparent.

The user-facing command for dropping stale carried context should be:

- `/refresh`

The meaning of `/refresh` in this design is:

- clear the carried session context for this chat or scope
- keep the runtime alive
- start the next request from the current truth baseline instead of the older carried context

This is narrower than a broad global reset.

## How Alignment Is Achieved

The loop achieves alignment in five steps.

### 1. Observe

Collect the current observed truth from code, manifest, status commands, and health snapshots.

### 2. Compare

Compare observed truth against declared truth in the summary and policy files.

### 3. Classify

Decide whether each mismatch is:

- structural drift
- temporary operational issue
- stale summary
- stale session risk
- noise that should be ignored

### 4. Correct

Update the right layer:

- structural drift -> stable summary docs
- temporary operational issue -> nightly state report
- stale session risk -> truth fingerprint change and stale-context warning eligibility

### 5. Persist

Write the results in machine-readable and human-readable form.

## Outputs

The loop should write three main outputs.

### 1. Latest State

Suggested path:

- `/var/lib/server3-dream-loop/latest_state.json`

Purpose:

- machine-readable nightly baseline
- input for future automation or status commands

Suggested contents:

- observed timestamp
- timezone
- truth sources scanned
- runtime status summary
- observer summary
- structural mismatches found
- operational issues found
- files updated
- whether stale-context warnings are required
- which chats or scopes were notified

### 2. Read-Only Truth Status

User-facing command:

- `/truth_status`

Purpose:

- let a user inspect the current truth-alignment state for the current chat or scope

The output should stay compact and operator-readable.

Suggested fields:

- last dream-loop run time
- whether the last run succeeded or failed
- whether truth changed on the last run
- which watched truth files changed
- whether this current chat or topic has a stale-context warning outstanding
- whether `/refresh` has already been used in this chat or topic since the last truth change
- short summary of what was aligned
- unresolved items that were skipped because they needed human judgment
- one short global system line

### 3. Latest Report

Suggested path:

- `/var/lib/server3-dream-loop/latest_report.md`

Purpose:

- human-readable nightly report

Suggested contents:

- last run time
- success or failure
- whether truth changed
- files changed
- commit SHA if a push succeeded
- warning count
- unresolved items
- what still needs human attention

### 4. History

Suggested path:

- `/var/lib/server3-dream-loop/history.jsonl`

Purpose:

- durable per-run audit trail

## Which Files Should Be Updated

The dream loop should be conservative.

Files that can reasonably be updated by the loop:

- `SERVER3_SUMMARY.md`
- one dedicated generated or semi-generated truth file if added later
- dream-loop state/report files

Files that should usually not be updated automatically:

- `ARCHITECT_INSTRUCTION.md`
- `AGENTS.md`
- broad runbooks
- archive history docs

`LESSONS.md` should only be updated when a real new validated lesson exists, not as part of normal nightly drift cleanup.

## Watched Truth Files

These files define the currently watched truth set for stale-context warning purposes.

Initial watched truth files:

- `ARCHITECT_INSTRUCTION.md`
- `SERVER3_SUMMARY.md`
- `LESSONS.md`

When one or more watched truth files change in a way that changes the truth fingerprint:

- the system should consider long-lived carried context potentially stale
- the system should notify affected chats
- the user can choose to run `/refresh`

The watched truth set can be expanded later when more memory layers exist.

## Session Notification

Updating truth files is not enough if persistent sessions still carry old beliefs.

But the design should not silently wipe those sessions.

So the dream loop must be tied into a notification path.

That means:

- truth-defining files are watched
- a nightly truth update changes the truth fingerprint
- affected chats are notified that their carried context may now be stale
- the notification tells them to use `/refresh` if they want a fresh session aligned to the new truth

This is how corrected truth reaches the live assistant behavior without hidden session loss.

### Warning Scope

The notification should not go to every possible chat.

It should go to:

- scopes with active persisted sessions
- scopes with recent activity

Recent activity window for the initial design:

- last 7 days

Initial rollout scope:

- Architect first

### Warning Frequency

Do not keep repeating the same warning unnecessarily.

Initial behavior:

- one warning per truth change per scope
- suppress repeated warnings until either:
  - the user runs `/refresh`
  - a later truth change creates a new warning condition

Warning delivery rule:

- send stale-context warnings only after truth updates and push both succeeded

### Warning Message

The warning should be short and explicit.

It should include:

- that truth files changed
- that carried session context may now be stale
- the changed watched truth files
- that the user can send `/refresh`

Suggested message shape:

`Truth files changed and this session may now carry stale context. Changed files: SERVER3_SUMMARY.md, LESSONS.md. Send /refresh if you want a fresh session aligned to the new truth.`

## Refresh Command

User-facing command:

- `/refresh`

Meaning:

- clear the carried assistant session context for the current chat or topic
- do not clear unrelated chats or topics
- do not clear broad runtime state
- do not clear model or engine overrides for the scope by default
- make the next request start from the current truth baseline instead of the older carried context

On success, the bridge should confirm clearly.

Suggested success message:

`Session context cleared for this topic. Next reply will start from current truth.`

## Daytime Behavior After Nightly Alignment

The dream loop is the baseline refresh, not the only source of truth.

During the day:

- if code or runtime state was just changed and verified, that fresh truth wins
- if a user makes an unverified claim, it does not become truth
- if the reply depends on fresh live state, do a small live check
- otherwise use the nightly baseline plus current verified session changes
- if a stale-context warning was sent, the user may choose `/refresh` before continuing

The dream loop reduces future drift.

It does not replace normal technical judgment.

## Suggested Implementation Shape

Suggested new files:

- `ops/dream_loop/dream_loop.py`
- `infra/systemd/server3-dream-loop.service`
- `infra/systemd/server3-dream-loop.timer`
- `docs/runbooks/server3-dream-loop.md`

Likely supporting changes:

- update watched truth files in `src/telegram_bridge/runtime_config.py`
- add a user-facing `/refresh` command in the bridge command layer
- add a user-facing `/truth_status` command in the bridge command layer
- add a manual “run now” command or entry point for the dream loop
- add stale-context notification delivery tied to watched truth-file changes
- document the truth hierarchy in `ARCHITECT_INSTRUCTION.md`
- add tests for watched-file warning behavior and dream-loop classification logic

### Execution Order

The dream loop should run in a fixed order.

Recommended order:

1. scan truth sources
2. compare observed truth against declared truth
3. classify mismatches
4. prepare edits
5. verify edits
6. write local state and report outputs
7. commit tracked allowed changes
8. push tracked allowed changes
9. send daily Telegram summary
10. send stale-context notices to affected chats

Stale-context notices must happen after push succeeds, not before.

### Nightly Schedule

Initial target schedule:

- around `02:15 AEST`

The timer should be placed so it does not fight with nearby nightly maintenance work if that becomes relevant later.

### Manual Run

There should be a manual way to run the dream loop immediately.

Purpose:

- test the loop without waiting for the nightly timer
- realign after major changes
- verify behavior during rollout

### Dry Run

There should be a dry-run mode.

Purpose:

- show what the dream loop would change
- show what it would report
- do not edit files
- do not commit
- do not push
- do not notify chats

### Dream Loop Edit Rights

The dream loop may directly edit `SERVER3_SUMMARY.md` wherever edits are needed to align the file to truth.

The intended rule is not section-based ownership.

The intended rule is:

- edit any section that must change to align the summary to current truth
- do not rewrite the file casually when no truth mismatch exists

### Commit And Push Behavior

The dream loop is allowed to commit and push its tracked doc changes automatically.

Initial intent:

- when the dream loop makes a tracked file change that it is allowed to make
- and the change verifies cleanly
- it may commit and push that change to the repo automatically

This is part of the initial design, not a later expansion.

If push fails:

- attempt push again once
- if push still fails, keep the local committed or edited change
- report the failure in the daily summary
- do not send stale-context notices yet

### Uncertain Mismatches

If the dream loop cannot classify a mismatch confidently, it should:

- skip the automatic correction
- record the unresolved item
- include it in the report and `/truth_status` output

## Safety Rules

The dream loop must:

- prefer small scoped updates
- never treat conversation text as truth by itself
- not rewrite permanent docs for temporary health issues
- not silently change broad policy docs
- not silently drop user session context when truth files change
- leave a durable record of every correction it makes

## Success Criteria

The dream loop is working if:

- stable docs stop drifting behind real code and runtime changes
- users are warned when persistent sessions may now carry stale truth
- `/refresh` gives users a clean way to realign a chat to the new truth baseline
- `/truth_status` lets a user inspect the current alignment state of the chat or topic
- dry-run and manual-run paths make rollout and debugging practical
- daytime replies need fewer broad re-checks
- temporary operational incidents are recorded without corrupting permanent docs
- operators can inspect one daily report and see what was aligned

## Source Of Truth

This file is the planning source for the Server3 dream-loop alignment design until implementation begins.
