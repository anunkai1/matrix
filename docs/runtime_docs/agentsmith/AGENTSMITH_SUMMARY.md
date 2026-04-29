# AgentSmith Summary

Last updated: 2026-04-27 (AEST, +10:00)

## Purpose
- Fast restart context for AgentSmith.
- Keep this file compact, current, and operational.

## Current Snapshot
- Runtime: Telegram bridge on Server3
- Assistant name: `AgentSmith`
- Primary runtime root: `/home/agentsmith/agentsmithbot`
- Shared core dependency: `/home/architect/matrix/src/telegram_bridge`
- Core documentation now includes:
  - `AGENTSMITH_INSTRUCTION.md`
  - `LESSONS.md`
  - `private/SOUL.md`
- `SRO ...` is now a real routed mode and is listed in `/help`

## Operational Memory (Pinned)
- For bridge/media/delivery capability claims, check the live runtime profile here first, then inspect code/live state; do not trust tool exposure alone.
- AgentSmith can send Telegram documents and photos from local file paths through outbound media directives.
- Voice and some media-intelligence paths are config-gated; do not assume they are enabled in the live runtime without checking.
- Current routed surfaces include `HA`, `Server3 TV`, `Server3 Browser`/`Browser Brain`, `Nextcloud`, `SRO`, and lightweight YouTube-link auto-routing.
- When file delivery target is ambiguous, explicitly ask whether the destination is Codex chat or Telegram attachment.
- Shared-core assumptions must be verified at the real filesystem/runtime path level, not inferred from service-unit paths alone.
- Architect and several sibling bots share bridge code in different ways; implementation topology must be checked before drawing rollout conclusions.

## Recent Changes
- 2026-04-27: aligned AgentSmith's live Venice model to `zai-org-glm-5-1` so it matches the current Venice account models list.
- 2026-04-27: mirrored the local Pi/Venice provider shape into AgentSmith so the `pi` engine can select `venice` from `/home/agentsmith/agentsmithbot` while still reading its own runtime-root `AGENTS.md`.
- 2026-03-22: collapsed the separate capability doc into `AGENTSMITH_SUMMARY.md` and `AGENTSMITH_INSTRUCTION.md` so AgentSmith keeps fewer runtime docs while preserving the key capability guardrails.
- 2026-03-21: added AgentSmith operating structure with authoritative instructions, summary, lessons log, and local soul guidance.
- 2026-03-21: implemented `SRO` routing and updated `/help` to advertise it as a real Server3 Runtime Observer mode.
- 2026-03-21: verified the AgentSmith bridge restart and confirmed the new code loaded from logs.

## Current Risks/Watchouts
- Capability mistakes are most likely when relying on tool exposure instead of runtime code/docs.
- Architecture mistakes are most likely when relying on surface paths instead of shared/shimmed runtime inspection.
- Shared-core rollout assumptions should be verified bot by bot.
