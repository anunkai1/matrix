# Server3 Summary

Last updated: 2026-02-28 (AEST, +10:00)

## Current Snapshot
- Primary active component: `telegram-architect-bridge.service`
- Runtime pattern: Telegram long polling + local `codex exec`
- Major enabled capabilities: text/photo/voice/document handling, per-chat memory persistence, optional persistent workers, optional canonical session model, safe queued `/restart`
- On-demand TV desktop capability: `server3-tv-start` / `server3-tv-stop` with Brave opened in maximized mode
- Repo workflow: direct-to-`main` with mandatory commit/push proof for non-exempt changes

## Recent Change Sets (Rolling)
- 2026-02-28: moved lessons to root-level `LESSONS.md` (with `docs/instructions/lessons.md` redirect stub) so it sits with main repo docs.
- 2026-02-28: removed legacy `tasks/lessons.md` compatibility stub and deleted empty `tasks/` folder after lessons migration to `docs/instructions/lessons.md`.
- 2026-02-28: moved lessons log to `docs/instructions/lessons.md`, updated authoritative instruction references, and kept `tasks/lessons.md` as compatibility stub.
- 2026-02-28: recorded owner risk decisions (`H5/H6/H7/H9`) and delivered H8 hardening by rejecting `--base-url` in direct HA scripts; docs and lessons updated.
- 2026-02-28: applied live Tank sudoers mirror so restart permission is restricted to `telegram-tank-bridge.service` only.
- 2026-02-28: hardened direct HA scripts to reject `--token` CLI arguments (credential safety).
- 2026-02-28: restricted bridge restart helper to explicit allowlisted units.
- 2026-02-28: hardened HA scheduler scripts to reject token CLI forwarding.
- 2026-02-28: fixed required-prefix enforcement gap for voice/media requests without captions.
- 2026-02-27: optimized TV apply ownership updates and added policy fingerprint TTL cache in worker checks.
- 2026-02-27: optimized memory prune reconciliation and synced TV startup wording.
- 2026-02-27: changed TV startup browser mode to maximized (not fullscreen).
- 2026-02-27: added TV shell commands to Telegram `/help` and `/h`, then restarted bridge to activate.
- 2026-02-27: deployed command-start TV desktop profile while keeping default boot target as CLI.

## Archive Pointer
- `SERVER3_ARCHIVE.md` is the canonical long-term detailed history.
- Older detailed entries were migrated from summary to archive on 2026-02-28 to keep this summary bounded.
- For per-change rollout evidence, use `logs/changes/*.md`.
