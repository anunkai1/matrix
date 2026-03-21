# AgentSmith Summary

Last updated: 2026-03-21 (AEST, +10:00)

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
  - `CAPABILITIES.md`
  - `LESSONS.md`
  - `private/SOUL.md`
- `SRO ...` is now a real routed mode and is listed in `/help`

## Operational Memory (Pinned)
- `CAPABILITIES.md` is the first source for bridge/media/delivery capability claims.
- When file delivery target is ambiguous, explicitly ask whether the destination is Codex chat or Telegram attachment.
- AgentSmith can send Telegram files through outbound media directives; do not assume otherwise from the visible tool list.
- Shared-core assumptions must be verified at the real filesystem/runtime path level, not inferred from service-unit paths alone.
- Architect and several sibling bots share bridge code in different ways; implementation topology must be checked before drawing rollout conclusions.

## Recent Changes
- 2026-03-21: added AgentSmith operating structure with authoritative instructions, summary, lessons log, and local soul guidance.
- 2026-03-21: added `CAPABILITIES.md` and updated `AGENTS.md` to treat it as the runtime capability manifest.
- 2026-03-21: implemented `SRO` routing and updated `/help` to advertise it as a real Server3 Runtime Observer mode.
- 2026-03-21: verified the AgentSmith bridge restart and confirmed the new code loaded from logs.

## Current Risks/Watchouts
- Capability mistakes are most likely when relying on tool exposure instead of runtime code/docs.
- Architecture mistakes are most likely when relying on surface paths instead of shared/shimmed runtime inspection.
- Shared-core rollout assumptions should be verified bot by bot.
