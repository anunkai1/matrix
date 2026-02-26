# Change Record: Telegram HA-only status query support

- Timestamp (UTC): 2026-02-19 21:20:38 UTC
- Operator: Codex (architect)
- Repo paths changed:
  - `src/telegram_bridge/ha_control.py`
  - `src/telegram_bridge/main.py`
  - `README.md`
  - `docs/telegram-architect-bridge.md`
- Live action: restarted `telegram-architect-bridge.service` via `ops/telegram-bridge/restart_and_verify.sh`

## Applied Change

- Added a dedicated HA status-query path for natural read prompts.
- In HA-only chats, prompts like `what's on right now` are now handled as HA status requests.
- In mixed chats, implicit status prompts are not auto-routed to HA unless HA context is explicit.
- Added active-entity summary output constrained to allowed HA domains/entities.
- Updated docs to reflect HA-only status-query support.

## Verification

- Static/runtime checks:
  - `python3 -m py_compile src/telegram_bridge/ha_control.py src/telegram_bridge/main.py`
  - `bash src/telegram_bridge/smoke_test.sh`
  - Result: pass (`self-test: ok`, `smoke-test: ok`)
- Status intent checks:
  - implicit HA-only query detected: `True`
  - same query in mixed mode without HA context: `False`
  - explicit HA-context query in mixed mode: `True`
- Live service verification after restart:
  - `ActiveState=active`
  - `SubState=running`
  - `ExecMainPID=80810`
  - `ExecMainStartTimestamp=Fri 2026-02-20 07:20:38 AEST`
  - startup journal confirms bridge started with chat routing enabled

## Notes

- No secrets were committed.
- No live env key changes were made in this change set.
