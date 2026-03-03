# Server3 Summary

Last updated: 2026-03-03 (AEST, +10:00)

## Purpose
- Fast restart context for current live behavior and high-impact recent changes.
- Keep this file concise; use archive/logs for deep chronology and evidence.

## Current Snapshot
- Primary active component: `telegram-architect-bridge.service`
- Runtime pattern: Telegram long polling + local `codex exec`
- Core capabilities: text/photo/voice/document handling, per-chat memory persistence, optional persistent workers, optional canonical session model, safe queued `/restart`
- Routing keywords:
  - `HA ...` / `Home Assistant ...` for stateless HA operation mode
  - `Server3 TV ...` for desktop/browser control mode
  - `Nextcloud ...` for Nextcloud file/calendar operation mode
- TV desktop capability: `server3-tv-start` / `server3-tv-stop` with Brave in maximized mode; Firefox reuse/autoplay fallback helpers are available
- Repo workflow: direct-to-`main` with mandatory commit/push proof for non-exempt changes

## Current State Flags
- Architect Google integration: removed/disabled in live bridge (2026-03-02) after backing account disablement
- Architect primary channel plugin: `telegram` (WhatsApp bridge runtime exists in parallel but is not the primary path)
- Tank runtime defaults: DM prefix bypass enabled in private chats, isolated Joplin profile/path, Codex reasoning effort set to `low`

## Recent Change Sets (Condensed Rolling)
- 2026-03-03: unified Server3 Codex CLI to `0.107.0` in `/usr/local`; resolved `/usr/local` vs `/usr` version mismatch
- 2026-03-03: added lessons rule to clarify file-delivery target before sending (Codex chat vs Telegram attachment)
- 2026-03-02: added keyword-routed Nextcloud operations and changed desktop trigger from `Server3 ...` to `Server3 TV ...`
- 2026-03-02: hardened TV/browser control flow with deterministic pause/play helpers, existing-window reuse, and Firefox autoplay fallback tooling (`wmctrl`, `xdotool`, `yt-dlp`)
- 2026-03-02: added Telegram Architect `/cancel` for per-chat in-flight interruption; change-time test run recorded `85 OK`
- 2026-03-02: removed Architect Google runtime module/config/env/docs paths; change-time test run recorded `79 OK`
- 2026-03-01: completed Telegram plugin architecture phases (A/B/C) plus WhatsApp bridge API + dual-runtime rollout; returned Architect primary channel to Telegram after WhatsApp auth/readiness failures
- 2026-03-01: hardened Tank runtime (dedicated Joplin profile/sync path, DM prefix bypass in private chats, reasoning lowered to `low`)
- 2026-02-28: completed Telegram outbound hardening phases 1-4 (media sends, retries/backoff, observability, structured outbound envelope)
- 2026-02-28: deployed voice transcription quality/safety improvements (decode tuning, alias correction, confidence gating) across Architect/Tank paths

## Archive Pointer
- `SERVER3_ARCHIVE.md` is the canonical long-term detailed history.
- For per-change rollout evidence, use `logs/changes/*.md`.
- Keep this summary focused on current state plus latest high-impact deltas.
