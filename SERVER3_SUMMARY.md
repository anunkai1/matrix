# Server3 Summary

Last updated: 2026-02-22 (AEST, +10:00)

## Current Snapshot
- Primary active component: `telegram-architect-bridge.service`
- Runtime pattern: Telegram long polling + local `codex exec`
- Major enabled capabilities: text/photo/voice/document input handling, per-chat context persistence, optional persistent workers, optional canonical session model, safe queued `/restart`
- Repo workflow: direct-to-`main` with mandatory commit/push proof for non-exempt changes

## Most Recent Changes
- Policy hardening completed for git safety, staging safety, and Brisbane timestamp consistency.
- Canonical session rollout has been enabled in live bridge env with restart verification.
- Documentation updated for summary-first session context and runbook consistency.
- README change-control wording aligned with authoritative summary/archive policy to remove ambiguity.
- Detailed context log renamed from `SERVER3_PROGRESS.md` to `SERVER3_ARCHIVE.md`, with references aligned across docs and runtime policy watch list.

## Session Start Guidance
- Read this file first at the start of each Codex session.
- Open `SERVER3_ARCHIVE.md` only when deeper historical or diagnostic detail is needed.

## Session End Guidance (Non-Exempt Changes)
- Always update this file with current high-level state.
- Update `SERVER3_ARCHIVE.md` when detailed archival context is needed (rollout steps, incidents, rollback trails, complex diagnostics).

## Open Focus
- Voucher automation implementation remains pending (handoff exists in `docs/handoffs/voucher-automation-resume-handoff.md`).
