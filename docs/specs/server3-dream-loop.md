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

## Purpose

The goal is to keep Architect aligned to reality without forcing expensive checks on every reply.

The design is:

- use current code and live runtime state as the primary truth
- use one nightly alignment pass to refresh stable truth across days and sessions
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
  - persistent worker session reset logic when watched files change
- `src/telegram_bridge/bridge_runtime_setup.py`
  - startup-time session reset logic when watched files changed before boot

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

- know whether session invalidation is needed after truth files change

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
4. Does the mismatch require session invalidation?

### If The Mismatch Is Structural

Examples:

- summary doc says a runtime works one way, but code or manifest says otherwise
- capability docs name the wrong current behavior
- a summary file is stale after a deliberate code/config change

Action:

- update the stable truth doc or summary file
- record what changed and why
- ensure watched truth state changes so stale sessions are reset

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
- stale session risk -> truth fingerprint change and next-request reset

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
- whether session invalidation is required

### 2. Latest Report

Suggested path:

- `/var/lib/server3-dream-loop/latest_report.md`

Purpose:

- human-readable nightly report

Suggested contents:

- what was scanned
- what matched
- what drifted
- what was updated
- what still needs human attention

### 3. History

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

## Session Invalidation

This is a key part of the design.

Updating truth files is not enough if persistent sessions still carry old beliefs.

The current bridge already knows how to reset long-lived worker state when watched files change.

So the dream loop must be tied into that behavior.

That means:

- truth-defining files must be included in the watched file set
- a nightly truth update must change the truth fingerprint
- the next request should clear stale worker session context when needed

This is how corrected truth reaches the live assistant behavior instead of sitting only in files.

## Daytime Behavior After Nightly Alignment

The dream loop is the baseline refresh, not the only source of truth.

During the day:

- if code or runtime state was just changed and verified, that fresh truth wins
- if a user makes an unverified claim, it does not become truth
- if the reply depends on fresh live state, do a small live check
- otherwise use the nightly baseline plus current verified session changes

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
- document the truth hierarchy in `ARCHITECT_INSTRUCTION.md`
- add tests for watched-file reset behavior and dream-loop classification logic

## Safety Rules

The dream loop must:

- prefer small scoped updates
- never treat conversation text as truth by itself
- not rewrite permanent docs for temporary health issues
- not silently change broad policy docs
- leave a durable record of every correction it makes

## Success Criteria

The dream loop is working if:

- stable docs stop drifting behind real code and runtime changes
- persistent sessions stop carrying stale truth across daily boundaries
- daytime replies need fewer broad re-checks
- temporary operational incidents are recorded without corrupting permanent docs
- operators can inspect one daily report and see what was aligned

## Open Questions

- Should `SERVER3_SUMMARY.md` be partially auto-managed, or should a new dedicated truth summary file be added?
- Which exact files belong in the watched truth set by default?
- Should the dream loop only update files, or also send one daily Telegram alignment summary?
- Should manual approval be required for some classes of structural doc changes?

## Source Of Truth

This file is the planning source for the Server3 dream-loop alignment design until implementation begins.
