# Change Record: Telegram HA-only voice parser support

- Timestamp (UTC): 2026-02-19 21:54:19 UTC
- Operator: Codex (architect)
- Repo paths changed:
  - `src/telegram_bridge/main.py`
  - `README.md`
  - `docs/telegram-architect-bridge.md`
- Live action: restarted `telegram-architect-bridge.service` via `ops/telegram-bridge/restart_and_verify.sh`

## Applied Change

- Enabled HA-only chat handling for voice notes.
- HA-only voice flow now:
  - download Telegram voice file
  - transcribe with configured `TELEGRAM_VOICE_TRANSCRIBE_CMD`
  - echo transcript to chat
  - pass transcript text into existing HA parser/status flow
- Kept existing HA-only guardrails:
  - photo/file inputs remain rejected in HA-only mode
  - non-HA text/voice still returns HA-only reminder
- Refactored voice transcription handling into shared helper (`transcribe_voice_for_chat`) to keep behavior consistent and avoid duplicate temp-file/transcription error code paths.

## Verification

- Static/runtime checks:
  - `python3 -m py_compile src/telegram_bridge/main.py src/telegram_bridge/ha_control.py`
  - `bash src/telegram_bridge/smoke_test.sh`
  - Result: pass (`self-test: ok`, `smoke-test: ok`)
- Live service verification after restart:
  - `ActiveState=active`
  - `SubState=running`
  - `ExecMainPID=85047`
  - `ExecMainStartTimestamp=Fri 2026-02-20 07:54:19 AEST`
  - startup journal confirms bridge started with strict chat routing enabled

## Notes

- No secrets were committed.
- No `/etc/default` environment key changes were required for this fix.
