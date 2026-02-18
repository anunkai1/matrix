# Server3 Progress Log

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
