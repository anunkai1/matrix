# 2026-03-21 12:55:56 AEST - Govorun Russian-default persona policy

## Request
- Make Govorun default to Russian using the Govorun-specific `AGENTS.md` policy path.

## Current State Inspected
- Verified the live Govorun policy file at `/home/govorun/govorunbot/AGENTS.md`.
- Confirmed Govorun already runs with its own runtime-root policy file and bridge env watch path.
- Confirmed the live policy file did not yet include any default reply-language rule.

## Change Applied
- Added a new `Language` section to `/home/govorun/govorunbot/AGENTS.md` with these rules:
  - default reply language is Russian
  - explicit user language requests override the default
  - English input alone does not force English replies unless English is clearly needed

## Verification
- Captured a minimal unified diff against the pre-change copy and verified the scope is one new policy block.
- Reinstalled the edited live file with original owner/group/mode preserved (`root:root`, `0644`).
- Restarted `govorun-whatsapp-bridge.service` via `ops/telegram-bridge/restart_and_verify.sh --unit govorun-whatsapp-bridge.service`.
- Verified restart output reported `verification=pass` at `2026-03-21 12:55:56 AEST`.
- Verified the live file now contains the `Language` section.

## Notes
- No bridge env change was made.
- `TELEGRAM_POLICY_RESET_MEMORY_ON_CHANGE` was not changed, so the rollout relies on the bridge restart rather than a full bridge-memory wipe.
