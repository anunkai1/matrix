# Telegram Bridge Context Preserve Fix + Live Restart

- Timestamp (UTC): 2026-02-17 05:53:23
- Host: Server3
- Operator: Codex (Architect)

## Objective
Prevent silent chat-context loss when `codex exec resume` fails for transient reasons, and activate latest bridge code in live runtime.

## Applied
- Updated bridge logic in `src/telegram_bridge/main.py`:
  - Resume failure no longer clears saved thread context by default.
  - Auto-reset/retry-as-new now occurs only when stderr/stdout indicates invalid or missing thread state.
- Restarted live service using repo helper:
  - `bash ops/telegram-bridge/restart_service.sh`

## Verification
- Smoke test passed:
  - `bash src/telegram_bridge/smoke_test.sh`
- Live service is active after restart:
  - `ExecMainStartTimestamp=Tue 2026-02-17 05:53:08 UTC`
  - `ExecMainPID=82819`
- Startup logs confirm backlog-drop behavior is active:
  - `No queued Telegram updates found at startup.`

## Notes
- This rollout keeps existing multi-chat concurrency model unchanged.
- Context reset remains available explicitly via Telegram `/reset`.
