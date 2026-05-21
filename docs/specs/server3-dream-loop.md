# Server3 Dream Loop

Status: proposed, partially implemented

## Implementation Status

This document currently describes two layers:

- the implemented bounded `v1` dream-loop runner
- the broader `v2+` truth-alignment system that is not yet fully built

Current reality:

- `v1` exists in `ops/dream_loop/dream_loop.py`
- `v1` is the authoritative implementation target for the current runner
- the broader system-wide truth-alignment behaviors in this document are follow-on scope and should not be used to judge `v1` completeness

Reading rule:

- treat `V1 Contract`, `Machine State Split`, and `V1 Scope` as the current implementation contract
- treat the broader alignment design outside those sections as the intended `v2+` direction unless a section explicitly says otherwise

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
- how stale-session warnings and `/reset` fit into the design

## Overall Purpose

The goal is to make actual system truth and maintained structured truth state converge, with actual system truth as the target and human-readable explanation only as a secondary rendered effect.

The desired end state is explicit: actual system truth should align with maintained structured truth state, and explainer files should derive from that state instead of competing with it.

The core maintenance target is `actual system truth <-> structured truth state`.

The design is:

- use current code and live runtime state as the upstream truth inputs
- normalize those inputs into structured machine-readable truth state first
- use one nightly alignment pass to refresh that structured truth baseline across days and sessions
- warn users when truth changed in a way that may leave old carried context stale
- keep human summary files as a secondary rendered explanation layer refreshed from structured truth state
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

The system needs a repeatable way to pull recorded state back toward actual truth, with structured truth state updated first and human-readable explanation rendered from that state.

## Core Principle

Conversation is input.

Truth comes from:

1. current code
2. current live runtime state
3. direct system signals such as status, logs, tests, and failures
4. verified changes made during the current working flow
5. saved structured truth state
6. older memory and older conversation

A statement is not true because it was just said.

It is true when the system shows it is true.

## Primary And Secondary Truth

The dream-loop design should separate:

1. primary structured truth state
2. secondary human-readable explanation

### Primary Structured Truth State

This is the machine-readable primary maintained self-model of Server3.

It should contain exact facts such as:

- what runtimes exist
- what services are active
- what capabilities are configured
- which structured-truth inputs changed
- which scopes may now have stale carried context

This is the main alignment target, and it exists to keep actual system truth converging with maintained structured truth state over time.

The dream loop should primarily keep actual system truth converging with maintained structured truth state:

`actual system truth <-> structured truth state`

aligned.

### Secondary Human Summary Layer

This is the human-readable explanation of the structured truth.

Examples:

- `SERVER3_SUMMARY.md`
- dream-loop markdown reports
- short Telegram alignment summaries

These are important, but they are not the primary truth store.

They should be derived from or updated from the structured truth state, not treated as the deepest truth source.

The dream loop should secondarily keep:

`structured truth state <-> human summary layer`

aligned.

## Overall Dream-Loop Vision

The dream loop is a nightly alignment pass that:

1. inspects the real system
2. updates structured truth and health state from observed truth
3. compares secondary rendered summaries against structured truth
4. classifies each mismatch
5. updates the correct truth layer
6. records a clean daily baseline for the next day

It is not meant to solve every live operational problem at night.

Its job is alignment, not open-ended automation.

## Overall Goals

- Align actual system truth <-> structured truth state.
- Keep Architect aligned to the current system across days and sessions.
- Make structured truth state the main durable self-model for Server3.
- Reduce stale beliefs in persistent bridge sessions.
- Make stale-context risk visible to users instead of silently clearing sessions.
- Keep human-readable summary files consistent with structured truth and stable reality.
- Keep temporary live health issues separate from permanent docs.
- Avoid unnecessary live checks during normal daytime replies.
- Make drift visible and auditable.

## Overall Non-Goals

- Do not rewrite the whole repo each night.
- Do not auto-edit every doc file.
- Do not treat temporary failures as permanent truth.
- Do not auto-add lessons without a real validated lesson.
- Do not force live verification before every normal reply.
- Do not replace operator judgment for destructive changes.

## Truth Model

The loop must keep these layers separate.

### 1. Structural Truth

This is what the system is built to be.

Examples:

- code paths
- runtime manifest
- service definitions
- capability docs
- structured truth-state outputs
- rendered summary docs

Structural truth changes when the system is intentionally changed.

### 2. Operational Truth

This is what the system is doing right now or has been doing recently.

Examples:

- service up or down
- recent request failures
- Telegram retry spikes
- recent restart bursts
- temporary degraded health

Operational truth is often temporary and should not automatically rewrite rendered summary docs.

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

## Truth State Outputs

The dream loop should produce structured truth outputs first.

For the overall design, the output set may include:

- `/var/lib/server3-dream-loop/latest_truth_state.json`
- `/var/lib/server3-dream-loop/latest_health_state.json`
- `/var/lib/server3-dream-loop/latest_run_state.json`
- `/var/lib/server3-dream-loop/history.jsonl`

For the v1-required outputs, the contract is only:

- `/var/lib/server3-dream-loop/latest_truth_state.json`
- `/var/lib/server3-dream-loop/latest_health_state.json`
- `/var/lib/server3-dream-loop/latest_run_state.json`

Suggested secondary outputs:

- `/var/lib/server3-dream-loop/latest_report.md`
- `SERVER3_SUMMARY.md`
- Telegram alignment summaries

### V1 Contract

V1 keeps three machine-output artifacts separate:

- `latest_truth_state.json`: machine truth and stale-context eligibility
- `latest_health_state.json`: operational health and degradation state
- `latest_run_state.json`: execution bookkeeping

The V1 source-and-command classification is explicit and single-purpose:

| Source or command | Role |
| --- | --- |
| `ARCHITECT_INSTRUCTION.md` | machine-truth fingerprint input |
| `LESSONS.md` | machine-truth fingerprint input |
| `infra/server3-runtime-manifest.json` | machine-truth fingerprint input |
| `python3 ops/server3_runtime_status.py --json` | machine-truth fingerprint input |
| `python3 ops/runtime_observer/runtime_observer.py status --json` | health input |
| `python3 ops/runtime_observer/runtime_observer.py summary --hours 24 --json` | health input |
| `src/telegram_bridge/runtime_config.py` | policy-derived stale-context eligibility input |
| `src/telegram_bridge/session_manager.py` | policy-derived stale-context eligibility input |
| `src/telegram_bridge/bridge_runtime_setup.py` | policy-derived stale-context eligibility input |
| `latest_truth_state.json` | primary truth output |
| `latest_health_state.json` | primary health output |
| `latest_run_state.json` | execution bookkeeping |
| `latest_report.md` | report-only output |
| `SERVER3_SUMMARY.md` | report-only output |
| Telegram alignment summaries | report-only output |

V1 contract rules:

1. The machine-truth fingerprint must be derived from structured truth inputs only.
2. Machine-truth fingerprint inputs come from watched structured-truth inputs and verified runtime truth inputs. They exclude secondary explainer files, reports, notification history, and all report-only outputs.
3. Policy-derived stale-context eligibility is tracked as a separate structured-truth field in truth state. Its inputs are the policy-only sources in the table, and it may change even if the machine-truth fingerprint does not.
4. V1 emits stale-context warning eligibility only. It does not perform actual chat notification delivery in the v1 runner.
5. `latest_truth_state.json` must include, at minimum, `generated_at`, `machine_truth_fingerprint`, `watched_inputs`, and `stale_context_eligibility`.
6. `latest_health_state.json` must include, at minimum, `generated_at`, `health_status`, and `health_findings`.
7. `latest_run_state.json` must include, at minimum, `generated_at`, `run_status`, and `artifacts_written`.

This means v1 can determine that a chat or scope is stale-context eligible, but any actual delivery to users is a later-phase bridge feature and is out of scope for `latest_run_state.json`.

Meaning:

- `latest_truth_state.json` and `latest_health_state.json` are the primary maintained machine outputs for v1
- `latest_run_state.json` is execution bookkeeping for the bounded runner
- history is optional for the first slice
- markdown and summary files are secondary explanation artifacts

## Machine State Split

V1 should keep three machine-facing records separate and non-overlapping.

### 1. Truth State

Truth state is what the system is.

It is the structured machine self-model and should only contain stable or intentionally updated facts about the Server3 system.

Examples:

- declared runtime inventory
- capability facts
- watched structured-truth-input fingerprints
- stale-context risk markers that reflect current truth conditions
- policy-derived stale-context eligibility in truth state

Truth state should not store transient pain, incident detail, or per-run bookkeeping.
It is the answer to `what is the system?`.

### 2. Health State

Health state is the current pain or recent operational condition.

It should capture whether the system is healthy, degraded, unstable, or recently failed.

Examples:

- recent service failures
- retry spikes
- degraded observer signals
- temporary operational warnings
- runtime status command output used for health validation

Health state should not carry delivery records, notification history, or other run bookkeeping.
Health state should not become the canonical record of what the system is or replace truth state.
It is the answer to `how is the system doing?`.

### 3. Run State

Run state is what the loop did.

It records the execution metadata for a specific nightly pass so operators can audit the run itself.

Examples:

- run start and end timestamps
- exit status
- checks executed
- files updated
- warnings emitted

Run state should not be treated as machine truth or health truth. It is bookkeeping about the alignment pass.
It is the answer to `what did the loop do?`.

Run state should stay limited to execution metadata, checks, artifacts written, and unresolved items. It should not describe which chats or scopes were affected by later-phase notification handling, whether any user-facing notice was sent, or any other notification outcome.

The key boundary is:

- truth state answers `what is the system?`
- health state answers `how is the system doing?`
- run state answers `what did the loop do?`

The split is intentionally strict:

- truth state owns stable machine facts and durable self-model data
- health state owns pain, degradation, and recent operational condition
- run state owns loop execution metadata, audit trail data, and pass-specific bookkeeping
- none of the three should be used as a substitute for the others

## V1 Scope

The first implementation slice should stay tightly bounded.

V1 is only about a bounded runner, in this execution order:

1. dry-run mode that scans, normalizes, classifies, and emits truth, health, and report outputs without side effects
2. manual run that executes the same bounded runner on demand for rollout and debugging
3. later automation that schedules the bounded runner nightly once the dry-run and manual run paths are stable

V1 is only about:

- producing and maintaining `latest_truth_state.json`
- producing and maintaining `latest_health_state.json`
- producing and maintaining run metadata for each loop pass
- producing a conservative `latest_report.md` as a rendered explanation of those machine-readable states
- keeping the scope centered on machine truth first, with human-readable output strictly secondary

V1 is not the full dream-loop system.

It should not expand into:

- broad repo-wide cleanup
- automatic maintenance of every document in the repository
- automatic summary rewrites except where needed to render the report layer
- commits or pushes as a required part of v1
- open-ended nightly automation outside the bounded truth and health outputs
- open-ended nightly automation beyond the declared truth and health outputs
- generalized refactoring of session, bridge, or runtime systems

Any later behavior that touches stale-session delivery, `/reset`, `/truth_status`, commit/push automation, or wider summary maintenance should be treated as follow-on scope unless it is strictly needed to support the three v1 artifacts above.

## V2+ Follow-On Scope

The sections below this point describe the intended follow-on system beyond the bounded `v1` runner.

These items are not required for `v1` completeness.

The main `v2+` areas are:

- broader truth scanning beyond the fixed `v1` input set
- a declared dream-loop check registry as a first-class implementation object
- wider rendered-doc and capability-truth reconciliation
- stale-context warning delivery to affected chats or scopes
- read-only user-facing truth inspection such as `/truth_status`
- user-driven stale-context reset flow such as `/reset`
- optional history output such as `history.jsonl`
- optional Telegram alignment summaries
- later automation such as commit/push only if explicitly approved and still aligned with the truth-layer boundaries

Implementation rule:

- if a requirement depends on these `v2+` behaviors, it must be specified and implemented as follow-on work rather than treated as an already-missing part of `v1`

## V2 Implementation Target

`V2` is the next implementation phase after the bounded `v1` runner.

Its purpose is to make the dream loop a real declared truth-alignment system, not just a bounded nightly snapshotter.

`V2` should stay strict and affordable. It should add the minimum new machinery required to make the broader design operational without turning the loop into an uncontrolled repo scanner or an autonomous doc-rewriter.

### V2 Must Deliver

- a declared check registry stored as code or structured data, rather than hard-coded check selection only in the runner
- a `v2` scan planner that executes fixed checks and declared conditional checks from that registry
- broader secondary-doc alignment for explicitly approved truth surfaces, starting with `SERVER3_SUMMARY.md`
- persisted stale-context warning state for eligible chats/scopes
- a read-only `/truth_status` view over dream-loop state
- a user-driven `/reset` flow that clears stale carried context for the current scope

### V2 Must Not Deliver

- open-ended scanning of the whole repo
- free-form capability inference without a declared check
- automatic rewriting of arbitrary docs outside approved correction targets
- commit/push automation
- proactive Telegram warning delivery to every eligible scope unless the delivery contract is explicitly implemented and tested

### V2 Artifact Changes

`V2` should keep the existing `v1` artifacts and extend them conservatively.

Required `v2` additions:

- `latest_truth_state.json`
  - add registry-driven check results
  - add claim-evaluation results such as `claim_results`, `claim_summary`, and `stale_claims`
  - add explicit rendered-doc alignment facts for approved secondary docs
  - add stale-context warning state for eligible scopes
- `latest_health_state.json`
  - keep health truth separate from structural truth
  - add any new health checks only through the registry
- `latest_run_state.json`
  - add executed registry checks, skipped registry checks, and reasons
  - add the active claim-verification mode such as `audit_only` or `corrective`
  - add any `/truth_status` or `/reset`-related maintenance bookkeeping only if it is run-level rather than truth-level

Optional `v2` additions:

- `history.jsonl`
  - append-only per-run summary for drift history and later operator inspection

### V2 Registry Minimum Shape

`V2` should make the registry a first-class implementation object with, at minimum:

- `check_id`
- `truth_area`
- `mode`
- `trigger`
- `inputs`
- `executor`
- `mismatch_rule`
- `correction_target`
- `severity`

Additional `v2` rule:

- every correction target must name whether it writes to truth state, health state, run state, or an approved secondary rendered document

### V2 Minimum Check Set

`V2` should promote the current implemented checks into the declared registry and add only the smallest missing checks needed for broader alignment.

Required fixed checks:

- `truth_files_fingerprint`
- `runtime_manifest_vs_status`
- `runtime_observer_truth`

Required conditional checks:

- `policy_watch_truth`
- `telegram_context_routing_truth`
- `server3_summary_truth`
  - purpose: evaluate approved `SERVER3_SUMMARY.md` claims against structured truth and live inputs that are already in dream-loop scope
  - correction target: claim results in truth/report state first, then `SERVER3_SUMMARY.md` only for explicitly approved claim-backed correction targets

The `server3_summary_truth` check is the key `v2` step that turns summary maintenance from ad hoc rendering into declared truth alignment.

The current narrow field-mapping approach is transitional only.

It exists to keep the already-implemented bounded runner conservative until claim verification replaces it.

`V2` should treat line-level or field-level summary mapping as legacy compatibility behavior, not as the long-term alignment model.

### V2 Approved Secondary Truth Surface

`V2` should approve exactly one broader rendered-doc target first:

- `SERVER3_SUMMARY.md`

For `v2`, approval of `SERVER3_SUMMARY.md` means:

- specific summary claims are explicitly declared and tied to bounded evidence
- each approved claim has one declared correction path
- unmapped prose remains operator-owned and must not be rewritten by the loop

Initial `v2` correction targets should stay narrow:

- dream-loop timer/status line
- runtime observer mode/schedule line
- other summary lines only when they already have a declared upstream truth source, a stable claim definition, and a stable correction rule

During the migration from field mapping to claim verification:

- already-implemented mapped summary fields may remain in place temporarily
- no new summary maintenance should be added as free-standing field mapping when a claim-backed verifier can be declared instead
- once a summary area is claim-backed, the claim becomes the unit of verification and correction rather than the raw line text

### V2 Claim Verification Model

`V2` should move broader doc alignment from line-based summary maintenance to bounded claim verification.

The dream loop should treat selected startup-loaded docs and approved explainer docs as claim surfaces, not as free-form prose that must be semantically reinterpreted from scratch on every run.

The preferred model is:

1. declare concrete operational or capability claims
2. attach each claim to bounded evidence
3. evaluate each claim against code, config, commands, or live runtime state
4. record the result in structured truth/report state
5. allow correction only for explicitly approved claim-backed targets

The claim-verification model exists because broad prose drift is too open-ended, while the current hard-coded field mapping is too narrow.

#### Claim Surfaces

Initial claim surfaces should be:

- `ARCHITECT_INSTRUCTION.md`
- `SERVER3_SUMMARY.md`

Later surfaces may include:

- `LESSONS.md`, but only for concrete validated operational lessons that the loop is explicitly meant to enforce
- `private/SOUL.md`, but only when it contains concrete operational constraints rather than collaboration tone

`remember.md` and other private or informal notes should not be included by default unless they are explicitly promoted into approved claim surfaces.

#### Claim Eligibility

Not every sentence in an approved doc is a claim.

A statement should only become a dream-loop claim when all of the following are true:

- it describes runtime behavior, capability, policy, config, workflow, or another operational fact
- it can be reduced to bounded observable evidence
- it can be evaluated without open-ended repo interpretation
- it matters enough that truth drift should be tracked

These are valid examples:

- restart behavior
- follow-up steering behavior
- worker/session persistence behavior
- timer schedule behavior
- declared runtime capability behavior

These are not valid examples:

- personality or tone statements
- vague aspirations
- broad prose that cannot be tied to observable evidence

#### Claim Registry

The dream loop should keep a separate executable claim registry.

That registry should be read at runtime.

The dream-loop design spec should define how claim verification works, but the spec itself should not need to be parsed every run.

Each claim entry should define at minimum:

- `claim_id`
- `source_doc`
- `source_anchor`
- `claim_text`
- `claim_kind`
- `verifier`
- `evidence_inputs`
- `correction_target`
- `severity`

The registry should be the runtime source of truth for which claims are evaluated.

Approved claim-surface docs do not, by themselves, force every sentence in those docs to be read as a runtime claim.

Only claims explicitly declared in the claim registry should be evaluated by the loop.

The claim registry is not the same thing as the dream-loop check registry.

Their responsibilities should stay separate:

- the check registry defines which bounded scan/evaluation routines the dream loop can run
- the claim registry defines which approved human-authored claims are evaluated by those routines or by claim-specific verifiers

In practice:

- the check registry controls execution flow
- the claim registry controls claim coverage

The initial claim-registry implementation should stay separate from prose docs and from the large design spec.

#### Verifier Types

Initial verifier types should stay bounded and mechanical.

Examples:

- file-marker or code-anchor verifier
- config/env value verifier
- systemd unit or timer verifier
- runtime command output verifier
- structured JSON/state-field verifier

If a claim cannot be checked through a bounded verifier, it should not be in the first-wave claim set.

#### Claim Statuses

Each evaluated claim should resolve to one of:

- `verified`
- `stale`
- `ambiguous`
- `unverifiable`

Meaning:

- `verified`
  - bounded evidence matches the declared claim
- `stale`
  - bounded evidence contradicts the declared claim
- `ambiguous`
  - the claim or evidence boundary is not precise enough to decide safely
- `unverifiable`
  - the current loop has no acceptable verifier path for the claim

`ambiguous` and `unverifiable` claims should not trigger automatic doc edits.

They should be surfaced for operator review and claim-registry cleanup.

#### Claim Correction Rule

The first correction target for claim evaluation should be structured truth/report state, not prose rewrites.

That means:

- first detect and persist claim drift
- then review claim quality and verifier quality
- only later enable narrow claim-backed doc correction for explicitly approved surfaces

This keeps the first rollout focused on trustworthy detection rather than premature auto-editing.

#### Claim Result Persistence

Claim evaluation results should be written into structured truth state first.

Suggested truth-state additions:

- `claim_results`
- `claim_summary`
- `stale_claims`

Suggested meanings:

- `claim_results`
  - per-claim status and supporting evidence summary
- `claim_summary`
  - compact counts such as verified, stale, ambiguous, and unverifiable
- `stale_claims`
  - compact list of claim IDs or source anchors currently in stale status

The rendered report should summarize claim drift from those truth-state fields rather than becoming the primary record of claim evaluation.

### V2 Claim Verification Rollout Phases

Claim verification should roll out in phases.

#### Phase 1: Audit-Only

Required behavior:

- load the claim registry
- evaluate approved claims
- record claim results in truth state and the rendered report
- do not edit source docs because of claim drift
- do not auto-correct `SERVER3_SUMMARY.md` except for the already-approved transitional narrow mappings, if they remain enabled during migration

Purpose:

- tune claims and verifiers
- measure noise
- identify stale, ambiguous, and weak claims safely before correction is enabled

#### Phase 2: Approved Correction Targets

Required behavior:

- keep claim evaluation running
- allow auto-correction only for explicitly approved claim-backed targets
- start with `SERVER3_SUMMARY.md`
- keep unmapped prose operator-owned

The unit of correction in this phase should be the approved claim, not arbitrary paragraph rewriting.

#### Runtime Mode

The implementation should expose an explicit claim-verification mode so rollout state is visible both in code and in run outputs.

Suggested values:

- `audit_only`
- `corrective`

Suggested behavior:

- `audit_only`
  - evaluate and persist claim results
  - do not perform claim-triggered doc correction
- `corrective`
  - evaluate and persist claim results
  - allow claim-triggered correction only for explicitly approved correction targets

The current mode should be recorded in run state.

#### Phase 3: Expanded Claim Coverage

Only after audit-mode claim quality is stable:

- add more claim surfaces
- add more verifier types
- widen the approved claim set

#### Audit Exit Criteria

The loop should not leave audit-only mode until all of the following are true:

- first-wave claims have produced stable low-noise results across multiple runs
- ambiguous and unverifiable claims have been reduced to an acceptable level
- approved correction targets are explicitly named
- tests cover the enabled verifier types and claim-status classification

### V2 Stale-Context Contract

`V2` should persist stale-context status per scope, but should keep delivery conservative.

Required `v2` behaviors:

- mark eligible scopes when watched truth or policy inputs changed
- persist whether a stale-context warning is outstanding for each eligible scope
- persist whether `/reset` has cleared that stale warning for the scope

`V2` may expose this status through `/truth_status` before any proactive notification delivery is enabled.

### V2 User-Facing Bridge Additions

`V2` should add two bridge-facing behaviors only:

- `/truth_status`
  - read-only view over current dream-loop truth/run state for the current scope
- `/reset`
  - clear the current scope's stale carried context and mark the outstanding stale warning as handled

`V2` should not add any broader conversational command set than this.

### V2 Exit Criteria

`V2` is complete when all of the following are true:

- the check registry exists and drives check selection
- the runner no longer relies only on hard-coded check orchestration
- `SERVER3_SUMMARY.md` alignment is registry-backed for approved claim-backed correction targets
- stale-context warning state is persisted per scope
- `/truth_status` works as a read-only scope-aware view
- `/reset` works as a scope-aware stale-context reset
- tests cover registry execution, claim evaluation, stale-context state transitions, and the bridge-facing `v2` commands

## Post-V2 Scope

Anything beyond the `V2` exit criteria should be treated as later scope, not silently absorbed into `v2`.

Examples:

- proactive Telegram stale-context warning delivery
- Telegram alignment summaries
- broader approved secondary docs beyond `SERVER3_SUMMARY.md`
- additional capability-specific checks that need new truth surfaces
- `history.jsonl` if it is not needed for the first `v2` rollout
- commit/push or any other outbound automation

## V2.1 Implementation Target

`V2.1` is the first bounded outbound automation slice after `v2`.

Its purpose is to let the dream loop commit and push safe repo-managed changes that it made itself, without turning the loop into a general git janitor that sweeps up unrelated operator work.

`V2.1` must stay conservative.

### V2.1 Must Deliver

- automatic git commit behavior for safe repo-managed files changed by the current dream-loop run
- automatic git push behavior immediately after a successful dream-loop auto-commit
- explicit run-state reporting of:
  - which repo-managed files were considered for commit
  - which files were skipped because they were already dirty before the run
  - whether a commit was created
  - commit SHA if created
  - whether push succeeded
  - push/commit failure details when relevant
- report-layer visibility of git automation outcome

### V2.1 Must Not Deliver

- committing unrelated pre-existing dirty files
- committing unrelated pre-existing staged files
- broad `git add .` or repo-wide staging
- automatic conflict resolution, rebases, pulls, or force-push behavior
- commit/push behavior in dry-run mode

### V2.1 Commit Boundary

`V2.1` may only auto-stage files that are both:

- inside the `matrix` git repo
- in the dream loop's approved managed-output set for the current run

The initial `v2.1` managed-output set is:

- approved secondary-doc correction targets changed by the loop
- structured truth/health artifacts written under the repo root, if that deployment path is used

Initial `v2.1` explicit exclusions:

- `latest_run_state.json`
- `latest_report.md`

Reason:

- those files must report the git automation result for the current run, so treating them as part of the same commit would create a self-referential write cycle

### V2.1 Safety Rules

Before auto-commit, the loop must detect:

- pre-existing staged changes anywhere in the repo
- pre-existing dirty state for candidate managed files

Required behavior:

- if unrelated pre-existing staged changes exist, skip auto-commit and record that skip in run state
- if a candidate managed file was already dirty before the run, do not auto-commit that file
- if safe current-run repo-managed changes remain after those filters, stage only those files and commit only those files
- if no safe repo-managed changes remain, skip commit/push and report why

### V2.1 Push Rule

After a successful auto-commit, the loop should push conservatively:

- prefer `origin HEAD` when `origin` exists
- otherwise use the repo's default `git push` behavior

If push fails:

- the run should still keep its truth/health outputs
- the failure must be recorded in run state and the report

### V2.1 Artifact Changes

`V2.1` extends `latest_run_state.json` with a git automation block.

Required `v2.1` run-state fields:

- candidate repo-managed files
- skipped dirty files
- skip reason when commit/push was not attempted
- commit attempted boolean
- commit message when attempted
- committed SHA when successful
- push attempted boolean
- push success boolean
- commit/push stdout/stderr snapshots as needed for debugging

### V2.1 Exit Criteria

`V2.1` is complete when all of the following are true:

- safe current-run repo-managed changes are auto-committed without sweeping up unrelated dirt
- a successful auto-commit triggers an automatic push
- dry-run mode never commits or pushes
- commit/push outcomes are visible in run state and the rendered report
- tests cover success, no-change skip, pre-existing-dirty skip, pre-existing-staged skip, and push failure behavior

## V2+ Truth Surfaces And Scan Expansion

Beyond the fixed `v1` inputs, later phases may expand the nightly pass to scan a broader but still declared set of high-value truth sources.

### A. Local Truth Rules

- `ARCHITECT_INSTRUCTION.md`
- `SERVER3_SUMMARY.md`
- `LESSONS.md`
- `private/SOUL.md`

Purpose:

- know the current declared rules
- know the current approved rule claims and summary claims that may need verification or rendering alignment
- know the current collaboration guidance
- contribute structured truth facts about current operating rules, validated lessons, and declared collaboration constraints

For the implemented `v1` runner, `ARCHITECT_INSTRUCTION.md` and `LESSONS.md` are watched only for the structured truth facts they encode, not for their explanatory prose. `ARCHITECT_INSTRUCTION.md` contributes current operating rules and declared truth boundaries. `LESSONS.md` contributes validated lessons that have become structured truth facts about what has already been verified. `SERVER3_SUMMARY.md` remains secondary rendered explanation output and does not contribute machine-truth fingerprint inputs by itself.

`SERVER3_SUMMARY.md` is a secondary rendered explainer. It may be scanned for claim-backed verification and approved correction, but it is not part of the machine-truth fingerprint input set.

Policy-derived stale-context eligibility inputs are separate from the machine-truth fingerprint inputs.
Those policy inputs are:

- `src/telegram_bridge/runtime_config.py`
- `src/telegram_bridge/session_manager.py`
- `src/telegram_bridge/bridge_runtime_setup.py`

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
- named targeted checks from the dream-loop check registry

Purpose:

- know whether local reality differs from structured truth or rendered explanation files
- know whether there are uncommitted changes that already altered truth

### E. Session Risk

- current watched structured-truth inputs
- current machine-truth fingerprint
- whether long-lived sessions may still carry pre-alignment beliefs

Purpose:

- know whether stale-context warning delivery is needed after structured truth inputs change

### F. Structured Truth State

- current dream-loop truth state files
- current dream-loop health state files

Purpose:

- know what the machine-readable self-model currently says
- compare that state against observed reality
- compare secondary summary outputs against the structured truth state

## V2+ Dream Loop Check Registry

To keep later-phase implementation unambiguous, the dream loop should not freely decide what files to inspect.

It should use a declared check registry.

The registry is the source that defines:

- what can be scanned
- why it can be scanned
- when it should be scanned
- what command or file proves the truth
- what counts as mismatch
- where correction goes

The registry should primarily describe how observed reality populates structured truth state.

It should secondarily describe how structured truth state renders or refreshes human-readable summary outputs.

Without this registry, “targeted scans” are too vague.

### Registry Shape

Each check entry should define:

- `check_id`
- `truth_area`
- `mode`
- `trigger`
- `inputs`
- `mismatch_rule`
- `correction_target`
- `severity`

Meaning:

- `check_id`
  - stable identifier for the check
- `truth_area`
  - what kind of truth is being validated
- `mode`
  - `always` or `conditional`
- `trigger`
  - when a conditional check should run
- `inputs`
  - files or commands used by the check
- `mismatch_rule`
  - what disagreement means the truth is not aligned
- `correction_target`
  - where the result should be written or corrected
- `severity`
  - how important the mismatch is

### Registry Logic

The dream loop should use two scan sets.

#### 1. Fixed Checks

These run every night.

Examples:

- watched structured-truth inputs
- runtime manifest
- runtime status
- runtime observer summary

#### 2. Named Conditional Checks

These run only when their trigger condition is true.

Examples:

- if the rendered summary claims a capability
- if a runtime is active in the manifest
- if yesterday's report flagged an area
- if the operator explicitly enabled a check
  - if a watched structured-truth input changed for that truth area

The loop should not improvise new scan targets outside the registry.

For `v1`, the implemented check set is still hard-coded in the runner.

For `v2+`, the registry should be narrow enough to support the primary machine truth and health outputs plus the conservative report layer without expanding into an uncontrolled repo-wide scan.

### Initial Checks For Affordable Alignment

V1 should start with a small registry of high-signal checks that move the structured truth state toward reality without turning the nightly pass into a broad repo scan.

Required initial checks:

- `truth_files_fingerprint`
  - purpose: detect whether watched structured-truth inputs changed and whether carried context may now be stale
  - inputs: `ARCHITECT_INSTRUCTION.md`, `LESSONS.md`, `infra/server3-runtime-manifest.json`
  - correction target: truth fingerprint and stale-context eligibility in structured truth state
- `runtime_manifest_vs_status`
  - purpose: compare declared runtime inventory with live runtime status
  - inputs: `infra/server3-runtime-manifest.json`, `python3 ops/server3_runtime_status.py --json`
  - correction target: runtime shape facts in structured truth state
- `runtime_observer_truth`
  - purpose: validate the observer snapshot and summary layer against current operational reality
  - inputs: `python3 ops/runtime_observer/runtime_observer.py status --json`, `python3 ops/runtime_observer/runtime_observer.py summary --hours 24 --json`
  - correction target: health state, plus only explicitly normalized structural observer facts in structured truth state
- `policy_watch_truth`
  - purpose: confirm watched structured-truth-input behavior remains aligned with the current policy
  - inputs: `src/telegram_bridge/runtime_config.py`, `src/telegram_bridge/session_manager.py`, `src/telegram_bridge/bridge_runtime_setup.py`
  - correction target: watched-file truth and the separate policy-derived stale-context eligibility field
- `telegram_context_routing_truth`
  - purpose: validate that Telegram context routing still matches the declared bridge behavior
  - inputs: `src/telegram_bridge/message_inputs.py`, `src/telegram_bridge/session_manager.py`
  - correction target: session-routing facts in structured truth state

These checks are the first concrete alignment slice because they cover the highest-signal boundaries between declared truth, live runtime status, observer truth, watched-file behavior, and context routing.

Anything beyond these checks should be added only when it is clearly justified by a new truth boundary, a recurring mismatch, or a direct dependency of the primary truth or health outputs.

## V2+ Runtime Shape Expansion

Runtime shape should be validated by a fixed, explicit set of checks.

Initial runtime shape sources:

- `infra/server3-runtime-manifest.json`
- `python3 ops/server3_runtime_status.py --json`
- matching `infra/systemd/*.service` and `*.timer` files for runtimes in scope

These answer:

- what runtimes should exist
- what units should exist
- what the system currently reports as active, inactive, or failed

### Runtime Shape Files In Scope

The initial runtime shape file set should include:

- `infra/server3-runtime-manifest.json`
- `ops/server3_runtime_status.py`
- `infra/systemd/telegram-architect-bridge.service`
- `infra/systemd/server3-runtime-observer.service`
- `infra/systemd/server3-runtime-observer.timer`

Additional systemd unit files may be checked when:

- the manifest includes them in the Architect scope
- the structured truth or rendered summary claims behavior that depends on them
- a named conditional check explicitly references them

### Targeted Capability Checks

Targeted capability checks should also come from the registry, but only when they map to a specific truth boundary that the nightly loop is responsible for maintaining.

Examples:

- `truth_files_fingerprint`
  - validates whether the watched structured-truth input set changed in a way that should trigger stale-context handling
  - input source: `ARCHITECT_INSTRUCTION.md`, `LESSONS.md`, `infra/server3-runtime-manifest.json`
- `runtime_manifest_vs_status`
  - validates that the declared runtime manifest matches the live runtime status shape
  - input source: `infra/server3-runtime-manifest.json`, `python3 ops/server3_runtime_status.py --json`
- `runtime_observer_truth`
  - validates observer truth against the current runtime state and health snapshots
  - input source: `python3 ops/runtime_observer/runtime_observer.py status --json`, `python3 ops/runtime_observer/runtime_observer.py summary --hours 24 --json`, current observer snapshots from the state directory
- `telegram_context_routing_truth`
  - validates current Telegram target-context behavior
  - input source: `src/telegram_bridge/message_inputs.py`
- `policy_watch_truth`
  - validates watched structured-truth-input behavior
  - input source: `src/telegram_bridge/runtime_config.py`
- `observer_summary_truth`
  - validates observer summary and alert behavior
  - input source: `ops/runtime_observer/runtime_observer.py`

These are not “free scans.”

They are predeclared named checks.

### Initial v1 Check Registry

For the first affordable slice, the registry should stay small, high-signal, and explicitly bounded to structured truth inputs, runtime shape, observer truth, watched-input policy, and Telegram context routing.

Initial fixed checks:

- `truth_files_fingerprint`
  - truth boundary: watched structured-truth inputs
  - watches the small truth-defining set and records when carried context may have gone stale
  - this is the cheapest high-signal way to detect truth drift without scanning the whole repo
- `runtime_manifest_vs_status`
  - truth boundary: declared runtime shape versus live runtime shape
  - compares the declared runtime manifest to the live runtime status output
  - this is the main structural truth check for declared runtime shape versus actual runtime shape
- `runtime_observer_truth`
  - truth boundary: observer truth versus current operational reality
  - compares observer status and summary snapshots against the live runtime and health picture
  - this is the main operational truth check for the nightly health baseline

Initial conditional checks:

- `telegram_context_routing_truth`
  - truth boundary: Telegram context routing behavior
  - run when the Telegram bridge routing or target-context behavior is explicitly in scope
  - keep this as a named check rather than a broad scan of all bridge code
- `policy_watch_truth`
  - truth boundary: watched-input policy and stale-context eligibility
  - run when watched structured-truth-input behavior or stale-context notification behavior is in scope
  - this is the bridge-facing check that ties watched structured-truth inputs to warning eligibility
  - updates the separate policy-derived stale-context eligibility field, not the machine-truth fingerprint

The first slice should not add a larger registry than this unless a later section clearly depends on it.

## V2+ Scan Limits

- the whole repo every night
- every log file on the machine
- every old archive document
- every chat history file
- every Telegram message

The loop should stay focused on the files and commands that define stable truth and current health.

## Shared Alignment Logic

For each mismatch, the loop must answer four questions.

1. Is this mismatch real?
2. Is it structural or temporary?
3. Which truth layer is supposed to hold this fact?
4. Does the mismatch require stale-context warning delivery?

### If The Mismatch Is Structural

Examples:

- rendered summary says a runtime works one way, but structured truth or code says otherwise
- capability docs name the wrong current behavior
- a rendered summary file is stale after a deliberate code/config change

Action:

- update structured truth state first
- then update only explicitly approved rendered truth targets that are now out of date
- record what changed and why
- mark that stale-context warnings may need to be sent to active chats

If the mismatch comes from claim verification in audit-only mode:

- do not rewrite the source doc yet
- persist the stale claim result
- surface the mismatch in the report for operator review

### If The Mismatch Is Operational

Examples:

- service is down
- retry rate spiked
- requests failed in the last 24 hours

Action:

- write it into structured health state and the nightly report
- do not rewrite permanent rendered summary docs just because of a temporary health issue

### If The Mismatch Is Only A Conversation Claim

Examples:

- a user says the system works one way
- prior chat text claims a capability that the code does not support

Action:

- do not promote the claim into truth
- leave stable docs unchanged
- rely on code/runtime truth

## V2+ Stale Session Handling

The follow-on system should not silently discard session context when structured-truth inputs change.

Instead, it should:

1. detect that watched structured-truth inputs changed
2. detect that active chats may still be carrying older session context
3. send a clear warning message to those chats
4. let the user decide whether to drop the old context

This keeps the system transparent.

The user-facing command for dropping stale carried context should be:

- `/reset`

The meaning of `/reset` in this design is:

- clear the carried session context for this chat or scope
- keep the runtime alive
- start the next request from the current truth baseline instead of the older carried context

This is narrower than a broad global reset.

## Shared Alignment Flow

The loop achieves alignment in five steps, always with the primary end state being actual system truth aligned to maintained structured truth state.

### 1. Observe

Collect the current observed truth from code, manifest, status commands, and health snapshots.

### 2. Compare

Compare observed truth against structured truth state first, then compare rendered summaries against that structured truth state. The purpose of the comparison is to move actual system truth back into alignment with maintained structured truth state, not to preserve prose consistency for its own sake.

### 3. Classify

Decide whether each mismatch is:

- structural drift
- temporary operational issue
- stale summary
- stale session risk
- noise that should be ignored

### 4. Correct

Update the right layer so actual system truth converges with maintained structured truth state:

- structural drift -> structured truth state first, then rendered summary docs
- temporary operational issue -> structured health state and nightly report
- stale session risk -> truth fingerprint change and stale-context warning eligibility

### 5. Persist

Write the results in machine-readable state first, then refresh any secondary rendered explanation outputs.

## Outputs

The loop should write primary structured outputs and secondary explanation outputs.

### 1. Latest Truth State

Suggested path:

- `/var/lib/server3-dream-loop/latest_truth_state.json`

Purpose:

- primary machine-readable truth baseline
- input for future automation or status commands

Suggested contents:

- observed timestamp
- timezone
- truth sources scanned
- normalized runtime truth facts
- normalized capability truth facts
- normalized watched-file truth facts
- normalized stale-context warning facts

### 2. Latest Health State

Suggested path:

- `/var/lib/server3-dream-loop/latest_health_state.json`

Purpose:

- primary machine-readable health and pain baseline

Suggested contents:

- observed timestamp
- timezone
- observer summary
- runtime status summary
- operational issues found
- degraded services and signals
- unresolved operator-visible health concerns

### 3. Latest Run State

Suggested path:

- `/var/lib/server3-dream-loop/latest_run_state.json`

Purpose:

- run-level bookkeeping for the most recent loop pass
- audit record of the execution itself, not a source of truth about the system

Suggested contents:

- observed timestamp
- timezone
- run start and end timestamps
- exit status
- checks executed
- files updated
- artifacts written
- unresolved items
- warnings emitted
- skipped checks and reasons

If commit/push automation is added later, those results belong in run state rather than truth state or health state.

### 4. Read-Only Truth Status

User-facing command:

- `/truth_status`

V1 note:

- the first slice does not need a user-facing status command unless it is required to keep the machine truth outputs coherent
- if implemented later, it should remain a read-only view over structured state, not a new source of truth

Purpose:

- let a user inspect the current truth-alignment state for the current chat or scope

The output should stay compact and operator-readable.

Suggested fields:

- last dream-loop run time
- whether the last run succeeded or failed
- whether truth changed on the last run
- which watched structured-truth inputs changed
- whether any approved claims are currently stale for this chat/runtime scope
- short claim-drift summary
- whether this current chat or topic has a stale-context warning outstanding
- whether `/reset` has already been used in this chat or topic since the last truth change
- short summary of what was aligned
- unresolved items that were skipped because they needed human judgment
- one short global system line

### 5. Latest Report

Suggested path:

- `/var/lib/server3-dream-loop/latest_report.md`

Purpose:

- human-readable explanation of the current structured truth and health state
- conservative rendered output, not a new maintenance surface

Suggested contents:

- last run time
- success or failure
- whether truth changed
- claim drift summary
- files changed
- commit SHA if a push succeeded
- warning count
- unresolved items
- what still needs human attention

### 6. History

Suggested path:

- `/var/lib/server3-dream-loop/history.jsonl`

Purpose:

- durable per-run audit trail

V1 note:

- history is optional for the first slice unless needed to support the three primary outputs

## Which Files Should Be Updated

The dream loop should be conservative about human-readable files.

Its primary write target should be structured truth, health, and run state.

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

## Watched Structured-Truth Inputs

These inputs define the currently watched structured-truth set for stale-context warning purposes.

The machine-truth fingerprint must be derived from structured truth inputs only.
Policy files are not part of that fingerprint input set.

It must not be derived from:

- `SERVER3_SUMMARY.md`
- `latest_report.md`
- Telegram summaries
- any other secondary human-readable explainer output

Policy-derived stale-context eligibility is tracked as a separate structured-truth field in the truth state.
That field may change when policy files change even if the machine-truth fingerprint does not.
When that happens, the later notification path must describe it as a policy-derived stale-context change, not as a machine-truth input change.

Initial watched structured-truth inputs:

- `ARCHITECT_INSTRUCTION.md`
- `LESSONS.md`
- `infra/server3-runtime-manifest.json`

When one or more watched structured-truth inputs change in a way that changes the machine-truth fingerprint:

- the system should consider long-lived carried context potentially stale
- the system should record stale-context warning eligibility for affected chats
- the user can choose to run `/reset`

If the structured truth state or its fingerprint does not change, the loop should not send stale-context warnings just because prose was edited.

The watched structured-truth set can be expanded later when more truth-defining inputs are intentionally added to the machine self-model.

## Session Notification

Updating structured-truth inputs is not enough if persistent sessions still carry old beliefs.

But the design should not silently wipe those sessions.

So the dream loop must be tied into a notification path.

That means:

- truth-defining structured inputs are watched
- secondary rendered explainer files are excluded from the machine-truth fingerprint
- a nightly truth update changes the structured truth state or machine-truth fingerprint
- affected chats are marked stale-context eligible
- v1 does not deliver the notification to chats; later bridge work handles actual delivery
- later delivery can tell them to use `/reset` if they want a fresh session aligned to the new truth

This is how corrected truth reaches the live assistant behavior without hidden session loss.

The stale-context trigger must key off machine-truth changes, not merely wording changes in human explainer files.

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
  - the user runs `/reset`
  - a later truth change creates a new warning condition

Warning delivery rule:

- send stale-context warnings only after structured truth updates or a machine-truth fingerprint change has been recorded
- do not send stale-context warnings for prose-only edits that leave machine truth unchanged

### Warning Message

The warning should be short and explicit.

If the warning was triggered by a machine-truth fingerprint change, it should include:

- that structured-truth inputs changed
- that carried session context may now be stale
- the changed watched structured-truth inputs
- that the user can send `/reset`

Suggested message shape:

`Truth inputs changed and this session may now carry stale context. Changed inputs: ARCHITECT_INSTRUCTION.md, infra/server3-runtime-manifest.json. Send /reset if you want a fresh session aligned to the new truth.`

If the warning was triggered by a policy-only stale-context eligibility change, it should instead include:

- that stale-context policy changed
- that carried session context may now be stale under the new policy
- the changed policy source or rule area
- that the user can send `/reset`

Suggested message shape:

`Stale-context policy changed and this session may now be stale under the new policy. Changed policy sources: src/telegram_bridge/runtime_config.py, src/telegram_bridge/session_manager.py. Send /reset if you want a fresh session aligned to current truth.`

## Reset Command

User-facing command:

- `/reset`

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
- otherwise use the structured nightly truth baseline plus current verified session changes
- if a stale-context warning was sent, the user may choose `/reset` before continuing

The dream loop reduces future drift.

It does not replace normal technical judgment.

## Suggested Implementation Shape

Suggested new files:

- `ops/dream_loop/dream_loop.py`
- `infra/systemd/server3-dream-loop.service`
- `infra/systemd/server3-dream-loop.timer`
- `docs/runbooks/server3-dream-loop.md`

Likely supporting changes:

- add a manual “run now” command or entry point for the dream loop
- add tests for dream-loop truth and health classification logic
- add tests for the report layer output shape

Later-phase supporting changes may include:

- update watched structured-truth inputs in `src/telegram_bridge/runtime_config.py`
- use the existing user-facing `/reset` command in the bridge command layer for stale-context realignment
- add a user-facing `/truth_status` command in the bridge command layer
- add stale-context notification delivery tied to watched structured-truth input changes
- add daily Telegram summary delivery if operators still want it after the bounded runner is stable
- document the truth hierarchy in `ARCHITECT_INSTRUCTION.md`

### V1 Implementation Boundary

The first slice should only implement what is necessary to keep the primary machine-readable truth and health outputs correct and to render the conservative report layer from them.
It must stay bounded to the first safe slice and must not absorb later-phase delivery features.

That means v1 should prioritize:

1. collecting the minimum truth inputs needed for the primary outputs
2. normalizing those inputs into structured truth, health, and run state
3. writing `latest_truth_state.json`
4. writing `latest_health_state.json`
5. writing `latest_run_state.json`
6. rendering `latest_report.md` from those machine-readable states
7. verifying those four outputs
8. staying within runner-side state production and conservative reporting only

Later work can extend the registry, notifications, status commands, Telegram summaries, and broader automation once the bounded core slice is stable.
In v1, the runner must not silently grow into user-facing status commands, Telegram summary delivery, or stale-context notice delivery.
In v1, the runner must not perform stale-context notice delivery.
v1 does not perform actual chat notification delivery.

### Execution Order

The dream loop should run in a fixed order.

Recommended order:

1. scan truth sources
2. normalize observed truth into structured truth and health state
3. classify mismatches
4. write local state outputs
5. render the conservative report from the written machine state
6. verify the outputs
7. stop

Do not insert user-facing status commands, Telegram summaries, or stale-context notices into the v1 execution path.

If later-phase notification delivery is added, stale-context notices must happen after the state write succeeds, not before.

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
- exercise the same bounded runner as dry-run mode, but with operator intent

### Dry Run

There should be a dry-run mode.

Purpose:

- show what the dream loop would change
- show what it would report
- do not edit files
- do not commit
- do not push
- do not notify chats

The dry-run mode is the first safe implementation step because it exercises the bounded scan/normalize/classify/emit path without introducing side effects.
The manual run comes next so operators can invoke the same bounded runner directly before any full nightly automation is enabled.
The execution order should stay conservative: dry-run first, manual run second, nightly automation only after both are stable.

Implementation order:

1. build the bounded runner that can scan, normalize, classify, and emit truth, health, and report outputs
2. expose it in dry-run mode first so the pipeline can be validated without side effects
3. add the manual run entrypoint so operators can invoke the same bounded runner on demand
4. enable broader nightly automation only after the dry-run and manual-run paths are stable and trusted

### Dream Loop Edit Rights

The dream loop may directly edit `SERVER3_SUMMARY.md` only where an explicit approved correction target allows it.

The intended rule is not broad section-based ownership.

The intended rule is:

- in audit-only mode, do not edit claim surfaces just because claim drift was detected
- in corrective mode, edit only approved claim-backed targets or the small transitional mapped fields that remain explicitly allowed during migration
- do not rewrite the file casually when no truth mismatch exists
- do not treat whole-section ownership as permission for broad free-form rewriting

In this design, `SERVER3_SUMMARY.md` is a secondary rendered explanation layer, not the primary truth store.

### Commit And Push Behavior

Commit and push behavior is out of scope for the first implementation slice.

If added later, it should be an explicit follow-on capability, not a prerequisite for v1 truth outputs.

If added later, failures should be reported in the daily summary, but they should not block the bounded v1 outputs.

### Uncertain Mismatches

If the dream loop cannot classify a mismatch confidently, it should:

- skip the automatic correction
- record the unresolved item
- include it in the report and, if later implemented, `/truth_status` output

## Safety Rules

The dream loop must:

- prefer small scoped updates
- never treat conversation text as truth by itself
- not rewrite permanent docs for temporary health issues
- not silently change broad policy docs
- not silently drop user session context when structured-truth inputs change
- leave a durable record of every correction it makes

## Success Criteria

V1 is working if:

- actual system truth and structured truth state stay aligned as the primary maintained self-model
- the primary maintained self-model is structured truth state, not the human-readable explainer layer
- human-readable explainers are derived from structured truth state as a secondary rendered explanation
- rendered summary docs stop drifting behind structured truth and real code/runtime changes
- structured truth state stays aligned to real code and runtime changes
- stale carried context is detected from machine-truth changes, not prose-only edits
- dry-run and manual-run paths make rollout and debugging practical
- daytime replies need fewer broad re-checks
- temporary operational incidents are recorded without corrupting permanent docs
- operators can inspect one daily report and see what was aligned

Later-phase success criteria may include:

- users are warned when persistent sessions may now carry stale truth
- `/reset` gives users a clean way to realign a chat to the new truth baseline
- `/truth_status` lets a user inspect the current alignment state of the chat or topic

## Source Of Truth

This file is the planning source for the Server3 dream-loop alignment design until implementation begins.
