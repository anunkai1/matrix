# Server3 Summary

Last updated: 2026-03-10 (AEST, +10:00)

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
- Canonical runtime inventory now lives in `infra/server3-runtime-manifest.json`, with shared live inspection via `python3 ops/server3_runtime_status.py`
- Shared runtime core now lives in `/home/architect/matrix/src/telegram_bridge`; Tank/Govorun/Oracle run as per-runtime overlays with preserved service names, env paths, AGENTS, and state roots.
- Repo workflow: direct-to-`main` with mandatory commit/push proof for non-exempt changes
- Runtime observer daily Telegram summary now appends a plain-English operator line indicating whether attention is needed.
- Runtime observer daily health delivery is centralized through `staker_alerts_bot` to chat `211761499` (single destination).

## Runtime Inventory
- Canonical manifest: `infra/server3-runtime-manifest.json`
- Shared live status command: `python3 ops/server3_runtime_status.py`
- Covered runtime groups: Architect, Tank, Govorun transport/bridge, Oracle transport/bridge, network layer, guardrail timers, optional UI.

## Operational Memory (Pinned)
- Routing keywords:
  - `HA ...` / `Home Assistant ...` for stateless HA operation mode
  - `Server3 TV ...` for desktop/browser control mode
  - `Nextcloud ...` for Nextcloud file/calendar operation mode
- Primary channel: `telegram`; WhatsApp runtime exists in parallel (`whatsapp-govorun-bridge.service` + `govorun-whatsapp-bridge.service`).
- Runtime observer is enabled on timer (`server3-runtime-observer.timer`) with Telegram daily summary mode (`RUNTIME_OBSERVER_MODE=telegram_daily_summary`) scheduled for `08:05` AEST.
- Govorun cross-channel routing contract guard is enforced by `ops/chat-routing/validate_chat_routing_contract.py` with canonical policy in `infra/contracts/server3-chat-routing.contract.env`; daily drift timer is `server3-chat-routing-contract-check.timer`.
- TV desktop/browser reliability is hardened with deterministic helpers, existing-window reuse, and autoplay fallback tooling (`wmctrl`, `xdotool`, `yt-dlp`).
- Tank defaults are hardened: DM prefix bypass in private chats, isolated Joplin profile/path, reasoning effort `low`.
- Architect Telegram + CLI now share one neutral memory identity on Server3 via `shared:architect:main`; the shared bucket merges the existing Architect Telegram chats and CLI history while starting a fresh unified Codex session thread.
- Govorun WhatsApp behavior is env-tunable: progress wording, busy-lock wording, and reply-tone guidance are configured via `/etc/default/govorun-whatsapp-bridge`.
- Server time standard for operations is Brisbane (`Australia/Brisbane`, AEST/UTC+10).

## Recent Changes (Rolling Max 8)
- 2026-03-10: completed a second-pass recovery of the local library stack after the importer path repair by clearing a bad Docker runtime state, restoring the downloader, indexer, importer, request, and catalog services, and verifying the recovered `Survivor AU` episodes 7 and 8 now exist in the live library paths and are indexed by the catalog; remaining importer warnings on the recovered backlog are duplicate-destination notices rather than broken import paths.
- 2026-03-10: repaired a Server3 download/import path drift by restoring legacy `/data/...` compatibility mounts for the local library importers, then backfilled previously downloaded valid episodes into the live library paths so the catalog can see them again.
- 2026-03-10: added a planning-only spec at `docs/specs/server3-browser-automation-mvp.md` for an OpenClaw-style browser-control layer on Server3, capturing the intended scope, architecture, rationale, and next actions before any implementation work starts.
- 2026-03-10: clarified the `mavali_eth` planning split so `docs/specs/mavali-eth-mvp.md` now acts as the human/operator planning doc with decisions, rationale, and next actions, while `infra/contracts/mavali-eth-mvp.contract.yaml` stays limited to the current agreed runtime behavior.
- 2026-03-10: added planning-only `mavali_eth` MVP artifacts at `docs/specs/mavali-eth-mvp.md` and `infra/contracts/mavali-eth-mvp.contract.yaml` so the human/operator spec and the stricter LLM/runtime contract are pinned before implementation starts.
- 2026-03-10: fixed Govorun reply-prefix behavior so a prefix-only reply like `говорун` on WhatsApp now uses the quoted/replied-to message as the actionable prompt instead of rejecting with the generic prefixed-prompt help text.
- 2026-03-10: fixed a live WhatsApp quoted-image gap after transport restarts by teaching the Govorun Node transport to reconstruct quoted media directly from Baileys `quotedMessage` payloads instead of depending only on in-memory reply-context cache.
- 2026-03-10: added a bounded attachment archive to the shared bridge so image/file follow-ups can reuse previously seen media for about 14 days by default, with archived-summary fallback after binary expiry and live activation on `govorun-whatsapp-bridge.service`.
- 2026-03-10: hardened follow-up handling for replied media by teaching the shared bridge to reuse photo/document/voice payloads from replied-to messages, and teaching the Govorun WhatsApp Node transport to preserve quoted media metadata so later questions about the same image/file no longer depend only on a one-shot temp download.

## Current Risks/Watchouts (Max 5)
- Tank keeps `/home/tank/tankbot/src` linked to the shared repo source tree; preserve `TELEGRAM_RUNTIME_ROOT=/home/tank/tankbot` in its unit/env so runtime identity does not collapse back to the shared repo root.
- Browser autoplay can still be blocked by client policy and may require UI fallback interactions.
- WhatsApp progress edit behavior relies on valid outbound key mappings; mismatch paths should be treated as warning conditions.
- Keep group allowlists aligned (`WA_ALLOWED_CHAT_IDS`/`WA_ALLOWED_GROUPS` with `TELEGRAM_ALLOWED_CHAT_IDS`) while managing DM admission separately via `WA_ALLOWED_DMS` and `TELEGRAM_ALLOW_PRIVATE_CHATS_UNLISTED`.
- Telegram/WhatsApp channels can still show transient API retries or reconnect churn; DNS-side retry risk is reduced via custom NordVPN DNS but should still be monitored during network instability.
- Runtime observer alert routing depends on `RUNTIME_OBSERVER_TELEGRAM_CHAT_IDS` (or Telegram env fallback) remaining valid for the active bot token.

## Archive Pointer
- `SERVER3_ARCHIVE.md` is the canonical long-term detailed history.
- For per-change rollout evidence, use `logs/changes/*.md`.
