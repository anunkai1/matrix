# Server3 Archive

This file stores detailed operational history for Server3 tasks.

## 2026-03-04 (Summary Roll-Forward Trim for Strict WhatsApp Canonicalization)

Summary:
- Added a new rolling-summary entry for strict WhatsApp canonicalization cleanup (legacy `telegram-architect-whatsapp-bridge` unit/ops/env artifact removal, canonical `govorun-whatsapp-bridge` env template path, and live alias symlink cleanup).
- Kept rolling bound by migrating one oldest entry from summary into archive.

Migrated out of summary during this trim:
- 2026-03-03: unified Server3 Codex CLI to `0.107.0` in `/usr/local`; resolved `/usr/local` vs `/usr` version mismatch.

## 2026-03-04 (Summary Retention Refactor: Operator-First)

Summary:
- Updated `SERVER3_SUMMARY.md` from time-heavy rolling history to an operator-first format:
  - `Current Snapshot`
  - `Operational Memory (Pinned)`
  - `Recent Changes (Rolling Max 8)`
  - `Current Risks/Watchouts`
- Added mandatory summary-retention policy to `ARCHITECT_INSTRUCTION.md`.
- Updated `README.md` summary-tracking pointer to reference the new operator-first retention policy.

Migrated out of summary during this refactor:
- 2026-03-03: added lessons rule to clarify file-delivery target before sending (Codex chat vs Telegram attachment).
- 2026-03-02: added keyword-routed Nextcloud operations and changed desktop trigger from `Server3 ...` to `Server3 TV ...`.
- 2026-03-02: hardened TV/browser control flow with deterministic pause/play helpers, existing-window reuse, and Firefox autoplay fallback tooling (`wmctrl`, `xdotool`, `yt-dlp`).
- 2026-03-02: added Telegram Architect `/cancel` for per-chat in-flight interruption; change-time test run recorded `85 OK`.
- 2026-03-02: removed Architect Google runtime module/config/env/docs paths; change-time test run recorded `79 OK`.
- 2026-03-01: completed Telegram plugin architecture phases (A/B/C) plus WhatsApp bridge API + dual-runtime rollout; returned Architect primary channel to Telegram after WhatsApp auth/readiness failures.
- 2026-03-01: hardened Tank runtime (dedicated Joplin profile/sync path, DM prefix bypass in private chats, reasoning lowered to `low`).
- 2026-02-28: completed Telegram outbound hardening phases 1-4 (media sends, retries/backoff, observability, structured outbound envelope).
- 2026-02-28: deployed voice transcription quality/safety improvements (decode tuning, alias correction, confidence gating) across Architect/Tank paths.

## 2026-02-26 (Repository Scope Cleanup)

Summary:
- Removed legacy media automation records and artifacts from tracked repository history scope.
- Pruned associated docs, infra templates, service units, scripts, and historical change records tied to that scope.
- Updated baseline summary/archive/target-state files so active context stays focused on Telegram Architect bridge operations.

Execution Notes:
- Cleanup was executed as an intentional scope reset requested by maintainer.
- Current active operational focus remains Telegram bridge, Architect CLI memory integration, and associated reliability tooling.

## 2026-02-26 (Managed Architect Launcher + Bridge Restart)

Summary:
- Applied managed Architect launcher to `/home/architect/.bashrc` and restarted bridge service.
- Verified launcher routing to `/home/architect/matrix/src/architect_cli/main.py`.
- Verified bridge healthy after restart and memory runtime path present.

Traceability:
- `logs/changes/20260226-200802-bashrc-launcher-apply-and-bridge-restart-live.md`


## 2026-02-28 (Summary/Archive Rebalance Migration)

Summary:
- Rebalanced tracking so summary remains short rolling context and archive carries detailed long-term history.
- Migrated pre-rebalance detailed summary content into archive verbatim to avoid data loss.
- Updated policy wording in ARCHITECT_INSTRUCTION.md and README.md to enforce bounded summary growth.

Traceability:
- Source migrated content: pre-rebalance `SERVER3_SUMMARY.md` state captured and moved in this change set.

## 2026-02-28 (Summary Roll-Forward Trim for Voice Accuracy Rollout)

Summary:
- Added a new rolling-summary entry for the voice transcription accuracy rollout (decode tuning, alias correction, low-confidence confirmation gate).
- Re-trimmed `SERVER3_SUMMARY.md` back to rolling bounds by migrating oldest entries into archive.

Migrated out of summary during this trim:
- 2026-02-28: hardened direct HA scripts to reject `--token` CLI arguments (credential safety).
- 2026-02-28: restricted bridge restart helper to explicit allowlisted units.
- 2026-02-28: hardened HA scheduler scripts to reject token CLI forwarding.
- 2026-02-28: fixed required-prefix enforcement gap for voice/media requests without captions.
- 2026-02-27: optimized TV apply ownership updates and added policy fingerprint TTL cache in worker checks.
- 2026-02-27: optimized memory prune reconciliation and synced TV startup wording.
- 2026-02-27: changed TV startup browser mode to maximized (not fullscreen).
- 2026-02-27: added TV shell commands to Telegram `/help` and `/h`, then restarted bridge to activate.
- 2026-02-27: deployed command-start TV desktop profile while keeping default boot target as CLI.

## 2026-02-28 (Summary Roll-Forward Trim for Live Voice Env Apply)

Summary:
- Added a new rolling summary entry for live application of voice-accuracy env settings and bridge restart.
- Kept rolling bound by migrating one oldest entry from summary into archive.

Migrated out of summary during this trim:
- 2026-02-28: applied live Tank sudoers mirror so restart permission is restricted to `telegram-tank-bridge.service` only.

## 2026-02-28 (Summary Roll-Forward Trim for Voice Alias Learning Rollout)

Summary:
- Added a new rolling summary entry for controlled voice-alias self-learning with explicit approval commands.
- Re-trimmed summary back to rolling bounds by migrating two oldest entries into archive.

Migrated out of summary during this trim:
- 2026-02-28: removed legacy `tasks/lessons.md` compatibility stub and deleted empty `tasks/` folder after lessons migration to `docs/instructions/lessons.md`.
- 2026-02-28: recorded owner risk decisions (`H5/H6/H7/H9`) and delivered H8 hardening by rejecting `--base-url` in direct HA scripts; docs and lessons updated.

## 2026-02-28 (Summary Roll-Forward Trim for Tank Voice Live Apply)

Summary:
- Added a new rolling summary entry for Tank live application of voice improvements (decode/confidence/learning) and restart verification.
- Re-trimmed summary to rolling bound by migrating two oldest entries into archive.

Migrated out of summary during this trim:
- 2026-02-28: cleaned doc inconsistencies by removing obsolete helper-bot instructions from bridge docs, aligning voucher handoff summary/archive wording with rolling policy, and removing contradictory lessons-path history line.
- 2026-02-28: moved lessons to root-level `LESSONS.md` (with `docs/instructions/lessons.md` redirect stub) so it sits with main repo docs.

## 2026-02-28 (Summary Roll-Forward Trim for TV Startup Wording Correction)

Summary:
- Added a new rolling-summary entry for TV startup wording alignment (fullscreen -> maximized).
- Re-trimmed summary back to rolling bound by migrating one oldest entry into archive.

Migrated out of summary during this trim:
- 2026-02-28: removed `docs/instructions/lessons.md` redirect stub; `LESSONS.md` is now the only active lessons path.

## 2026-02-28 (Summary Roll-Forward Trim for Claude Code Alias Default)

Summary:
- Added a new rolling-summary entry for default voice alias correction `clode code -> claude code` with docs/env/test updates.
- Re-trimmed summary back to rolling bound by migrating two oldest entries into archive.

Migrated out of summary during this trim:
- 2026-02-28: upgraded chat summarization to structured sections (objective/decisions/state/open items/preferences/risks), added summary-regeneration helper, and regenerated all 6 existing live summaries in `/home/architect/.local/state/telegram-architect-bridge/memory.sqlite3`.
- 2026-02-28: renamed memory mode label from `full` to `all_context` across runtime/help/docs, while keeping `full` as a backward-compatible alias.

## 2026-02-28 (Summary Roll-Forward Trim for Voucher Handoff Removal)

Summary:
- Added a new rolling-summary entry for deletion of `docs/handoffs/voucher-automation-resume-handoff.md` per owner request.
- Re-trimmed summary back to rolling bounds by migrating four oldest entries into archive.

Migrated out of summary during this trim:
- 2026-02-28: completed voice rollout traceability by syncing missing live voice env mirror keys (idle-timeout/socket/log path) and verifying live Telegram voice requests after restart with warm transcriber process/socket active.
- 2026-02-28: verified Tank memory parity with Architect; ran Tank summary regeneration (0 summary rows present to rewrite) and confirmed canonical mode rows are `all_context`.
- 2026-02-28: upgraded voice transcription runtime with a warm persistent service (`voice_transcribe_service.py`) that loads on first voice request, reuses the model, auto-unloads after idle timeout (default 1 hour), uses GPU-first with CPU fallback, and applies fixed ffmpeg preprocessing when available.
- 2026-02-28: improved high-level policy clarity in `ARCHITECT_INSTRUCTION.md` (added `LESSONS.md` to session-start checklist, referenced canonical Git section to avoid duplicate workflow drift, relaxed paused-state next-action wording to accept explicit approval with a recommended phrase, and updated sudo-boundary wording to present tense).


## Legacy Snapshot Pointer (2026-02-28 Verbatim)

Summary:
- The large migrated historical summary block was moved to `SERVER3_ARCHIVE_LEGACY_20260228.md`.
- Content in the legacy file is preserved verbatim for audit/history needs.
- `SERVER3_ARCHIVE.md` remains the concise canonical archive index for ongoing updates.

Maintenance Rule:
- Add new archival entries in this file.
- Keep verbatim historical dumps in separate `SERVER3_ARCHIVE_LEGACY_*.md` files and link them here.
