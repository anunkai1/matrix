# Server3 Summary

Last updated: 2026-03-04 (AEST, +10:00)

## Purpose
- Fast restart context optimized for execution speed, clarity, and recovery value.
- Keep this file compact and operator-first; move deep history to `SERVER3_ARCHIVE.md`.

## Summary Policy (Operator-First)
- Keep only items that materially improve execution speed, correctness, or recovery.
- Structure limits:
  - `Operational Memory (Pinned)`: 6-10 items
  - `Recent Changes (Rolling Max 8)`: newest high-value deltas only
  - `Current Risks/Watchouts (Max 5)`: active operational caveats only
- Do not trim by age alone; trim by reuse and operational impact.

## Current Snapshot
- Primary active component: `telegram-architect-bridge.service`
- Runtime pattern: Telegram long polling + local `codex exec`
- Core capabilities: text/photo/voice/document handling, per-chat memory persistence, optional persistent workers, optional canonical session model, safe queued `/restart`
- Repo workflow: direct-to-`main` with mandatory commit/push proof for non-exempt changes

## Operational Memory (Pinned)
- Routing keywords:
  - `HA ...` / `Home Assistant ...` for stateless HA operation mode
  - `Server3 TV ...` for desktop/browser control mode
  - `Nextcloud ...` for Nextcloud file/calendar operation mode
- Primary channel: `telegram`; WhatsApp runtime exists in parallel (`whatsapp-govorun-bridge.service` + `govorun-whatsapp-bridge.service`).
- TV desktop/browser reliability is hardened with deterministic helpers, existing-window reuse, and autoplay fallback tooling (`wmctrl`, `xdotool`, `yt-dlp`).
- Tank defaults are hardened: DM prefix bypass in private chats, isolated Joplin profile/path, reasoning effort `low`.
- Govorun WhatsApp progress depends on outbound message-key mapping for `/messages/edit`; compact elapsed wording is env-configured.
- Architect Google runtime integration is removed/disabled.
- Server time standard for operations is Brisbane (`Australia/Brisbane`, AEST/UTC+10).

## Recent Changes (Rolling Max 8)
- 2026-03-04: reduced active markdown redundancy by making `AGENTS.md` a minimal pointer to `ARCHITECT_INSTRUCTION.md`, trimming duplicated policy text in `README.md`, and consolidating repeated Govorun setup details in `docs/runbooks/telegram-whatsapp-dual-runtime.md` to reference the canonical ops runbook.
- 2026-03-04: drafted and activated `ARCHITECT_INSTRUCTION.md` as authoritative Server3 execution policy; aligned `AGENTS.md` to startup-checklist/pointer role and updated `README.md` policy references to remove authority ambiguity.
- 2026-03-04: addressed three follow-up code-review issues in WhatsApp/progress paths: made outbound edit-key cache dedupe-safe, enforced mapped-chat usage for `/messages/edit`, and replaced hardcoded compact elapsed wording with configurable env keys.
- 2026-03-03: fixed Govorun WhatsApp progress freeze at `... 1s` by implementing real `/messages/edit` handling in `ops/whatsapp_govorun/bridge/src/index.mjs`, then redeployed both WhatsApp services.
- 2026-03-03: updated Govorun/WhatsApp compact progress rendering to one-line elapsed format and 1s edit cadence.
- 2026-03-03: strict WhatsApp runtime cleanup finalized `govorun`-only ops/docs and removed legacy user-unit artifact.
- 2026-03-03: fixed WhatsApp runtime drift/regressions (config compatibility, caption return consistency, unit/install/env/runbook alignment, dependency add for `link-preview-js`); validation recorded `111 OK` + `self-test OK` + `smoke-test OK`.
- 2026-03-03: unified Server3 Codex CLI to `0.107.0` in `/usr/local`; resolved `/usr/local` vs `/usr` version mismatch.

## Current Risks/Watchouts (Max 5)
- Browser autoplay can still be blocked by client policy and may require UI fallback interactions.
- WhatsApp progress edit behavior relies on valid outbound key mappings; mismatch paths should be treated as warning conditions.
- Keep private guidance files under `private/` local-only and out of GitHub.

## Archive Pointer
- `SERVER3_ARCHIVE.md` is the canonical long-term detailed history.
- For per-change rollout evidence, use `logs/changes/*.md`.
