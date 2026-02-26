# Telegram Resume Full-Access Rollout

- Timestamp (UTC): 2026-02-17 03:16:56
- Host: Server3
- Operator: Codex (Architect)

## Objective
Ensure Telegram resumed conversations run with full access, matching new-session capability.

## Change
- Updated `src/telegram_bridge/executor.sh` resume mode command:
  - from: `codex exec resume --json <thread_id> -`
  - to: `codex exec resume --dangerously-bypass-approvals-and-sandbox --json <thread_id> -`

## Validation
- Local resume-mode test succeeded with DNS command:
  - `getent hosts github.com` resolved correctly from resume path.
- Restarted `telegram-architect-bridge.service` and verified `active` state.

## Notes
- This increases execution authority for resumed Telegram prompts to full access.
- Allowlist still applies (`TELEGRAM_ALLOWED_CHAT_IDS`).
