# Telegram Bridge Executor Non-TTY Fix (Live)

- Timestamp (UTC): 2026-02-17 01:35:06
- Host: Server3
- Operator: Codex (Architect)

## Issue
Telegram bridge returned generic failures for normal prompts while `/status` worked.

## Root Cause
Executor used interactive `codex` invocation under systemd. Runtime log showed:
- `Error: stdin is not a terminal`

## Repo Changes Applied
- Updated `src/telegram_bridge/executor.sh` to run non-interactive `codex exec`.
- Captured only final assistant message via `--output-last-message`.
- Suppressed CLI transcript noise from stdout and surfaced failure logs to stderr.
- Updated runbook note in `docs/telegram-architect-bridge.md`.

## Live Actions
- Restarted service: `telegram-architect-bridge.service`.
- Verified service returned to `active` state.

## Validation
- Direct non-TTY test succeeded:
  - `sudo -u architect -H bash -lc 'echo "Who are you" | /home/architect/matrix/src/telegram_bridge/executor.sh'`
- Journal no longer shows new `stdin is not a terminal` errors after restart.

## Notes
- Final end-user confirmation requires sending a normal prompt in Telegram after this rollout.
