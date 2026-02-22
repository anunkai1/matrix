# Server3 Archive

Summary-first note:
- Read `SERVER3_SUMMARY.md` first for normal session context.
- Use this file as the detailed archive when additional history/diagnostics are needed.

## 2026-02-22 (Summary-First Context Workflow + Doc Consistency Fixes)

### Summary
- Added summary-first session context file: `SERVER3_SUMMARY.md`.
- Updated authoritative workflow policy in `ARCHITECT_INSTRUCTION.md`:
  - session start now requires `SERVER3_SUMMARY.md` first
  - `SERVER3_ARCHIVE.md` is now detailed archive context loaded when needed
  - session-end update requirement now centers on `SERVER3_SUMMARY.md`, with archive updates for detailed archival scenarios
- Updated documentation for consistency:
  - `README.md` progress-tracking and structure references updated for summary-first workflow
  - `docs/telegram-architect-bridge.md` refreshed runtime file map and canonical-session env flags
  - `docs/home-assistant-ops.md` fixed stale env-file examples and corrected scheduled-action cancel flow
  - `docs/handoffs/voucher-automation-resume-handoff.md` aligned with current proof command (`git show --stat --oneline -1`) and summary-first startup workflow
- No runtime/service/live system changes were made.

### Git State
- Current branch: `main`
- Remote: `origin https://github.com/anunkai1/matrix.git`

### Notes
- This change set is documentation/policy only.

## 2026-02-22 (Policy Hardening: Beginner Clarity + Brisbane Timestamp Standard)

### Summary
- Updated `ARCHITECT_INSTRUCTION.md` to improve execution safety and beginner clarity.
- Git safety updates:
  - removed masked pull behavior (`git pull --ff-only` now hard-stop on failure)
  - replaced weak post-commit proof (`git diff --stat`) with `git show --stat --oneline -1`
  - changed staging guidance to explicit file paths by default, with `git add -A` only when intentionally staging all task changes
- Policy clarity updates:
  - renamed repo settings section from placeholder wording to current-state wording
  - added explicit exempt vs non-exempt quick decision rule under HA boundary
- Traceability time standard updates:
  - required `logs/` timestamps now must use Australia/Brisbane ISO-8601 with offset (AEST, +10:00)
- Bootstrap/enforceability updates:
  - added mandatory bootstrap mention for `tasks/lessons.md` in from-scratch rules
  - expanded section 7B with minimal schema requirements for each lesson entry
- Created new file: `tasks/lessons.md` with minimal template for lesson capture.
- Removed decorative emoji heading style in `ARCHITECT_INSTRUCTION.md` for cleaner policy readability.
- No runtime/service/live system changes were made.

### Git State
- Current branch: `main`
- Remote: `origin https://github.com/anunkai1/matrix.git`

### Notes
- These are documentation/policy hardening changes only.
- Brisbane timestamp requirement applies to future repo-tracked execution logs.

## 2026-02-22 (Workflow Policy: Execution Quality Gates Added)

### Summary
- Updated `ARCHITECT_INSTRUCTION.md` with new mandatory section:
  - `7. EXECUTION QUALITY GATES (MANDATORY)`
- Added non-redundant enforcement rules for the selected top-3 workflow points:
  - verification-before-done net-new requirements:
    - behavior diff vs `main` when relevant
    - tests/log checks + correctness evidence
    - final staff-engineer quality check prompt
  - self-improvement loop requirements:
    - capture user-correction patterns and prevention rules in `tasks/lessons.md`
    - review and apply relevant lessons at session start
  - plan-mode net-new requirements:
    - stop and re-plan when execution deviates or assumptions break
    - include explicit verification steps for non-trivial work
- No runtime/service/live system changes were made.

### Git State
- Current branch: `main`
- Remote: `origin https://github.com/anunkai1/matrix.git`

### Notes
- Existing plan/commit/push/proof gates remain unchanged.
- New section was written to avoid duplicating already-enforced rules.

## 2026-02-22 (Voucher Automation: Resume Handoff Prompt + Telegram Delivery)

### Summary
- Added a resume handoff document for paused voucher automation work:
  - `docs/handoffs/voucher-automation-resume-handoff.md`
- Handoff includes:
  - beginner-friendly high-level status summary
  - full LLM/Codex continuation prompt with decisions, constraints, rollback status, and next sequence
- Sent the handoff markdown file to Telegram chat ID `211761499` as a document for easy reuse in a new chat.
- No voucher automation implementation code was added in this step.
- No live staker/server1 changes were made in this step.

### Git State
- Current branch: `main`
- Remote: `origin https://github.com/anunkai1/matrix.git`

### Notes
- This change is documentation/operational handoff only.
- Voucher automation implementation remains pending.

## 2026-02-22 (Telegram Bridge: Live Canonical Rollout Enable + Restart Verification)

### Summary
- Applied live runtime env rollout for canonical session mode with temporary legacy-mirror safety.
- Updated live `/etc/default/telegram-architect-bridge` flags:
  - `TELEGRAM_CANONICAL_SESSIONS_ENABLED=true`
  - `TELEGRAM_CANONICAL_LEGACY_MIRROR_ENABLED=true`
- Created live env backup before apply:
  - `/etc/default/telegram-architect-bridge.bak-20260222-001727-canonical-rollout`
- Restarted and verified bridge service:
  - `bash ops/telegram-bridge/restart_and_verify.sh`
  - verification passed (`active/running`, new main PID observed)
- Journal confirms canonical rollout is active:
  - `Canonical sessions enabled=True ...`
  - `Canonical legacy mirror enabled=True`
- Updated repo-tracked mirrors and live-change record:
  - `infra/env/telegram-architect-bridge.server3.redacted.env`
  - `infra/env/telegram-architect-bridge.env.example`
  - `logs/changes/20260222-001727-telegram-canonical-rollout-enable-and-restart.md`

### Git State
- Current branch: `main`
- Remote: `origin https://github.com/anunkai1/matrix.git`

### Notes
- No code logic changes were made in this rollout step.
- This step activates previously-implemented canonical mode in live runtime config.

## 2026-02-21 (Telegram Bridge: Canonical Session Model Phase 3 - Canonical-Only Runtime Path)

### Summary
- Completed Phase 3 canonical-session migration by finalizing canonical-only runtime semantics when canonical mode is enabled.
- Added temporary rollback mirror control:
  - new config flag: `TELEGRAM_CANONICAL_LEGACY_MIRROR_ENABLED` (default `false`)
  - wired to `Config.canonical_legacy_mirror_enabled` and `State.canonical_legacy_mirror_enabled`
- Updated `src/telegram_bridge/state_store.py`:
  - canonical-first operations now mirror legacy files only when rollback mirror flag is enabled
  - added canonical->legacy conversion helpers:
    - `_canonical_session_to_legacy(...)`
    - `build_legacy_from_canonical(...)`
    - `canonical_session_is_empty(...)`
  - `mirror_legacy_from_canonical(...)` now always keeps in-memory legacy views aligned, but persists legacy files only when rollback mirror flag is enabled
- Updated `src/telegram_bridge/session_manager.py` canonical-mode lifecycle paths to honor optional legacy mirror persistence.
- Updated startup behavior in `src/telegram_bridge/main.py`:
  - added canonical legacy mirror config parsing
  - canonical mode startup now uses canonical source-of-truth path with optional legacy persistence based on rollback mirror flag
  - startup logging now reports canonical legacy mirror enablement.
- Updated `src/telegram_bridge/handlers.py` status reporting:
  - `/status` now reports context/worker counts directly from canonical sessions when canonical mode is enabled (independent of legacy mirror persistence).
- Expanded tests in `tests/telegram_bridge/test_bridge_core.py`:
  - canonical-first + mirror-enabled persistence behavior
  - canonical-first + mirror-disabled no-legacy-persist behavior
  - total test count now 11.
- Updated `README.md` to document canonical mode and temporary rollback mirror flag.

### Validation
- `python3 -m py_compile src/telegram_bridge/main.py src/telegram_bridge/executor.py src/telegram_bridge/handlers.py src/telegram_bridge/media.py src/telegram_bridge/session_manager.py src/telegram_bridge/state_store.py src/telegram_bridge/stream_buffer.py src/telegram_bridge/transport.py` (pass)
- `python3 -m unittest discover -s tests -p 'test_*.py'` (pass, 11 tests)
- `python3 src/telegram_bridge/main.py --self-test` (pass)
- `bash src/telegram_bridge/smoke_test.sh` (pass)

### Git State
- Current branch: `main`
- Remote: `origin https://github.com/anunkai1/matrix.git`

### Notes
- No live `/etc` or systemd/runtime configuration changes were made in this change set.
- Canonical mode remains feature-flagged; production behavior is unchanged unless enabled explicitly.

## 2026-02-21 (Telegram Bridge: Canonical Session Model Phase 2 - Canonical-First Behind Flag)

### Summary
- Completed Phase 2 canonical-session migration path by switching state operations to canonical-first behavior when feature flag is enabled.
- Updated `src/telegram_bridge/state_store.py`:
  - added canonical->legacy conversion helpers:
    - `build_legacy_from_canonical(...)`
    - `mirror_legacy_from_canonical(...)`
  - canonical-first repository behaviors now apply when `state.canonical_sessions_enabled`:
    - thread operations (`get_thread_id`, `set_thread_id`, `clear_thread_id`)
    - worker session clear (`clear_worker_session`)
    - in-flight operations (`mark_in_flight_request`, `clear_in_flight_request`, `pop_interrupted_requests`)
  - canonical mutations now persist `chat_sessions.json` first, then mirror legacy files (`chat_threads.json`, `worker_sessions.json`, `in_flight_requests.json`) for rollback compatibility.
- Updated startup behavior in `src/telegram_bridge/main.py`:
  - when canonical mode is enabled and `chat_sessions.json` exists, runtime now loads canonical as source-of-truth and derives legacy runtime maps from canonical snapshot.
  - when canonical mode is enabled but canonical state is empty/missing, bridge keeps compatibility fallback by deriving canonical from legacy state.
- Updated session lifecycle in `src/telegram_bridge/session_manager.py`:
  - added canonical-mode branches for `ensure_chat_worker_session(...)` and `expire_idle_worker_sessions(...)` so worker lifecycle decisions execute against canonical sessions directly.
  - in canonical mode these paths persist canonical first and mirror legacy files afterward.
- Expanded characterization coverage in `tests/telegram_bridge/test_bridge_core.py`:
  - canonical->legacy conversion test
  - canonical-first thread/worker mutation + legacy mirror persistence test
  - total unit tests now 10.
- Updated README canonical mode description to clarify rollback-compatible legacy mirroring.

### Validation
- `python3 -m py_compile src/telegram_bridge/main.py src/telegram_bridge/executor.py src/telegram_bridge/handlers.py src/telegram_bridge/media.py src/telegram_bridge/session_manager.py src/telegram_bridge/state_store.py src/telegram_bridge/stream_buffer.py src/telegram_bridge/transport.py` (pass)
- `python3 -m unittest discover -s tests -p 'test_*.py'` (pass, 10 tests)
- `python3 src/telegram_bridge/main.py --self-test` (pass)
- `bash src/telegram_bridge/smoke_test.sh` (pass)

### Git State
- Current branch: `main`
- Remote: `origin https://github.com/anunkai1/matrix.git`

### Notes
- No live `/etc` or systemd/runtime configuration changes were made in this change set.
- Flag default remains disabled; production behavior remains unchanged unless canonical mode is explicitly enabled.

## 2026-02-21 (Telegram Bridge: Canonical Session Model Phase 1)

### Summary
- Implemented Phase 1 of canonical session-model migration without runtime cutover.
- Added canonical schema and compatibility helpers in `src/telegram_bridge/state_store.py`:
  - `CanonicalSession` dataclass
  - `load_canonical_sessions(...)`
  - `build_canonical_sessions_from_legacy(...)`
  - `persist_canonical_sessions(...)`
  - sync helpers (`sync_canonical_session(...)`, `sync_all_canonical_sessions(...)`)
- Added optional runtime feature flag (off by default):
  - `TELEGRAM_CANONICAL_SESSIONS_ENABLED` -> `Config.canonical_sessions_enabled`
  - when enabled, bridge maintains `chat_sessions.json` as canonical mirror while legacy stores remain active behavior source.
- Updated startup compatibility path in `src/telegram_bridge/main.py`:
  - loads canonical store when enabled
  - falls back to compatibility snapshot built from legacy state if canonical file is absent/empty
  - quarantines corrupt canonical state files using existing quarantine path
  - logs canonical-session enablement/count/path for operator visibility
- Updated session lifecycle synchronization in `src/telegram_bridge/session_manager.py` so worker eviction/expiry and lifecycle updates keep canonical mirror aligned when enabled.
- Expanded characterization tests in `tests/telegram_bridge/test_bridge_core.py`:
  - legacy->canonical migration mapping test
  - repository canonical-sync behavior test
  - total test count now 8.
- Updated `README.md` status line to document optional canonical-session flag.

### Validation
- `python3 -m py_compile src/telegram_bridge/main.py src/telegram_bridge/executor.py src/telegram_bridge/handlers.py src/telegram_bridge/media.py src/telegram_bridge/session_manager.py src/telegram_bridge/state_store.py src/telegram_bridge/stream_buffer.py src/telegram_bridge/transport.py` (pass)
- `python3 -m unittest discover -s tests -p 'test_*.py'` (pass, 8 tests)
- `python3 src/telegram_bridge/main.py --self-test` (pass)
- `bash src/telegram_bridge/smoke_test.sh` (pass)

### Git State
- Current branch: `main`
- Remote: `origin https://github.com/anunkai1/matrix.git`

### Notes
- No live `/etc` or systemd/runtime configuration changes were made in this change set.
- This phase intentionally avoids canonical-only cutover; legacy stores continue to drive runtime behavior by default.

## 2026-02-21 (Telegram Bridge: Full Low-Risk Module Split Completion)

### Summary
- Completed full low-risk module split for Telegram bridge runtime while preserving behavior and existing runtime contracts.
- Refactored `src/telegram_bridge/main.py` into orchestration/bootstrap only (`load_config`, self-test, startup/backlog handling, polling loop).
- Added new runtime modules:
  - `src/telegram_bridge/transport.py` (Telegram client + chunking)
  - `src/telegram_bridge/executor.py` (executor stream/progress parsing + bounded buffering execution wrapper)
  - `src/telegram_bridge/state_store.py` (state dataclasses + persistence/load/store APIs)
  - `src/telegram_bridge/session_manager.py` (rate limiting, worker lifecycle, restart orchestration)
  - `src/telegram_bridge/handlers.py` (message routing, prompt pipeline, command handlers, progress reporter)
- Kept existing helper modules:
  - `src/telegram_bridge/media.py`
  - `src/telegram_bridge/stream_buffer.py`
- Expanded characterization test coverage:
  - `tests/telegram_bridge/test_bridge_core.py` now includes `/status` routing assertion in addition to parser/state/session/buffer checks.
- Updated CI compile scope in `.github/workflows/telegram-bridge-ci.yml` to include all split bridge modules.
- Updated README structure section to reflect new module layout.

### Validation
- `python3 -m py_compile src/telegram_bridge/main.py src/telegram_bridge/executor.py src/telegram_bridge/handlers.py src/telegram_bridge/media.py src/telegram_bridge/session_manager.py src/telegram_bridge/state_store.py src/telegram_bridge/stream_buffer.py src/telegram_bridge/transport.py` (pass)
- `python3 src/telegram_bridge/main.py --self-test` (pass)
- `python3 -m unittest discover -s tests -p 'test_*.py'` (pass, 6 tests)
- `bash src/telegram_bridge/smoke_test.sh` (pass)

### Git State
- Current branch: `main`
- Remote: `origin https://github.com/anunkai1/matrix.git`

### Notes
- No live `/etc` or systemd/runtime configuration changes were made in this change set.
- Canonical `chat_threads` + `worker_sessions` data-model unification remains intentionally deferred as medium-risk follow-up.

## 2026-02-21 (Telegram Bridge: Low-Risk Structure Refactor + Test Gates)

### Summary
- Completed a low-risk internal refactor focused on structure/testability with no intentional runtime behavior change.
- Refactored `src/telegram_bridge/main.py`:
  - split prompt handling into explicit pipeline helpers:
    - `prepare_prompt_input(...)`
    - `execute_prompt_with_retry(...)`
    - `finalize_prompt_success(...)`
  - introduced `StateRepository` adapter for thread/in-flight/session state operations at call sites.
  - consolidated duplicated JSON persistence write pattern via `persist_json_state_file(...)`.
  - consolidated duplicated Telegram media download logic via shared helper:
    - `src/telegram_bridge/media.py` (`TelegramFileDownloadSpec`, `download_telegram_file_to_temp(...)`)
  - added bounded executor stdout/stderr buffering with truncation marker to cap memory growth on noisy runs.
- Began module split from monolith (move-only utility extraction):
  - added `src/telegram_bridge/media.py`
  - added `src/telegram_bridge/stream_buffer.py`
- Added focused unit tests:
  - `tests/telegram_bridge/test_bridge_core.py`
  - coverage includes parser output handling, bounded buffer behavior, download guard behavior, state repository persistence, and worker-capacity rejection behavior.
- Added lightweight CI workflow:
  - `.github/workflows/telegram-bridge-ci.yml` (compile + unit tests + self/smoke tests)
- Updated `README.md` with local validation commands and CI reference.

### Validation
- `python3 -m py_compile src/telegram_bridge/main.py src/telegram_bridge/media.py src/telegram_bridge/stream_buffer.py` (pass)
- `python3 src/telegram_bridge/main.py --self-test` (pass)
- `python3 -m unittest discover -s tests -p 'test_*.py'` (pass)
- `bash src/telegram_bridge/smoke_test.sh` (pass)

### Git State
- Current branch: `main`
- Remote: `origin https://github.com/anunkai1/matrix.git`

### Notes
- No live `/etc` or systemd/runtime configuration changes were made in this change set.
- Canonical model unification of `chat_threads` + `worker_sessions` remains intentionally deferred as a higher-risk follow-up.

## 2026-02-21 (Telegram Bridge: Unreachable Worker Guard Cleanup)

### Summary
- Applied additional low-risk cleanup in `src/telegram_bridge/main.py` by removing unreachable guard logic in `process_message_worker(...)`.
- Removed dead `prompt_invoked` flag and no-op `finally` branch that could never execute.
- Runtime behavior remains unchanged; `process_prompt(...)` retains ownership of request finalization and cleanup.
- Validation:
  - `python3 -m py_compile src/telegram_bridge/main.py` (pass)
  - `python3 src/telegram_bridge/main.py --self-test` (pass)
  - `bash src/telegram_bridge/smoke_test.sh` (pass)

### Git State
- Current branch: `main`
- Remote: `origin https://github.com/anunkai1/matrix.git`

### Notes
- No live `/etc` or systemd/runtime configuration changes were made in this change set.

## 2026-02-21 (Telegram Bridge: Persistent-Worker Safe Cleanup)

### Summary
- Applied low-risk cleanup in `src/telegram_bridge/main.py` after persistent-worker rollout, focused on reducing redundant state writes without changing user-visible bridge behavior.
- Removed redundant session-touch call in `process_prompt(...)`; session freshness is already handled earlier via `ensure_chat_worker_session(...)`.
- Removed dead helper function `touch_worker_session(...)` (no remaining call sites).
- Optimized persistence behavior:
  - `set_thread_id(...)` now persists `chat_threads.json` only when mapping changes.
  - `clear_thread_id(...)` now persists `worker_sessions.json` only when a worker session exists.
- Added repo-tracked change record:
  - `logs/changes/20260221-094437-telegram-persistent-worker-safe-cleanup.md`
- Validation:
  - `python3 -m py_compile src/telegram_bridge/main.py` (pass)
  - `python3 src/telegram_bridge/main.py --self-test` (pass)
  - `bash src/telegram_bridge/smoke_test.sh` (pass)
  - targeted state behavior verification snippet (pass)

### Git State
- Current branch: `main`
- Remote: `origin https://github.com/anunkai1/matrix.git`

### Notes
- No live `/etc` or systemd/runtime configuration changes were made in this change set.
- Larger structural simplification (single source of truth for thread/session state) remains deferred to keep this change set low risk.

## 2026-02-21 (Telegram Bridge: Feature-Flagged Persistent Worker Sessions)

### Summary
- Implemented feature-flagged persistent worker-session lifecycle management in `src/telegram_bridge/main.py` using per-chat session metadata backed by `thread_id` reuse.
- Added new runtime config flags:
  - `TELEGRAM_PERSISTENT_WORKERS_ENABLED` (default `false`)
  - `TELEGRAM_PERSISTENT_WORKERS_MAX` (default `4`)
  - `TELEGRAM_PERSISTENT_WORKERS_IDLE_TIMEOUT_SECONDS` (default `2700`)
- Added worker-session state persistence:
  - state file: `/home/architect/.local/state/telegram-architect-bridge/worker_sessions.json`
  - sessions are restored across bridge restart when feature is enabled.
- Implemented selected behavior set for persistent worker mode:
  - overlap requests in same chat remain rejected while busy
  - max-worker capacity enforcement with idle-session eviction
  - 45-minute idle session expiry path with user notification that context was cleared
  - policy/context file change detection (`AGENTS.md`, `ARCHITECT_INSTRUCTION.md`, `SERVER3_ARCHIVE.md`) applied on next message with user notice and session reset
  - `/reset` now clears both saved thread context and persistent worker session metadata
  - `/status` now reports persistent-worker enablement and current chat worker state
  - automatic one-time retry path for execution failures in persistent-worker mode, followed by explicit user-facing retry-failed notice
- Updated docs/env templates:
  - `infra/env/telegram-architect-bridge.env.example`
  - `docs/telegram-architect-bridge.md`
  - `README.md`
- Validation:
  - `python3 -m py_compile src/telegram_bridge/main.py`
  - `python3 src/telegram_bridge/main.py --self-test` (pass)
  - `bash src/telegram_bridge/smoke_test.sh` (pass)

### Git State
- Current branch: `main`
- Remote: `origin https://github.com/anunkai1/matrix.git`

### Notes
- Rollout remains guarded by feature flag; default runtime behavior is unchanged until `TELEGRAM_PERSISTENT_WORKERS_ENABLED=true`.

## 2026-02-21 (HA Ops: Reliable Delayed Climate Scheduling Scripts)

### Summary
- Implemented repo-tracked HA operations scripts to prevent transient `systemd-run` variable-expansion failures in delayed climate actions.
- Added new scripts under `ops/ha/`:
  - `set_climate_temperature.sh`
    - validates climate entity + temperature input
    - reads HA URL/token from explicit env file or direct args
    - executes `climate.set_temperature` and reports result
    - supports `--dry-run` validation mode
  - `schedule_climate_temperature.sh`
    - schedules delayed climate actions via transient systemd timer/service
    - executes the set script directly (no inline `${...}` shell in unit command)
    - prints timer/service unit names for traceability and cancel/inspect workflows
    - supports scheduled `--dry-run` canary mode
- Added runbook:
  - `docs/home-assistant-ops.md`
- Updated docs index:
  - `README.md` now links to the HA ops runbook in Operations and Related Docs.
- Validation:
  - `bash -n ops/ha/set_climate_temperature.sh ops/ha/schedule_climate_temperature.sh`
  - canary schedule test (dry-run): `--delay 10s`
  - journal confirms successful trigger + script execution without unset-variable errors:
    - `ha-climate-temp-20260221062215.service`

### Git State
- Current branch: `main`
- Remote: `origin https://github.com/anunkai1/matrix.git`

### Notes
- No live `/etc` configuration edits were made in this change set.
- For environments where `/etc/default/telegram-architect-bridge` no longer contains HA keys, use `--env-file` with a file that does.

## 2026-02-20 (Telegram Bridge: Live Progress Streaming + Typing Updates)

### Summary
- Implemented live Architect progress updates for Telegram requests and removed the old static thinking placeholder behavior.
- Updated `src/telegram_bridge/main.py`:
  - added real-time executor stream handling for JSON events from Codex
  - added `ProgressReporter` for:
    - periodic Telegram `typing` actions while work is in progress
    - in-place edited progress message with elapsed time + current step
  - wired event-to-status mapping for `turn`, `reasoning`, `command_execution`, and `agent_message` events
  - removed worker path that sent `💭🤔💭.....thinking.....💭🤔💭 (/h)` before execution
  - added self-tests for streamed executor output parsing and progress event extraction
- Updated `src/telegram_bridge/executor.sh`:
  - removed end-of-run buffering/parsing
  - now streams `codex exec --json` output directly for live progress consumption
- Updated docs:
  - `README.md`
  - `docs/telegram-architect-bridge.md`
- Added repo-tracked change record:
  - `logs/changes/20260220-154505-telegram-live-progress-streaming.md`
- Validation:
  - `python3 -m py_compile src/telegram_bridge/main.py`
  - `bash src/telegram_bridge/smoke_test.sh` (pass)
  - executor stream sanity check via `bash src/telegram_bridge/executor.sh new` (JSON stream observed)
  - `bash ops/telegram-bridge/restart_and_verify.sh` (pass)
  - service healthy after restart (`active/running`, start `Fri 2026-02-20 15:46:06 AEST`)

### Git State
- Current branch: `main`
- Remote: `origin https://github.com/anunkai1/matrix.git`

### Notes
- No live `/etc/default/telegram-architect-bridge` env changes were required in this change set.

## 2026-02-20 (Telegram Bridge: Permanent Architect-Only Code/Docs Cleanup)

### Summary
- Completed full permanent Architect-only cleanup for Telegram bridge runtime and repo artifacts.
- Removed Home Assistant-specific bridge components from repo:
  - deleted `src/telegram_bridge/ha_control.py`
  - deleted `infra/home_assistant/packages/architect_executor.yaml`
  - deleted `ops/home-assistant/validate_architect_package.sh`
- Refactored `src/telegram_bridge/main.py`:
  - removed split chat routing and HA conversation handling code paths
  - removed HA conversation state handling
  - `/help` now describes Architect-only handling for all allowlisted chats
  - startup logs now report Architect-only routing mode
- Updated docs/templates to match permanent Architect-only behavior:
  - `README.md`
  - `docs/telegram-architect-bridge.md`
  - `infra/env/telegram-architect-bridge.env.example`
  - `infra/env/telegram-architect-bridge.server3.redacted.env`
- Updated smoke test:
  - `src/telegram_bridge/smoke_test.sh` no longer validates removed HA files
- Live server cleanup:
  - removed remaining HA env key from `/etc/default/telegram-architect-bridge` (backup created)
  - archived stale HA/pending state files under `/home/architect/.local/state/telegram-architect-bridge/`
- Validation:
  - `python3 -m py_compile src/telegram_bridge/main.py`
  - `bash src/telegram_bridge/smoke_test.sh` (pass)
  - service healthy after restart; journal confirms `Architect-only routing active for all allowlisted chats.`
- Added change record:
  - `logs/changes/20260220-153114-telegram-permanent-architect-only-cleanup.md`

### Git State
- Current branch: `main`
- Remote: `origin https://github.com/anunkai1/matrix.git`

### Notes
- Home Assistant control is no longer provided by bridge runtime. Any future HA integration would require reintroducing code and env/docs support.

## 2026-02-20 (Telegram Bridge: HA-Disabled Cleanup)

### Summary
- Completed post-migration cleanup for Architect-only Telegram operation after HA routing disablement.
- Live runtime env cleanup in `/etc/default/telegram-architect-bridge`:
  - removed residual HA-only keys (`TELEGRAM_HA_*`) that were unused with HA runtime disabled
  - retained explicit `TELEGRAM_HA_ENABLED=false`
  - backup created: `/etc/default/telegram-architect-bridge.bak-20260220-145256-ha-cleanup`
- Cleared stale HA conversation state:
  - set `/home/architect/.local/state/telegram-architect-bridge/ha_conversations.json` to empty object `{}`.
  - backup created: `/home/architect/.local/state/telegram-architect-bridge/ha_conversations.json.bak-20260220-145256`
- Updated bridge runtime/operator visibility:
  - `src/telegram_bridge/main.py` now reports HA runtime disabled in startup logs when HA config is off
  - `/help` text now reflects Architect-only behavior when HA runtime is disabled
- Updated docs/env traceability:
  - `docs/telegram-architect-bridge.md`
  - `infra/env/telegram-architect-bridge.server3.redacted.env`
  - `logs/changes/20260220-145309-telegram-ha-disabled-cleanup.md`
- Validation:
  - `python3 -m py_compile src/telegram_bridge/main.py src/telegram_bridge/ha_control.py`
  - `bash src/telegram_bridge/smoke_test.sh` (pass)
  - service healthy after restart; journal shows:
    - `Chat routing disabled. Mixed HA/Architect behavior is active.`
    - `HA conversation mode disabled by runtime config.`
    - `Loaded 0 HA conversation mapping(s) ...`

### Git State
- Current branch: `main`
- Remote: `origin https://github.com/anunkai1/matrix.git`

### Notes
- This cleanup intentionally does not delete HA support code; it removes operational redundancy and misleading runtime messaging for the current HA-disabled mode.

## 2026-02-20 (Telegram Bridge: Disable HA Routing + Disable Split Chat Mode)

### Summary
- Applied live runtime config change in `/etc/default/telegram-architect-bridge` to remove HA chat specialization and route both allowlisted chats through Architect behavior.
- Updated live env values:
  - set `TELEGRAM_HA_ENABLED=false`
  - removed `TELEGRAM_ARCHITECT_CHAT_IDS`
  - removed `TELEGRAM_HA_CHAT_IDS`
  - removed `TELEGRAM_HA_BASE_URL`
  - removed `TELEGRAM_HA_TOKEN`
- Preserved `TELEGRAM_ALLOWED_CHAT_IDS=211761499,-5144577688`.
- Backed up live env before apply:
  - `/etc/default/telegram-architect-bridge.bak-20260220-143644-disable-ha-split`
- Restarted and verified bridge runtime:
  - `bash ops/telegram-bridge/restart_and_verify.sh`
  - service healthy (`active/running`, start `Fri 2026-02-20 14:36:51 AEST`)
  - journal confirms `Chat routing disabled. Mixed HA/Architect behavior is active.`
- Updated repo-tracked mirrors/logs:
  - `infra/env/telegram-architect-bridge.server3.redacted.env`
  - `logs/changes/20260220-143651-telegram-disable-ha-routing-and-split-chat-mode.md`

### Git State
- Current branch: `main`
- Remote: `origin https://github.com/anunkai1/matrix.git`

### Notes
- This is an operational configuration switch only; no bridge source code changes were made.

## 2026-02-20 (Telegram HA: Parser Removed, Conversation-Agent Routing)

### Summary
- Replaced local HA parser/scheduler stack with direct Home Assistant Conversation API routing.
- Rewrote `src/telegram_bridge/ha_control.py` to conversation-only helpers:
  - HA config loading
  - `/api/conversation/process` client call
  - conversation reply extraction
  - per-response `conversation_id` extraction
- Updated `src/telegram_bridge/main.py` HA flow:
  - HA requests now call Home Assistant conversation directly.
  - Added per-chat HA conversation context persistence:
    - state file: `/home/architect/.local/state/telegram-architect-bridge/ha_conversations.json`
  - `/reset` now clears both Architect thread context and HA conversation context.
  - Removed local HA schedule/approval execution code paths.
- Updated docs/env templates:
  - `docs/telegram-architect-bridge.md`
  - `infra/env/telegram-architect-bridge.env.example`
  - Added/used HA conversation env vars:
    - `TELEGRAM_HA_CONVERSATION_AGENT_ID`
    - `TELEGRAM_HA_LANGUAGE`
- Validation:
  - `python3 -m py_compile src/telegram_bridge/main.py src/telegram_bridge/ha_control.py`
  - `bash src/telegram_bridge/smoke_test.sh` (pass)

### Git State
- Current branch: `main`
- Remote: `origin https://github.com/anunkai1/matrix.git`

### Notes
- This change set does not perform a live service restart from this session; apply with `bash ops/telegram-bridge/restart_and_verify.sh` on Server3.

## 2026-02-20 (Telegram HA Parser: Climate Mode-Only Intents Enabled)

### Summary
- Investigated HA-only voice/text failures for mode-only climate phrases, including:
  - `Set Master's Aircon to cold mode.`
  - `Change Master's Aircon Mode to Cold.`
  - `Master's Aircon cold mode`
- Root cause: parser required a temperature for all climate intents; mode-only commands were rejected and fell back to HA-only reminder.
- Implemented parser/executor updates in `src/telegram_bridge/ha_control.py`:
  - Added `climate_mode_set` intent/action path for mode-only climate commands.
  - Mode-only parser now accepts set/change and shorthand phrasing without explicit temperature.
  - Added explicit `turn on ... <mode>` handling by carrying `power_on_requested=True`.
  - Executor now applies `climate.set_hvac_mode`; when `power_on_requested=True`, it calls `climate.turn_on` before setting mode.
  - Token canonicalization now strips trailing periods so transcribed terms like `cold.` map correctly to `cool`.
  - Added parser self-tests for mode-only phrases (including punctuation and `only` filler variants).
- Updated docs:
  - `README.md`
  - `docs/telegram-architect-bridge.md`
- Validation:
  - `python3 -m py_compile src/telegram_bridge/ha_control.py src/telegram_bridge/main.py`
  - `bash src/telegram_bridge/smoke_test.sh` (pass)
  - targeted parser checks for the reported mode-only phrases (pass)
- Rolled out live runtime by restart + verify:
  - `bash ops/telegram-bridge/restart_and_verify.sh`
  - service healthy after restart (`active/running`, start `Fri 2026-02-20 09:19:36 AEST`)
- Added repo-tracked change record:
  - `logs/changes/20260219-231936-telegram-ha-climate-mode-only-intents.md`

### Git State
- Current branch: `main`
- Remote: `origin https://github.com/anunkai1/matrix.git`

### Notes
- No live `/etc/default` env changes were required in this change set.

## 2026-02-20 (Telegram HA Parser: Climate Room-Context + Cold-Mode Parsing Fix)

### Summary
- Investigated HA-chat ambiguity on phrase:
  - `Turn on aircon in living room to 22 degrees cold mode`
  - Prior behavior extracted target as `aircon` only, causing ambiguity across multiple room AC entities.
- Implemented parser fixes in `src/telegram_bridge/ha_control.py`:
  - Added token normalization: `cold`/`colder` -> `cool`.
  - Updated climate target extraction to preserve room context after `in` (for example `aircon in living room`).
  - Kept mode boundary handling so `in cool mode` still terminates target parsing correctly.
  - Added parser self-test case for the full living-room sentence.
- Updated docs:
  - `README.md`
  - `docs/telegram-architect-bridge.md`
- Validation:
  - `python3 -m py_compile src/telegram_bridge/ha_control.py src/telegram_bridge/main.py`
  - `bash src/telegram_bridge/smoke_test.sh` (pass)
  - targeted parser checks confirmed room-preserved targets for living/master/guest phrasing examples.
- Rolled out live runtime by restart + verify:
  - `bash ops/telegram-bridge/restart_and_verify.sh`
  - service healthy after restart (`active/running`, start `Fri 2026-02-20 09:07:14 AEST`)
- Added repo-tracked change record:
  - `logs/changes/20260219-230714-telegram-ha-climate-room-context-fix.md`

### Git State
- Current branch: `main`
- Remote: `origin https://github.com/anunkai1/matrix.git`

### Notes
- No live `/etc/default` env changes were required in this change set.

## 2026-02-20 (Telegram HA Parser: Open/Close Garage Intent Support)

### Summary
- Investigated HA-only rejection of `open garage` / `Open garage please` after voice/text transcription.
- Root cause: those phrases did not match existing HA parser intent grammar, so HA-only routing returned fallback message.
- Added parser and execution support in `src/telegram_bridge/ha_control.py`:
  - new intents: `entity_open`, `entity_close`
  - parser now recognizes natural `open ...` / `close ...` phrases
  - parser trims trailing polite suffixes in extracted target (`please`/`pls`/`kindly`)
  - action resolver prefers `cover` domain for open/close intents when matching
  - executor maps open/close by entity domain:
    - `cover.*` -> `open_cover` / `close_cover`
    - `lock.*` -> `unlock` / `lock`
    - other domains -> `turn_on` / `turn_off` fallback
  - schedule gate keywords expanded to include `open`, `close`, `garage`, `door`, `lock`, `unlock`
- Added parser self-test cases for:
  - `open garage`
  - `Open garage please`
  - `close garage`
- Updated docs:
  - `README.md`
  - `docs/telegram-architect-bridge.md`
- Validation:
  - `python3 -m py_compile src/telegram_bridge/ha_control.py src/telegram_bridge/main.py`
  - `bash src/telegram_bridge/smoke_test.sh` (pass)
  - targeted parser check snippets confirmed open/close parsing behavior
- Rolled out live runtime by restart + verify:
  - `bash ops/telegram-bridge/restart_and_verify.sh`
  - service healthy after restart (`active/running`, start `Fri 2026-02-20 08:52:37 AEST`)
- Added repo-tracked change record:
  - `logs/changes/20260219-225237-telegram-ha-open-close-intent-support.md`

### Git State
- Current branch: `main`
- Remote: `origin https://github.com/anunkai1/matrix.git`

### Notes
- No live `/etc/default` env changes were required in this change set.

## 2026-02-20 (Telegram HA-Only Chat: Voice Commands Routed Through HA Parser)

### Summary
- Implemented HA-only voice-command support in bridge runtime so voice notes no longer auto-fail with HA-only fallback.
- Added shared voice helper in `src/telegram_bridge/main.py`:
  - download voice
  - transcribe using configured voice command
  - send transcript echo
  - clean up temp voice file
- Updated HA-only routing path:
  - if voice is present (and no photo/file), transcript is now passed into existing `handle_ha_request_text(...)` parser/status flow.
  - keeps same HA parser behavior used for text requests (status/control/schedule).
- Preserved HA-only guardrails:
  - photo/document inputs still rejected in HA-only mode
  - non-HA text/voice content still returns HA-only reminder
- Updated docs/help wording for HA-only voice support:
  - `README.md`
  - `docs/telegram-architect-bridge.md`
  - chat help mode note in `src/telegram_bridge/main.py`
- Validation:
  - `python3 -m py_compile src/telegram_bridge/main.py src/telegram_bridge/ha_control.py`
  - `bash src/telegram_bridge/smoke_test.sh` (pass)
- Rolled out live runtime by restart + verify:
  - `bash ops/telegram-bridge/restart_and_verify.sh`
  - service healthy after restart (`active/running`, start `Fri 2026-02-20 07:54:19 AEST`)
- Added repo-tracked change record:
  - `logs/changes/20260219-215419-telegram-ha-voice-parser-support.md`

### Git State
- Current branch: `main`
- Remote: `origin https://github.com/anunkai1/matrix.git`

### Notes
- No live `/etc/default` env changes were required in this change set.

## 2026-02-20 (Telegram HA Allowed-Entities Allowlist Applied Live)

### Summary
- Applied live HA entity allowlist in `/etc/default/telegram-architect-bridge` by setting `TELEGRAM_HA_ALLOWED_ENTITIES` to the approved explicit list:
  - four `climate.*` aircon entities
  - approved `select.*` airflow/swing controls for those aircons
  - `switch.shelly01_water_heater`
  - `switch.tapo_p110x02`
  - `switch.shelly1minig3_garage`
- Preserved strict chat routing keys (`TELEGRAM_ALLOWED_CHAT_IDS`, `TELEGRAM_ARCHITECT_CHAT_IDS`, `TELEGRAM_HA_CHAT_IDS`) unchanged.
- Created live backup prior to apply: `/etc/default/telegram-architect-bridge.bak-20260219-214547`.
- Rolled out runtime and verified service health:
  - `ActiveState=active`, `SubState=running`
  - `ExecMainStartTimestamp=Fri 2026-02-20 07:46:11 AEST`
  - Journal confirms `Bridge started` and `Chat routing enabled`.
- Updated repo traceability artifacts:
  - `infra/env/telegram-architect-bridge.server3.redacted.env`
  - `logs/changes/20260219-214859-telegram-ha-allowed-entities-allowlist.md`

### Git State
- Current branch: `main`
- Remote: `origin https://github.com/anunkai1/matrix.git`

### Notes
- During live update, an in-place rewrite attempt was detected as unsafe after truncation behavior; the env file was immediately restored from backup and then re-applied via temp-file install to preserve full file content.

## 2026-02-20 (Telegram HA Chat: OFF Status Queries + Climate Turn-On Intent Fix)

### Summary
- Investigated two live HA-chat issues:
  - `whats off` / `whats off in HA` returned HA-only fallback instead of status results.
  - `turn on AC living to 25` set temperature but did not reliably power the climate entity on.
- Implemented parser/executor fixes in bridge runtime:
  - Added HA status-query mode parsing (`on`/`off`) and OFF-query phrase support in `src/telegram_bridge/ha_control.py`.
  - Added status summary generation for both ON and OFF views, constrained to allowed HA domains/entities.
  - Kept mixed-chat routing guard: implicit status prompts without explicit HA context are still not auto-routed to HA.
  - Added `power_on_requested` intent flag for climate commands expressed as `turn on ... to <temp>`.
  - Updated climate execution path to call `climate.turn_on` when no HVAC mode is provided, then apply `climate.set_temperature`.
  - Updated execution messaging to reflect turn-on behavior when that path is used.
- Updated docs:
  - `README.md`
  - `docs/telegram-architect-bridge.md`
- Validation:
  - `python3 -m py_compile src/telegram_bridge/ha_control.py src/telegram_bridge/main.py`
  - `bash src/telegram_bridge/smoke_test.sh` (pass)
  - targeted parser checks for OFF query modes and turn-on climate intent flag (pass)
- Rolled out live runtime by restarting and verifying service:
  - `bash ops/telegram-bridge/restart_and_verify.sh`
  - service healthy after restart (`active/running`, start `Fri 2026-02-20 07:35:51 AEST`)
- Added repo-tracked change record:
  - `logs/changes/20260219-213551-telegram-ha-off-query-and-climate-turn-on-fix.md`

### Git State
- Current branch: `main`
- Remote: `origin https://github.com/anunkai1/matrix.git`

### Notes
- No live `/etc/default` env changes were required in this change set.

## 2026-02-20 (Telegram HA-Only Chat: Natural Status Queries Enabled)

### Summary
- Investigated HA-only chat rejection for natural read prompts such as `Can you check what's on right now`.
- Root behavior before fix: HA-only routing accepted only control/schedule intents; status-style queries were treated as non-HA and rejected with the HA-only reminder.
- Added dedicated HA status-query detection and handling in bridge runtime:
  - New status-query matcher and active-entity summarizer in `src/telegram_bridge/ha_control.py`.
  - `handle_ha_request_text(...)` now serves read-only HA status responses in `src/telegram_bridge/main.py`.
  - HA-only chats allow implicit status phrasing (for example `what's on right now`).
  - Mixed chats still require explicit HA context for status-query routing to avoid accidental hijack of normal Architect prompts.
- Updated docs to reflect new behavior:
  - `README.md`
  - `docs/telegram-architect-bridge.md`
- Validation:
  - `python3 -m py_compile src/telegram_bridge/ha_control.py src/telegram_bridge/main.py`
  - `bash src/telegram_bridge/smoke_test.sh` (pass)
  - runtime intent check snippet confirmed expected true/false status-query routing behavior
- Rolled out live runtime by restarting `telegram-architect-bridge.service` with verified helper:
  - `bash ops/telegram-bridge/restart_and_verify.sh`
  - service healthy after restart (`active/running`)
- Added repo-tracked change record:
  - `logs/changes/20260219-212038-telegram-ha-status-query-support.md`

### Git State
- Current branch: `main`
- Remote: `origin https://github.com/anunkai1/matrix.git`

### Notes
- No live `/etc/default` env content changes in this change set; rollout required service restart only.

## 2026-02-20 (Telegram Bridge Live Env Recovery While Preserving Strict Routing)

### Summary
- Investigated Telegram outage and confirmed `telegram-architect-bridge.service` was crash-looping on startup with `Configuration error: TELEGRAM_BOT_TOKEN is required`.
- Identified live root cause: `/etc/default/telegram-architect-bridge` had been truncated to only 3 routing keys during an in-place rewrite attempt at `2026-02-19 22:09:30 AEST`.
- Recovered live env from `/etc/default/telegram-architect-bridge.bak-20260219-220930` and preserved strict routing keys:
  - `TELEGRAM_ALLOWED_CHAT_IDS=211761499,-5144577688`
  - `TELEGRAM_ARCHITECT_CHAT_IDS=211761499`
  - `TELEGRAM_HA_CHAT_IDS=-5144577688`
- Restarted bridge service and verified healthy runtime with routing enabled:
  - `ActiveState=active`, `SubState=running`
  - `ExecMainStartTimestamp=Fri 2026-02-20 07:06:40 AEST`
  - Journal confirms `Bridge started` and `Chat routing enabled`.
- Updated repo-tracked redacted env mirror and added change record:
  - `infra/env/telegram-architect-bridge.server3.redacted.env`
  - `logs/changes/20260219-210652-telegram-env-recovery-preserve-routing.md`

### Git State
- Current branch: `main`
- Remote: `origin https://github.com/anunkai1/matrix.git`

### Notes
- No bridge code changes were made in this recovery; fix scope was live env restore + traceability updates.

## 2026-02-19 (Telegram Bridge Strict Chat Routing: Architect-Only vs HA-Only)

### Summary
- Added strict chat-ID based routing support in bridge runtime (`src/telegram_bridge/main.py`) via new optional env keys:
  - `TELEGRAM_ARCHITECT_CHAT_IDS`
  - `TELEGRAM_HA_CHAT_IDS`
- Added startup validation for strict split mode:
  - no overlap between routing sets
  - all routed IDs must be in `TELEGRAM_ALLOWED_CHAT_IDS`
  - all allowlisted IDs must be assigned when split mode is enabled
- Updated message handling behavior:
  - Architect chat IDs bypass HA parser and route to local executor only
  - HA chat IDs run HA handling only; non-HA or media/file requests are rejected with HA-only guidance
  - `APPROVE`/`CANCEL` in Architect-only chats are blocked with routing guidance
- Updated help text to show per-chat mode (`mixed`, `Architect-only`, `HA-only`).
- Updated env/docs references for strict split configuration:
  - `infra/env/telegram-architect-bridge.env.example`
  - `README.md`
  - `docs/telegram-architect-bridge.md`
- Verified with:
  - `python3 -m py_compile src/telegram_bridge/main.py`
  - `bash src/telegram_bridge/smoke_test.sh`

### Git State
- Current branch: `main`
- Remote: `origin https://github.com/anunkai1/matrix.git`

### Notes
- This change set updates repo code/docs only; no live `/etc` runtime config edits were applied in this step.

## 2026-02-19 (Server3 System Timezone Set to Australia/Brisbane)

### Summary
- Updated live system timezone from `Etc/UTC` to `Australia/Brisbane` using `timedatectl`.
- Aligned `/etc/timezone` to `Australia/Brisbane` to match `/etc/localtime`.
- Mirrored live timezone state into repo files:
  - `infra/system/timezone.server3`
  - `infra/system/localtime.server3.symlink`
- Recorded live change details in `logs/changes/20260219-091124-server3-timezone-australia-brisbane.md`.

### Git State
- Current branch: `main`
- Remote: `origin https://github.com/anunkai1/matrix.git`

### Notes
- Final verification shows `Time zone: Australia/Brisbane (AEST, +1000)` with NTP synchronized.
- UTC time remains synchronized; local display/interpretation now follows Brisbane time.

## 2026-02-19 (Daily Surprise Instruction Reverted)

### Summary
- Reverted commit `edb56f5` to fully remove the temporary daily surprise behavior from repo policy/docs.
- Removed `Daily Surprise Mode` guidance from `AGENTS.md`.
- Removed the prior rollout log entry that introduced daily surprise behavior.

### Git State
- Current branch: `main`
- Remote: `origin https://github.com/anunkai1/matrix.git`

### Notes
- This change set is a policy/docs revert only; no live `/etc` or runtime service config edits were applied.

## 2026-02-19 (ESPHome 2026.2.0 Xiaomi BLE Outage: Runtime Recovery Attempt + Permission Boundary)

### Summary
- Investigated user-reported outage after ESPHome add-on update (`2026.1.5` -> `2026.2.0`) and confirmed all Xiaomi `LYWSD03MMC` entities were `unavailable` on a shared timeline.
- Verified BLE proxy path metadata remained present in HA (`esphome`, `bluetooth`, `xiaomi_ble` config entries loaded; proxy host reachable at LAN level with ESPHome API port `6053` open).
- Attempted HA integration reload path (`homeassistant.reload_config_entry` for esphome/bluetooth/xiaomi_ble entries), but calls were blocked by token permission (`home_assistant_error: Unauthorized`).
- Executed ESPHome add-on restart via `hassio.addon_restart` (`5c53de3b_esphome`) and monitored target Xiaomi entities for 6 minutes post-restart.
- Result after restart window: no recovery; all watched Xiaomi temperature entities remained `unavailable`.
- Attempted HA core restart via `homeassistant.restart`; also blocked by token permission (`home_assistant_error: Unauthorized`).
- Recorded live operations and outcomes in `logs/changes/20260219-073900-esphome-xiaomi-ble-recovery-attempt.md`.

### Git State
- Current branch: `main`
- Remote: `origin https://github.com/anunkai1/matrix.git`

### Notes
- This step performed runtime operations only (HA service calls and state checks) with no live config file changes.
- Next required action is an admin-privileged rollback/restart path (for example, roll back ESPHome add-on to `2026.1.5` via Supervisor UI) because current token scope cannot execute HA core/integration reload services.

## 2026-02-18 (HA General Scheduling Runtime: Replace Policy + Brisbane TZ + Complex Confirm)

### Summary
- Added generalized HA scheduling support in bridge runtime (`src/telegram_bridge/ha_control.py`, `src/telegram_bridge/main.py`) for relative and absolute timing, chained steps, and optional timed on-duration auto-off behavior.
- Added persistent HA scheduler state files under bridge state dir: `ha_schedules.json` (queued steps) and `pending_ha_plans.json` (awaiting `APPROVE`/`CANCEL`).
- Added runtime env controls for user-requested defaults: `TELEGRAM_HA_SCHEDULE_POLICY=replace`, `TELEGRAM_HA_TIMEZONE=Australia/Brisbane`, and `TELEGRAM_HA_REQUIRE_CONFIRM_COMPLEX=true` (plus scheduler interval knob).
- Updated help/status behavior to surface HA queue and pending complex confirmations; updated README/runbook/env example docs accordingly.
- Hardened HA trigger path to avoid unnecessary HA network calls for non-HA prompts by requiring a parseable HA intent before fetching HA states.
- Verified with `python3 -m py_compile src/telegram_bridge/ha_control.py src/telegram_bridge/main.py` and `bash src/telegram_bridge/smoke_test.sh`.

### Git State
- Current branch: `main`
- Remote: `origin https://github.com/anunkai1/matrix.git`

### Notes
- This change set updates repo code/docs only; no live `/etc` runtime config edits were applied in this step.

## 2026-02-18 (Live Env: Telegram Max Document Size Raised to 500MB)

### Summary
- Updated live bridge env `/etc/default/telegram-architect-bridge` to set `TELEGRAM_MAX_DOCUMENT_BYTES=524288000` (500MB).
- Confirmed bridge restart occurred with `ExecMainStartTimestamp=Wed 2026-02-18 22:00:02 UTC` and service remained healthy (`active/running`).
- Mirrored live non-secret env key to `infra/env/telegram-architect-bridge.server3.redacted.env`.
- Added execution/change record at `logs/changes/20260218-220706-telegram-max-document-bytes-500mb.md`.

### Git State
- Current branch: `main`
- Remote: `origin https://github.com/anunkai1/matrix.git`

### Notes
- This change set includes live `/etc` state traceability (mirror + log) and repo updates in the same session.

## 2026-02-18 (Telegram Generic File Analysis Support Added)

### Summary
- Added Telegram `document` message handling to `src/telegram_bridge/main.py` so generic files can be sent for analysis.
- Added bounded file download path with temp-file lifecycle and cleanup; file size is enforced via new env key `TELEGRAM_MAX_DOCUMENT_BYTES` (default `52428800`).
- Added prompt context injection for file analysis (`local path`, `filename`, `mime`, `size`) so Codex can analyze attached files directly from disk.
- Updated bridge help text and self-test to include/validate document parsing behavior.
- Updated runtime docs and env example (`README.md`, `docs/telegram-architect-bridge.md`, `infra/env/telegram-architect-bridge.env.example`) for the new file-analysis mode.
- Verified `python3 -m py_compile src/telegram_bridge/main.py` and `bash src/telegram_bridge/smoke_test.sh` both pass.

### Git State
- Current branch: `main`
- Remote: `origin https://github.com/anunkai1/matrix.git`

### Notes
- This change set updates repo code/docs only; no live `/etc` or runtime config edits were applied.

## 2026-02-18 (Bridge Dead HA Parser Runtime Paths Removed)

### Summary
- Removed unused in-bridge HA parser runtime paths from `src/telegram_bridge/main.py` after Codex-only routing rollout.
- Deleted dead `handle_ha_control_text(...)` handler and removed pending-approval state model/loading code (`pending_actions.json`) from bridge runtime state.
- Simplified status output by removing non-functional `Pending HA approvals` metric.
- Removed parser-specific self-test checks from bridge self-test path so `--self-test` now validates active runtime behavior only.
- Updated runbook context-persistence section to drop stale pending-approval state file reference.

### Git State
- Current branch: `main`
- Remote: `origin https://github.com/anunkai1/matrix.git`

### Notes
- This change set updates repo code/docs only; no live `/etc` or runtime config edits were applied.

## 2026-02-18 (Bridge Runtime Routed Fully Through Codex Executor)

### Summary
- Updated Telegram bridge runtime to bypass in-bridge HA parser routing for incoming messages.
- Removed runtime message-worker branch that invoked `looks_like_ha_control_text(...)` and `handle_ha_control_text(...)`; text/voice/photo prompts now all follow the same Codex executor path.
- Updated `/help` output in runtime to remove `APPROVE` / `CANCEL` confirmation guidance.
- Updated README and Telegram bridge runbook text to reflect that runtime no longer uses the in-bridge `APPROVE` parser flow.
- Kept legacy HA parser assets/functions in repo for reference, but they are not on the active runtime message path.

### Git State
- Current branch: `main`
- Remote: `origin https://github.com/anunkai1/matrix.git`

### Notes
- This change set updates repo code/docs only; no live `/etc` or runtime config edits were applied.

## 2026-02-18 (Telegram Voice GPU Runtime Enablement + CUDA Fallback)

### Summary
- Installed NVIDIA driver/runtime stack on Server3 (`nvidia-driver-590-open`) and completed reboot activation.
- Installed required CUDA BLAS runtime libs for faster-whisper (`libcublas12`, `libcublaslt12`).
- Updated live `/etc/default/telegram-architect-bridge` voice runtime to `TELEGRAM_VOICE_WHISPER_DEVICE=cuda` and `TELEGRAM_VOICE_WHISPER_COMPUTE_TYPE=float16`, with explicit CPU fallback keys.
- Added voice transcriber CUDA fallback logic in `src/telegram_bridge/voice_transcribe.py`: if CUDA init/transcription fails, retry on configured fallback device/compute type.
- Updated docs/env examples for fallback keys and mirrored live non-secret voice env keys to `infra/env/telegram-architect-bridge.server3.redacted.env`.
- Recorded live execution details in `logs/changes/20260218-134120-telegram-voice-gpu-runtime-enable.md`.

### Git State
- Current branch: `main`
- Remote: `origin https://github.com/anunkai1/matrix.git`

### Notes
- Post-reboot runtime verification shows `nvidia-smi` active with GTX 1650 and driver `590.48.01`.
- Local benchmark on a 20s silence sample measured CPU `0:01.51` vs CUDA `0:01.62` (silence sample is not representative of real speech complexity).

## 2026-02-18 (Telegram Restart Interruption Detection Added)

### Summary
- Added persisted in-flight request tracking in `src/telegram_bridge/main.py` using state file `in_flight_requests.json` under `TELEGRAM_BRIDGE_STATE_DIR`.
- Bridge now records in-flight chat work when a request starts and clears it on normal finalize paths.
- On startup, any leftover in-flight markers are treated as interrupted work from prior runtime; affected allowlisted chats get a one-time notice to resend.
- Existing safe `/restart` queue semantics, chat-thread persistence, and HA pending-action persistence were kept unchanged.
- Updated README and runbook docs to document restart interruption notices and in-flight state path.

### Git State
- Current branch: `main`
- Remote: `origin https://github.com/anunkai1/matrix.git`

### Notes
- This change set updates repo code/docs only; no live `/etc` or runtime config edits were applied.

## 2026-02-18 (Voice Transcript Echo in Telegram Chat)

### Summary
- Updated Telegram bridge voice flow to echo the recognized transcript back to chat after successful transcription.
- Transcript echo is non-blocking: if the echo send fails, normal prompt execution still continues.
- Kept existing processing unchanged: same transcript text is still used as the Architect prompt input (with caption-prefix behavior unchanged).
- Updated bridge/README docs to reflect transcript echo behavior.
- Verified compile and bridge self-test pass.

### Git State
- Current branch: `main`
- Remote: `origin https://github.com/anunkai1/matrix.git`

### Notes
- This change set updates repo code/docs only; no live `/etc` or runtime config edits were applied.

## 2026-02-18 (Telegram Group Allowlist Added + Runtime Verified)

### Summary
- Added new Telegram group chat ID `-5144577688` to live bridge allowlist in `/etc/default/telegram-architect-bridge`.
- Live allowlist is now `TELEGRAM_ALLOWED_CHAT_IDS=211761499,-5144577688`.
- Verified bridge runtime is healthy after restart with `ExecMainStartTimestamp=Wed 2026-02-18 11:55:51 UTC`, `MainPID=154347`, and active running state.
- Updated repo-tracked live env mirror and execution record for this allowlist change.

### Git State
- Current branch: `main`
- Remote: `origin https://github.com/anunkai1/matrix.git`

### Notes
- Last denied log for the group was before this change (`2026-02-18 11:42:59`).
- Final operator validation is sending `/status` from the group and confirming no access-denied response.

## 2026-02-18 (Bridge Hardening: 10h Default + Async HA + Restart Verification Path)

### Summary
- Updated bridge runtime default executor timeout to 10 hours (`TELEGRAM_EXEC_TIMEOUT_SECONDS=36000`) in code and aligned runbook manual env example to the same value.
- Switched in-bridge `/restart` execution path and failure guidance to the verified helper `ops/telegram-bridge/restart_and_verify.sh`.
- Added async message-worker flow so HA planning/execution runs off the main Telegram polling loop; slow HA API calls no longer block polling for other chats.
- Added startup resilience for state files: if `chat_threads.json` or `pending_actions.json` is malformed, the bridge now quarantines the corrupt file and continues with empty in-memory state.
- Improved HA fuzzy entity matching to score only allowed candidates (`TELEGRAM_HA_ALLOWED_DOMAINS` / `TELEGRAM_HA_ALLOWED_ENTITIES`) before selecting the top match.
- Updated bridge docs to explicitly document worker-thread HA processing behavior.
- Verified compile and smoke/self-test pass after changes.

### Git State
- Current branch: `main`
- Remote: `origin https://github.com/anunkai1/matrix.git`

### Notes
- This change set updates repo code/docs only; no live `/etc` or runtime config edits were applied.

## 2026-02-18 (Final Live-Edit Scope Clarification for HA Quick-Ops)

### Summary
- Updated one remaining ambiguous line in `ARCHITECT_INSTRUCTION.md` from `NO live edits outside the repo ...` to `NO non-exempt live edits outside the repo ...`.
- This makes the live-edit restriction explicitly consistent with the HA quick-ops exemption model.

### Git State
- Current branch: `main`
- Remote: `origin https://github.com/anunkai1/matrix.git`

### Notes
- This change set updates policy/docs only; no live `/etc` or runtime config edits were applied.

## 2026-02-18 (Traceability Heading Clarified for HA Quick-Ops Exemption)

### Summary
- Updated `ARCHITECT_INSTRUCTION.md` traceability section heading/scope wording to explicitly state it applies to non-exempt server changes.
- Added explicit wording that routine HA quick-ops are excluded from that traceability block and governed by the exemption section.

### Git State
- Current branch: `main`
- Remote: `origin https://github.com/anunkai1/matrix.git`

### Notes
- This change set updates policy/docs only; no live `/etc` or runtime config edits were applied.

## 2026-02-18 (Final Policy Wording Alignment for HA Quick-Ops)

### Summary
- Updated the remaining absolute wording in `ARCHITECT_INSTRUCTION.md` so non-exempt scope is explicit.
- Changed the top-level change-control line from `All changes MUST follow ...` to `All non-exempt changes MUST follow ...`.
- Changed working-rules wording from unconditional commit/push to `For non-exempt changes, Codex commits and pushes directly to origin/main`.

### Git State
- Current branch: `main`
- Remote: `origin https://github.com/anunkai1/matrix.git`

### Notes
- This change set updates policy/docs only; no live `/etc` or runtime config edits were applied.

## 2026-02-18 (Policy Consistency Cleanup for HA Quick-Ops Exemption)

### Summary
- Aligned remaining conflicting language in `ARCHITECT_INSTRUCTION.md` so session-end and required git sequence rules explicitly apply to non-exempt changes only.
- Added explicit note that routine HA quick-ops do not require repo file updates/commit/push.
- Updated README change-control and progress-tracking wording to match the same non-exempt vs quick-ops boundary.

### Git State
- Current branch: `main`
- Remote: `origin https://github.com/anunkai1/matrix.git`

### Notes
- This change set updates policy/docs only; no live `/etc` or runtime config edits were applied.

## 2026-02-18 (Instruction Docs De-duplication + Consistency Fix)

### Summary
- Removed duplicated traceability clauses from `AGENTS.md` (instructions 3-5) so policy authority remains centralized in `ARCHITECT_INSTRUCTION.md`.
- Updated `ARCHITECT_INSTRUCTION.md` role section to explicitly defer commit/push completion requirements to the `HA QUICK-OPS EXCEPTION` for routine HA operations.
- Kept non-exempt change-control and proof requirements unchanged.

### Git State
- Current branch: `main`
- Remote: `origin https://github.com/anunkai1/matrix.git`

### Notes
- This change set updates policy/docs only; no live `/etc` or runtime config edits were applied.

## 2026-02-18 (Policy Update: HA Quick-Ops Exemption Added)

### Summary
- Updated `ARCHITECT_INSTRUCTION.md` with a new `HA QUICK-OPS EXCEPTION` policy.
- Defined that routine HA entity state operations (for example turn on/off, climate mode/temperature set) are exempt from per-action repo logging/commit/push requirements.
- Added strict boundary that all persistent changes (repo code/docs/policy, `/etc`, HA packages/automations, infra/ops/docs/logs updates) still require full traceability and same-session commit/push.
- Added a concise README change-control note pointing to `ARCHITECT_INSTRUCTION.md` for the exemption boundary.

### Git State
- Current branch: `main`
- Remote: `origin https://github.com/anunkai1/matrix.git`

### Notes
- This change set updates policy/docs only; no live `/etc` or runtime config edits were applied.

## 2026-02-18 (Live HA Action Executed: Master AC 23C)

### Summary
- Executed requested live HA action via bridge planner/executor path: set Master AC to 23C.
- Original phrase included `air contamination`; planner did not confidently resolve that target, so execution used normalized wording (`aircon`) to match intended device.
- Planner resolved target as `climate.master_brm_aircon`, action executed successfully, and post-check confirmed `temperature=23` with state `cool`.
- Added repo-tracked execution record `logs/changes/20260218-090921-ha-live-action-masters-ac-23c.md`.

### Git State
- Current branch: `main`
- Remote: `origin https://github.com/anunkai1/matrix.git`

### Notes
- This is an operational HA state change only; no `/etc` configuration values were modified.

## 2026-02-18 (Live HA Action Executed: Master AC 25C)

### Summary
- Executed requested live HA action using the bridge HA planner/executor path: set Master AC to 25C.
- Planner resolved target as `climate.master_brm_aircon`.
- Verified post-action state as `cool` with `temperature=25`.
- Added repo-tracked execution record `logs/changes/20260218-090553-ha-live-action-masters-ac-25c.md`.

### Git State
- Current branch: `main`
- Remote: `origin https://github.com/anunkai1/matrix.git`

### Notes
- This is an operational HA state change only; no `/etc` configuration values were modified.

## 2026-02-18 (HA Lead-In Filler Stripping + Implied Climate Intent)

### Summary
- Updated HA intent parsing in `src/telegram_bridge/ha_control.py` to ignore filler lead-ins (for example `to your normal ...`) before intent extraction.
- Added implied climate-intent handling when a phrase includes AC target plus mode/temperature without explicit `turn on`/`set`.
- Added parser self-test coverage for `To your normal masters I see on cool mode 23`.
- Verified compile, bridge self-test, and smoke test all pass.

### Git State
- Current branch: `main`
- Remote: `origin https://github.com/anunkai1/matrix.git`

### Notes
- This change set updates repo code/docs only; no live `/etc` edits were applied.

## 2026-02-18 (HA Mode Typo Normalization: `hit` -> `heat`)

### Summary
- Updated HA interpreter token normalization in `src/telegram_bridge/ha_control.py` to map `hit` to `heat` for voice/typo resilience.
- Added regression self-test coverage for `Turn on Master's AC to hit mode 23`.
- Verified compile, bridge self-test, and smoke-test all pass.

### Git State
- Current branch: `main`
- Remote: `origin https://github.com/anunkai1/matrix.git`

### Notes
- This change set updates repo code/docs only; no live `/etc` edits were applied.

## 2026-02-18 (HA Speech Variant Parsing Improvement)

### Summary
- Improved HA natural-language parser normalization for speech-transcription variants in `src/telegram_bridge/ha_control.py`.
- Added support mapping `i see` to `aircon` and `cooling`/`heating` wording to HVAC modes (`cool`/`heat`).
- Added parser self-test coverage for the phrase `Set masters I see to 23 degrees cooling and turn it on`.
- Verified parser and bridge checks pass (`--self-test` and smoke test).

### Git State
- Current branch: `main`
- Remote: `origin https://github.com/anunkai1/matrix.git`

### Notes
- This change set updates repo code/docs only; no live `/etc` edits were applied.

## 2026-02-18 (Telegram Bridge Restart on Request, Post-HA Interpreter Rollout)

### Summary
- Restarted live `telegram-architect-bridge.service` on request so the new HA asset-aware interpreter is active in runtime.
- Verified service health post-restart with runtime start timestamp `2026-02-18 06:57:02 UTC` and active `MainPID=139203`.
- Added repo-tracked execution record `logs/changes/20260218-065702-telegram-bridge-restart-on-request.md`.

### Git State
- Current branch: `main`
- Remote: `origin https://github.com/anunkai1/matrix.git`

### Notes
- This change set is operational only; no live `/etc` configuration values were modified.

## 2026-02-18 (HA Regex Parser Removed, Asset-Aware Interpreter Added)

### Summary
- Replaced HA regex intent parsing in `src/telegram_bridge/ha_control.py` with a new asset-aware natural-language interpreter.
- Added fuzzy entity resolution against live HA assets (states + friendly labels) with confidence and ambiguity gates.
- Kept confirm-first flow unchanged (`APPROVE` / `CANCEL`) and preserved existing execution/service-call path after approval.
- Added optional HA match tuning env vars: `TELEGRAM_HA_MATCH_MIN_SCORE` and `TELEGRAM_HA_MATCH_AMBIGUITY_GAP`.
- Added parser self-test coverage in bridge self-test path and updated README/runbook/env docs for the new logic.

### Git State
- Current branch: `main`
- Remote: `origin https://github.com/anunkai1/matrix.git`

### Notes
- This change set updates repo code/docs only; no live `/etc` edits were applied.

## 2026-02-18 (Telegram Bridge Restart via Verified Helper on Request)

### Summary
- Executed live bridge restart using the new verified helper `ops/telegram-bridge/restart_and_verify.sh`.
- Confirmed restart occurred at `2026-02-18 06:08:20 UTC` via `systemctl` start timestamp and journal startup entries.
- Added repo-tracked execution record `logs/changes/20260218-060820-telegram-bridge-restart-and-verify-on-request.md`.

### Git State
- Current branch: `main`
- Remote: `origin https://github.com/anunkai1/matrix.git`

### Notes
- This change set is an operational restart only; no live env/config values were modified.

## 2026-02-18 (Verified Restart Helper Added)

### Summary
- Added `ops/telegram-bridge/restart_and_verify.sh` to enforce restart verification using pre/post `systemd` markers (`MainPID`, start timestamp monotonic) plus active running-state checks.
- Updated Telegram bridge runbook and README restart examples to use the verified helper as the primary restart path.
- Kept existing `ops/telegram-bridge/restart_service.sh` for simple restart usage; new helper is the recommended deterministic option.

### Git State
- Current branch: `main`
- Remote: `origin https://github.com/anunkai1/matrix.git`

### Notes
- This change set updates repo code/docs only; no live `/etc` edits were applied.

## 2026-02-18 (Telegram Bridge Restart on Request)

### Summary
- Restarted live `telegram-architect-bridge.service` on operator request.
- Verified service health post-restart with active runtime start timestamp `2026-02-18 05:48:20 UTC`.
- Added repo-tracked execution record `logs/changes/20260218-054820-telegram-bridge-restart-on-request.md`.

### Git State
- Current branch: `main`
- Remote: `origin https://github.com/anunkai1/matrix.git`

### Notes
- This change set is an operational restart only; no live env/config values were modified.

## 2026-02-18 (Thinking Prompt Single-Line Format)

### Summary
- Updated Telegram bridge default thinking placeholder to a single-line prompt with inline help hint.
- Changed `thinking_message` from two lines to: `💭🤔💭.....thinking.....💭🤔💭 (/h)`.
- Updated bridge runbook documentation to match the new prompt format.

### Git State
- Current branch: `main`
- Remote: `origin https://github.com/anunkai1/matrix.git`

### Notes
- This change set updates repo code/docs only; no live `/etc` edits were applied.

## 2026-02-18 (Live HA Approval TTL Reduced to 7 Minutes)

### Summary
- Applied live edit in `/etc/default/telegram-architect-bridge` to reduce HA approval expiry from 1 hour to 7 minutes.
- Updated `TELEGRAM_HA_APPROVAL_TTL_SECONDS` from `3600` to `420`.
- Verified the running `telegram-architect-bridge.service` process environment is using `TELEGRAM_HA_APPROVAL_TTL_SECONDS=420`.
- Updated repo-tracked redacted mirror and added execution log `logs/changes/20260218-044404-telegram-ha-approval-ttl-7m.md`.

### Git State
- Current branch: `main`
- Remote: `origin https://github.com/anunkai1/matrix.git`

### Notes
- This was a live `/etc` change and has been mirrored/documented in-repo in the same session.

## 2026-02-18 (Telegram /h Help Alias + Thinking Hint)

### Summary
- Added `/h` as a short alias for `/help` in Telegram bridge command handling.
- Updated help output to include `/h` in the command list.
- Updated the thinking placeholder reply to include `Type /h for commands.` after each request acknowledgement.
- Updated README and bridge runbook documentation for the new command alias/hint behavior.

### Git State
- Current branch: `main`
- Remote: `origin https://github.com/anunkai1/matrix.git`

### Notes
- This change set updates repo code/docs only; no live `/etc` edits were applied in this task.

## 2026-02-18 (Telegram Safe Queued Restart Command)

### Summary
- Added a built-in Telegram `/restart` command to the bridge command set.
- Implemented safe restart behavior: restart requests are accepted even when chat work is busy, queued in-memory, and automatically executed after active work completes.
- Added restart-state visibility in `/status` output (`Restart queued`, `Restart in progress`).
- Added self-test coverage for restart state transitions and updated docs/README command references.

### Git State
- Current branch: `main`
- Remote: `origin https://github.com/anunkai1/matrix.git`

### Notes
- This change set updates repo code/docs only; no live `/etc` edits were applied in this task.
- In-flight work is preserved by deferring restart until current active request(s) complete.

## 2026-02-18 (Telegram HA Natural Language + Code-Free Approval)

### Summary
- Relaxed Telegram HA command parsing to accept more natural phrasing while preserving existing strict command compatibility.
- Added support for common conversational variants (for example polite prefixes, `switch on/off`, `set ... to <temp>`, optional `degrees` unit, and `in/on <mode> mode`).
- Removed code-based HA confirmation requirement; pending actions are now confirmed with plain `APPROVE` and cancelled with plain `CANCEL`.
- Updated bridge help text and docs to reflect code-free approval and natural-language intent support.

### Git State
- Current branch: `main`
- Remote: `origin https://github.com/anunkai1/matrix.git`

### Notes
- Pending HA actions remain per-chat and still expire based on `TELEGRAM_HA_APPROVAL_TTL_SECONDS`.
- This change set updates repo code/docs only; no live `/etc` changes were applied.

## 2026-02-18 (Telegram HA E2E Validation Success)

### Summary
- Verified end-to-end Telegram confirm-first Home Assistant control path is working on live runtime.
- Confirmed bridge service is active after HA env activation and startup logs show HA integration enabled.
- Owner-confirmed successful execution flow: `turn off climate.living_rm_aircon` with approval reply `APPROVE <code>`.
- Added repo-tracked validation record: `logs/changes/20260218-004111-telegram-ha-e2e-validation-success.md`.

### Git State
- Current branch: `main`
- Remote: `origin https://github.com/anunkai1/matrix.git`

### Notes
- Known behavior: climate commands without explicit HVAC mode may only set temperature; explicit mode phrasing (for example `on cool mode`) remains recommended until fallback-mode enhancement is added.

## 2026-02-18 (Live HA Env Config Applied, Restart Deferred)

### Summary
- Applied live Home Assistant integration environment values in `/etc/default/telegram-architect-bridge` for Telegram confirm-first control.
- Configured HA base URL, token (live only), 1-hour approval TTL, temperature limits, broad allowed domains, solar sensor, and 2000W excess threshold.
- Intentionally left `TELEGRAM_HA_ALLOWED_ENTITIES` blank per owner request (domain-wide allow).
- Created repo-tracked redacted mirror of live HA env keys at `infra/env/telegram-architect-bridge.server3.redacted.env`.
- Added live-change execution record `logs/changes/20260218-001104-telegram-ha-live-env-config-no-restart.md`.
- Per owner request, did **not** restart `telegram-architect-bridge.service` in this change set.

### Git State
- Current branch: `main`
- Remote: `origin https://github.com/anunkai1/matrix.git`

### Notes
- Integration values are in place but inactive until service restart.
- Next operator step is explicit restart + runtime validation from Telegram.

## 2026-02-17 (Telegram Input Limit Default Raised to 4096)

### Summary
- Increased Telegram bridge default input-character limit from `4000` to `4096` in runtime config loading (`src/telegram_bridge/main.py`).
- Updated env mirror default in `infra/env/telegram-architect-bridge.env.example` to `TELEGRAM_MAX_INPUT_CHARS=4096`.
- Updated bridge runbook example in `docs/telegram-architect-bridge.md` to match the new default.

### Git State
- Current branch: `main`
- Remote: `origin https://github.com/anunkai1/matrix.git`

### Notes
- This is a repo/code default update; live service picks it up after restart if no lower override exists in `/etc/default/telegram-architect-bridge`.
- Hard Telegram text-message ceiling is still `4096` characters.

## 2026-02-17 (Telegram Confirm-First Home Assistant Executor Added)

### Summary
- Added Home Assistant control integration to Telegram bridge with explicit in-chat approval flow (`APPROVE <code>` / `CANCEL <code>`).
- Added persistent pending-approval state storage (`pending_actions.json`) so approval windows survive bridge restarts.
- Implemented HA intent parsing + execution path for:
  - climate set with optional delayed follow-up schedule
  - generic entity on/off
  - conditional water-heater/off style action based on solar-export threshold
- Added HA package template `infra/home_assistant/packages/architect_executor.yaml` for restart-safe delayed climate follow-up execution and post-run cleanup reset.
- Added HA package validator helper `ops/home-assistant/validate_architect_package.sh`.
- Updated env template, README, bridge runbook docs, and smoke test to cover HA executor setup and validation.

### Git State
- Current branch: `main`
- Remote: `origin https://github.com/anunkai1/matrix.git`

### Notes
- No live `/etc/default/telegram-architect-bridge` or Home Assistant runtime changes were applied in this change set.
- Next step is user-side HA deployment: install package under HA `/config/packages`, set live `TELEGRAM_HA_*` env vars, restart bridge service, then run Telegram approval-path tests.

## 2026-02-17 (Private Local Workspace Path Added)

### Summary
- Added a repo-safe private workspace pattern for local-only personal files.
- Updated `.gitignore` to ignore everything under `private/` while allowlisting `private/README.md` and `private/.gitkeep`.
- Added tracked placeholder files under `private/` to document usage without storing personal content.

### Git State
- Current branch: `main`
- Remote: `origin https://github.com/anunkai1/matrix.git`

### Notes
- New files like `private/profile.md` now remain local and untracked by default.
- If any private file was committed before this change, it is still present in Git history unless explicitly removed.

## 2026-02-17 (Telegram Voice Production User-Path Validation Success)

### Summary
- Recorded final production validation for Telegram voice messaging after owner-confirmed real Telegram voice-note test success.
- Verified bridge runtime is healthy during validation (`telegram-architect-bridge.service` active since `2026-02-17 06:44:39 UTC`, main PID `94913`).
- Verified post-restart journal evidence contains live voice transcription executions via `ops/telegram-voice/transcribe_voice.sh`.
- Added repo-tracked verification record: `logs/changes/20260217-082514-telegram-voice-production-validation-success.md`.
- No additional live config or code changes were required for this completion step.

### Git State
- Current branch: `main`
- Remote: `origin https://github.com/anunkai1/matrix.git`

### Notes
- Voice path validation is now complete for real Telegram usage, not only local wrapper testing.
- Ongoing task is routine monitoring for future runtime regressions.

## 2026-02-17 (Telegram Bridge Timeout Increased to 10 Hours)

### Summary
- Increased live `telegram-architect-bridge.service` executor timeout from `300` seconds to `36000` seconds (10 hours) in `/etc/default/telegram-architect-bridge`.
- Restarted service and verified it is `active (running)` with updated runtime start timestamp `2026-02-17 06:41:59 UTC`.
- Confirmed running process environment includes `TELEGRAM_EXEC_TIMEOUT_SECONDS=36000`.
- Added repo-tracked live-change execution record: `logs/changes/20260217-064151-telegram-bridge-timeout-10h.md`.
- Updated infra env mirror default timeout in `infra/env/telegram-architect-bridge.env.example`.

### Git State
- Current branch: `main`
- Remote: `origin https://github.com/anunkai1/matrix.git`

### Notes
- This change reduces timeout-triggered Telegram failures for long operations.
- Risk/tradeoff: long-running requests can keep a chat busy for significantly longer before timeout.

## 2026-02-17 (Telegram Voice Transcription Live Enablement Verified)

### Summary
- Completed end-to-end voice-transcription rollout path on Server3 using repo-managed scripts in `ops/telegram-voice/`.
- Re-applied live env settings in `/etc/default/telegram-architect-bridge` for `TELEGRAM_VOICE_TRANSCRIBE_CMD`, timeout, and Whisper runtime variables.
- Re-ran runtime installer verification (`ffmpeg`, venv, `faster-whisper`) and restarted `telegram-architect-bridge.service`.
- Verified active runtime start timestamp `2026-02-17 06:38:24 UTC` and confirmed voice env vars are loaded inside the running service process.
- Executed a functional transcription test through the production wrapper `ops/telegram-voice/transcribe_voice.sh` using generated sample speech audio; transcript output returned successfully.
- Added repo-tracked live-change execution record: `logs/changes/20260217-063854-telegram-voice-live-enable.md`.

### Git State
- Current branch: `main`
- Remote: `origin https://github.com/anunkai1/matrix.git`

### Notes
- Voice pipeline is now configured and active; remaining user-path confirmation is to send a real Telegram voice note and verify the bridge responds with transcribed content instead of the configuration warning.

## 2026-02-17 (Telegram Bridge Restart on Request)

### Summary
- Restarted live `telegram-architect-bridge.service` using repo helper script.
- Verified service health after restart; runtime is active with new start timestamp `2026-02-17 06:13:04 UTC`.
- Added repo-tracked live-change execution record: `logs/changes/20260217-061422-telegram-bridge-restart-on-request.md`.

### Git State
- Current branch: `main`
- Remote: `origin https://github.com/anunkai1/matrix.git`

### Notes
- No code logic changes were made in this change set; this was an operational restart/verification task.

## 2026-02-17 (Telegram Voice Snippet Support via Configurable Transcription Command)

### Summary
- Added Telegram voice-message support to the bridge runtime using the same media lifecycle pattern as photo support (detect, download with size guard, process, cleanup).
- Added configurable voice transcription command support (`TELEGRAM_VOICE_TRANSCRIBE_CMD`) with optional `{file}` placeholder replacement and timeout guard (`TELEGRAM_VOICE_TRANSCRIBE_TIMEOUT_SECONDS`).
- Updated bridge docs, README status/troubleshooting notes, and env template with new voice-related configuration and limits (`TELEGRAM_MAX_VOICE_BYTES`).

### Git State
- Current branch: `main`
- Remote: `origin https://github.com/anunkai1/matrix.git`

### Notes
- Voice transcription backend is intentionally externalized; the command must output transcript text to stdout.
- This change set updates repo code/docs only; live service restart is required on Server3 for runtime activation.

## 2026-02-17 (Telegram Context Preserve on Resume Failure + Live Restart)

### Summary
- Updated Telegram bridge resume-failure handling so saved thread context is preserved for transient executor errors.
- Limited automatic context reset/retry-as-new to failures that clearly indicate invalid/missing thread state.
- Restarted `telegram-architect-bridge.service` to activate latest bridge code and verified startup backlog-drop log entry.
- Added repo-tracked live-change execution record: `logs/changes/20260217-055323-telegram-bridge-context-preserve-restart.md`.

### Git State
- Current branch: `main`
- Remote: `origin https://github.com/anunkai1/matrix.git`

### Notes
- This closes a context-loss path where resume failures could silently force a new conversation.
- Existing `/reset` behavior and multi-chat concurrency model remain unchanged.

## 2026-02-17 (Telegram Startup Backlog Drop + New Session Approval Bypass)

### Summary
- Updated bridge startup behavior to discard queued Telegram updates before entering the main polling loop, preventing stale backlog replay after restarts.
- Updated executor behavior so new sessions now also run with `--dangerously-bypass-approvals-and-sandbox`, matching resumed-session approval mode.
- Updated Telegram bridge runbook documentation to reflect both behaviors.

### Git State
- Current branch: `main`
- Remote: `origin https://github.com/anunkai1/matrix.git`

### Notes
- Multi-chat concurrency model was intentionally left unchanged.
- No live paths outside the repo were modified in this change set.

## 2026-02-17 (Telegram Privileged Ops Enabled)

### Summary
- Removed the bridge unit privilege-escalation block by setting `NoNewPrivileges=false` in `infra/systemd/telegram-architect-bridge.service`.
- Updated service helper scripts `ops/telegram-bridge/restart_service.sh` and `ops/telegram-bridge/status_service.sh` to use non-interactive privileged execution (`sudo -n`) for Telegram-safe command paths.
- Applied updated unit to live `/etc/systemd/system/telegram-architect-bridge.service`, restarted the service, and verified runtime now has `NoNewPrivs: 0`.
- Added repo-tracked live-change execution record: `logs/changes/20260217-043641-telegram-bridge-privilege-escalation-enabled.md`.

### Git State
- Current branch: `main`
- Remote: `origin https://github.com/anunkai1/matrix.git`

### Notes
- Telegram-triggered Architect sessions can now execute sudo-capable scripts if requested.
- Security tradeoff: keep `TELEGRAM_ALLOWED_CHAT_IDS` strict because allowed chats now have a path to privileged operations.

## 2026-02-17 (Photo Support Live Rollout Success)

### Summary
- Verified manual restart was successfully applied for `telegram-architect-bridge.service`.
- Confirmed service is `active` with updated runtime start timestamp `2026-02-17 04:28:39 UTC`.
- Added repo-tracked live-change record: `logs/changes/20260217-043009-telegram-photo-support-live-rollout-success.md`.

### Git State
- Current branch: `main`
- Remote: `origin https://github.com/anunkai1/matrix.git`

### Notes
- This closes the prior blocked-restart attempts from this Codex runtime environment.
- Latest Telegram photo-support code is now live on Server3 runtime.

## 2026-02-17 (Photo Support Restart Retry Blocked)

### Summary
- Retried live restart commands for `telegram-architect-bridge.service` to activate the latest Telegram photo-support code.
- `ops/telegram-bridge/restart_service.sh` failed again because `sudo` is blocked by `no new privileges` in this Codex runtime.
- Direct `systemctl restart telegram-architect-bridge.service` failed again with `Interactive authentication required`.
- Added repo-tracked execution record: `logs/changes/20260217-042630-telegram-photo-support-restart-retry-blocked.md`.

### Git State
- Current branch: `main`
- Remote: `origin https://github.com/anunkai1/matrix.git`

### Notes
- Service remains `active`, but start timestamp is still `2026-02-17 03:46:13 UTC` (no restart applied).
- Manual restart from a shell with sudo/polkit access is still required.

## 2026-02-17 (Photo Support Live Rollout Attempt Blocked)

### Summary
- Attempted to roll out latest Telegram photo-support commit to live runtime by restarting `telegram-architect-bridge.service`.
- Restart via repo helper `ops/telegram-bridge/restart_service.sh` failed in this Codex execution context because `sudo` is blocked by `no new privileges`.
- Direct non-sudo `systemctl restart` also failed with `Interactive authentication required`.
- Added repo-tracked execution record: `logs/changes/20260217-042340-telegram-photo-support-rollout-blocked-no-new-privileges.md`.

### Git State
- Current branch: `main`
- Remote: `origin https://github.com/anunkai1/matrix.git`

### Notes
- Service remained active but was not restarted; start timestamp stayed `2026-02-17 03:46:13 UTC`.
- Manual apply is required from a shell with functional sudo/polkit: `bash /home/architect/matrix/ops/telegram-bridge/restart_service.sh`.

## 2026-02-17 (Telegram Photo Input Support)

### Summary
- Added Telegram photo-message support to the bridge runtime so photo updates are no longer ignored.
- Implemented photo file resolution/download via Telegram `getFile` + `/file/bot...` endpoint and temporary local file handling with cleanup.
- Extended executor integration to pass image attachments to Codex (`codex exec --image`) for both new and resumed chats.
- Added configurable image-size limit support (`TELEGRAM_MAX_IMAGE_BYTES`, default `10485760`) and documented behavior in README/runbook/env example.

### Git State
- Current branch: `main`
- Remote: `origin https://github.com/anunkai1/matrix.git`

### Notes
- Photo without caption uses default prompt: `Please analyze this image.`
- This change set updates repo code/docs only; live service restart is required on Server3 for runtime activation.

## 2026-02-17 (Telegram Bridge Service Recovery)

### Summary
- Investigated Telegram non-response window and confirmed the bridge process had stopped cleanly (`inactive/dead`) at `2026-02-17 03:38:35 UTC`.
- Restarted `telegram-architect-bridge.service` using repo helper `ops/telegram-bridge/restart_service.sh`.
- Verified recovery: service is `active (running)` from `2026-02-17 03:46:13 UTC`, with startup logs showing expected executor and thread-state load.
- Added repo-tracked live-action record: `logs/changes/20260217-034636-telegram-bridge-service-restart-recovery.md`.

### Git State
- Current branch: `main`
- Remote: `origin https://github.com/anunkai1/matrix.git`

### Notes
- Unit policy remains `Restart=on-failure`; clean stops do not auto-restart, so an explicit restart is required after a manual/clean termination.

## 2026-02-17 (Telegram Thinking Ack)

### Summary
- Updated Telegram bridge prompt flow to send an immediate placeholder reply for accepted non-command messages: `💭🤔💭.....thinking.....💭🤔💭`.
- Added busy-lock safety handling so a failed placeholder send clears the chat busy state instead of leaving it stuck.
- Updated `docs/telegram-architect-bridge.md` to document the new immediate acknowledgment behavior.

### Git State
- Current branch: `main`
- Remote: `origin https://github.com/anunkai1/matrix.git`

### Notes
- Final Architect output still arrives as a separate follow-up reply after executor completion.
- Live service restart from this session environment is blocked by `sudo` `no new privileges`; apply via `bash ops/telegram-bridge/restart_service.sh` on Server3 shell with sudo capability.

## 2026-02-17 (README Matrix Emoji Refresh)

### Summary
- Added more Matrix-themed emojis to the first heading line in `README.md`.
- Kept all other README content unchanged.
- No live paths outside the repo were modified in this change set.

### Git State
- Current branch: `main`
- Remote: `origin https://github.com/anunkai1/matrix.git`

### Notes
- This was a presentation-only documentation tweak for the README banner line.

## 2026-02-17 (Resume Full Access)

### Summary
- Updated Telegram bridge executor so resumed chats run with full access (`--dangerously-bypass-approvals-and-sandbox`) instead of workspace-write sandbox.
- Validated resume path can resolve GitHub DNS (previously failing in sandboxed resume mode).
- Restarted `telegram-architect-bridge.service` live and confirmed active state after the change.
- Recorded live rollout in `logs/changes/20260217-031656-telegram-resume-full-access-rollout.md`.

### Git State
- Current branch: `main`
- Remote: `origin https://github.com/anunkai1/matrix.git`

### Notes
- This aligns permission behavior between new and resumed Telegram conversations.
- Security impact: resumed Telegram prompts now execute with full-access authority under `architect` user context.

## 2026-02-17 (README Welcome Banner)

### Summary
- Updated the first `README.md` heading to a styled Markdown welcome banner: `Welcome to the Matrix` with emoji.
- Kept the rest of the README content unchanged.
- No live paths outside the repo were modified in this change set.

### Git State
- Current branch: `main`
- Remote: `origin https://github.com/anunkai1/matrix.git`

### Notes
- GitHub network/DNS resolution may still block `git push` from this environment.

## 2026-02-17 (Live Bashrc Launcher Apply Verification)

### Summary
- Confirmed managed launcher block is present in live `/home/architect/.bashrc` with matrix markers.
- Verified shell launcher resolution in interactive bash: both `codex` and `architect` are functions using the full-access default wrapper.
- Added repo-tracked live change record: `logs/changes/20260217-024631-bashrc-codex-default-launcher-apply.md`.

### Git State
- Current branch: `main`
- Remote: `origin https://github.com/anunkai1/matrix.git`

### Notes
- Live apply command remains `bash ops/bash/deploy-bashrc.sh apply` followed by `source ~/.bashrc`.

## 2026-02-17 (Codex Default Launcher)

### Summary
- Updated the managed shell snippet to make `codex` default to full-access launch flags (`-s danger-full-access -a never`).
- Kept `architect` as a convenience wrapper that routes to the same default launcher behavior.
- Updated `docs/server-setup.md` to document verification, default behavior, and how to bypass wrappers with `command codex`.

### Git State
- Current branch: `main`
- Remote: `origin https://github.com/anunkai1/matrix.git`

### Notes
- Live shell profile apply is still performed via `bash ops/bash/deploy-bashrc.sh apply`.
- Current environment may fail GitHub operations due DNS reachability (`github.com` unresolved).

## 2026-02-17 (README Expansion)

### Summary
- Replaced placeholder `README.md` with an operational project guide covering purpose, current status, repository structure, prerequisites, quick start, operations, change control, progress tracking, security notes, troubleshooting, and related runbooks.
- Aligned README instructions with existing repo-tracked scripts and documentation for the Telegram Architect bridge.
- No live paths outside the repo were modified in this change set.

### Git State
- Current branch: `main`
- Remote: `origin https://github.com/anunkai1/matrix.git`

### Notes
- Network/DNS reachability to GitHub may block `git pull`/`git push` from this environment until connectivity is restored.

## 2026-02-17 (Context Persistence)

### Summary
- Implemented persistent per-chat Telegram context using saved `chat_id -> thread_id` mappings.
- Added `/reset` command to clear saved context for the current chat.
- Updated executor flow for explicit `new` and `resume` modes and robust JSON event parsing for thread and response extraction.
- Restarted `telegram-architect-bridge.service` live and verified active state with context mapping load path.
- Recorded live rollout trace in `logs/changes/20260217-021212-telegram-context-persistence-rollout.md`.

### Git State
- Current branch: `main`
- Remote: `origin https://github.com/anunkai1/matrix.git`

### Notes
- Default mapping path: `/home/architect/.local/state/telegram-architect-bridge/chat_threads.json`.
- User should validate in Telegram with two related prompts, then `/reset`, then another prompt to confirm reset behavior.

## 2026-02-17 (Executor Fix)

### Summary
- Resolved Telegram normal-message failure caused by interactive Codex invocation under systemd (`stdin is not a terminal`).
- Updated bridge executor to use non-interactive `codex exec` and return only the last assistant message.
- Restarted `telegram-architect-bridge.service` live on Server3 and verified active state after rollout.
- Recorded live execution details in `logs/changes/20260217-013506-telegram-bridge-executor-nontty-fix.md`.

### Git State
- Current branch: `main`
- Remote: `origin https://github.com/anunkai1/matrix.git`

### Notes
- Local non-TTY executor validation passed as `architect`.
- User should now validate by sending a normal prompt to `@Architect_server3_bot`.

## 2026-02-17 (Live Rollout)

### Summary
- Activated Telegram Architect bridge service on Server3 for bot `@Architect_server3_bot`.
- Applied live runtime env at `/etc/default/telegram-architect-bridge` with allowlisted chat `211761499` and production guardrails (timeout, limits, rate control).
- Installed repo-tracked systemd unit to `/etc/systemd/system/telegram-architect-bridge.service`, enabled service, and restarted successfully.
- Recorded live-change execution trace in `logs/changes/20260217-012725-telegram-bridge-live-rollout.md`.

### Git State
- Current branch: `main`
- Remote: `origin https://github.com/anunkai1/matrix.git`

### Notes
- Service health checks passed (`enabled`, `active`) and journal shows bridge startup with expected allowlist/executor.
- Final user-path validation is to send `/status` or a normal prompt to `@Architect_server3_bot` from the allowlisted chat.

## 2026-02-17

### Summary
- Implemented Telegram-to-Architect bridge v1 using Telegram long polling and local Codex execution (no OpenAI API integration in bridge code).
- Added secure runtime controls: allowlisted chat IDs, per-chat busy lock, timeout guard, rate limiting, max input/output bounds, output chunking for Telegram limits, and generic user-facing failure responses.
- Added operational assets: repo-tracked systemd unit source (`infra/systemd`), env example (`infra/env`), install/restart/status helper scripts (`ops/telegram-bridge`), and runbook documentation (`docs/telegram-architect-bridge.md`).
- Added local smoke test and syntax/compile validation path for the bridge.

### Git State
- Current branch: `main`
- Remote: `origin https://github.com/anunkai1/matrix.git`

### Notes
- Live service install/start and end-to-end Telegram validation are pending bot token and allowlist values in `/etc/default/telegram-architect-bridge`.
- No live system paths outside the repo were modified in this change set.

## 2026-02-16

### Summary
- Updated policy files to enforce GitHub traceability for all server changes.
- Switched workflow to direct commits/pushes on `main`.
- Standardized mirror structure: `infra/` (state), `ops/` (deploy/rollback), `docs/` (runbooks), `logs/` (execution records).
- Added managed architect launcher for Codex full-access mode via repo-tracked bash snippet and deploy script.
- Applied live `.bashrc` change on Server3 with backup and logged execution record in `logs/changes/`.
- Reconciled policy/doc consistency (direct `main` wording), corrected audit log function body to literal `$@`, and hardened deploy script target handling for `/home/architect/.bashrc`.
- Validated live redeploy path (rollback/apply), confirmed `architect` function loads correctly, and improved backup naming in deploy script to avoid same-second collisions.
- Finalized excellence cleanup: corrected remaining log function-body mismatch, aligned merge-policy wording with direct-to-main workflow, added `README.md`, and added a minimal `.gitignore`.

### Git State
- Current branch: `main`
- Remote: `origin https://github.com/anunkai1/matrix.git`

### Notes
- `architect` now launches: `codex -s danger-full-access -a never`.
- Live apply/rollback commands are documented in `docs/server-setup.md`.

## 2026-02-15

### Summary
- Initialized local repository in `/home/architect/matrix`.
- Installed GitHub CLI (`gh`) on Server3.
- Authenticated GitHub CLI with account `anunkai1` using `gh auth login`.
- Created public GitHub repository: `https://github.com/anunkai1/matrix`.
- Added `origin` remote and pushed branch `codex/20260215-github-setup`.

### Git State
- Current branch: `codex/20260215-github-setup`
- Latest commit: `c52f996 chore: initialize repository and github setup`
- Remote: `origin https://github.com/anunkai1/matrix.git`

### Notes
- Pull request creation and `main` branch/default-branch setup are intentionally deferred.
