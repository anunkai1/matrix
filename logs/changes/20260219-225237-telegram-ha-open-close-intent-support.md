# Change Record: Telegram HA open/close intent support

- Timestamp (UTC): 2026-02-19 22:52:37 UTC
- Operator: Codex (architect)
- Repo paths changed:
  - `src/telegram_bridge/ha_control.py`
  - `README.md`
  - `docs/telegram-architect-bridge.md`
- Live action: restarted `telegram-architect-bridge.service` via `ops/telegram-bridge/restart_and_verify.sh`

## Applied Change

- Added HA parser support for natural `open` / `close` intents:
  - `open garage`
  - `Open garage please`
  - `close garage`
- Added `entity_open` / `entity_close` action kinds in HA execution path.
- Service mapping behavior:
  - `cover.*` -> `open_cover` / `close_cover`
  - `lock.*` -> `unlock` / `lock`
  - other domains -> `turn_on` / `turn_off` (open/close fallback)
- Expanded HA schedule pre-filter keywords so open/close/garage phrasing enters parser path.
- Added parser self-test cases for open/close phrases.

## Verification

- Static/runtime checks:
  - `python3 -m py_compile src/telegram_bridge/ha_control.py src/telegram_bridge/main.py`
  - `bash src/telegram_bridge/smoke_test.sh`
  - Result: pass (`self-test: ok`, `smoke-test: ok`)
- Parser checks:
  - `_parse_control_intent('open garage') -> {'kind': 'entity_open', 'target': 'garage'}`
  - `_parse_control_intent('Open garage please') -> {'kind': 'entity_open', 'target': 'garage'}`
  - `_parse_control_intent('close garage') -> {'kind': 'entity_close', 'target': 'garage'}`
- Live service verification after restart:
  - `ActiveState=active`
  - `SubState=running`
  - `ExecMainPID=87414`
  - `ExecMainStartTimestamp=Fri 2026-02-20 08:52:37 AEST`
  - startup journal confirms bridge started with strict routing enabled

## Notes

- No secrets were committed.
- No `/etc/default` env key changes were required in this change set.
