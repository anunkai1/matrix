# Change Record: Telegram HA climate room-context parsing fix

- Timestamp (UTC): 2026-02-19 23:07:14 UTC
- Operator: Codex (architect)
- Repo paths changed:
  - `src/telegram_bridge/ha_control.py`
  - `README.md`
  - `docs/telegram-architect-bridge.md`
- Live action: restarted `telegram-architect-bridge.service` via `ops/telegram-bridge/restart_and_verify.sh`

## Applied Change

- Fixed climate target extraction so room context is preserved for phrases like:
  - `turn on aircon in living room to 22 degrees cold mode`
- Added tokenizer normalization:
  - `cold` / `colder` -> `cool`
- Updated climate target parser behavior:
  - no longer stops target at generic `in`
  - still stops on `in <hvac_mode>` (for example `in cool mode`) to avoid mixing mode text into target
- Added parser self-test case for the full living-room example sentence.

## Verification

- Static/runtime checks:
  - `python3 -m py_compile src/telegram_bridge/ha_control.py src/telegram_bridge/main.py`
  - `bash src/telegram_bridge/smoke_test.sh`
  - Result: pass (`self-test: ok`, `smoke-test: ok`)
- Targeted parser checks:
  - `Turn on aircon in living room to 22 degrees cold mode.` ->
    `{'kind': 'climate_set', 'target': 'aircon in living room', 'mode': 'cool', 'temp_now': 22.0, ...}`
  - `turn on aircon in master room to 23 cool mode` -> room preserved in target
  - `turn on aircon in guest room to 24` -> room preserved in target
- Live service verification after restart:
  - `ActiveState=active`
  - `SubState=running`
  - `ExecMainPID=88063`
  - `ExecMainStartTimestamp=Fri 2026-02-20 09:07:14 AEST`
  - startup journal confirms bridge started with strict routing enabled

## Notes

- No secrets were committed.
- No `/etc/default` env key changes were required in this change set.
