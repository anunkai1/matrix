# Change Record — 2026-02-20 15:45:05 AEST

## Summary
- Implemented live Architect progress streaming in Telegram bridge runtime.
- Replaced static one-shot thinking placeholder with dynamic request progress behavior.

## Repo Changes
- `src/telegram_bridge/main.py`
  - Added `ProgressReporter` to provide:
    - periodic Telegram `typing` actions while requests run
    - in-place edited progress status message with elapsed time and current step
  - Updated executor flow to stream JSON events from executor subprocess in real time.
  - Wired Codex event parsing for progress signals (`turn`, `reasoning`, `command_execution`, `agent_message`).
  - Updated executor output parsing to support streamed JSON events directly.
  - Removed static thinking-ack send path from worker flow.
  - Added self-test coverage for streamed executor output parsing and progress-event extraction.
- `src/telegram_bridge/executor.sh`
  - Switched to passthrough streaming of `codex exec --json` output.
  - Removed end-of-run buffering/parsing markers so runtime can consume live events.
- `README.md`
  - Updated status bullets to describe live progress behavior.
- `docs/telegram-architect-bridge.md`
  - Replaced placeholder-thinking note with typing + edited progress status behavior.

## Validation
- `python3 -m py_compile src/telegram_bridge/main.py` (pass)
- `bash src/telegram_bridge/smoke_test.sh` (pass)
- `printf 'Reply with exactly: ping' | bash src/telegram_bridge/executor.sh new` (JSON stream observed)
- `bash ops/telegram-bridge/restart_and_verify.sh` (pass; service active/running)

## Live Rollout
- Applied by restarting bridge service:
  - `telegram-architect-bridge.service`
- Restart verification markers:
  - before PID: `9044`
  - after PID: `9432`
  - verification: `pass`

## Notes
- No `/etc/default/telegram-architect-bridge` env changes were required in this change set.
