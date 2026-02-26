# Change Record: Telegram HA off-query support + climate turn-on enforcement

- Timestamp (UTC): 2026-02-19 21:35:51 UTC
- Operator: Codex (architect)
- Repo paths changed:
  - `src/telegram_bridge/ha_control.py`
  - `src/telegram_bridge/main.py`
  - `README.md`
  - `docs/telegram-architect-bridge.md`
- Live action: restarted `telegram-architect-bridge.service` via `ops/telegram-bridge/restart_and_verify.sh`

## Applied Change

- Added HA status-query mode parsing (`on` / `off`) for read-only prompts.
- Added OFF/inactive query support for HA-only prompts such as:
  - `whats off?`
  - `whats off in HA?`
- Kept mixed-chat guard behavior: implicit status queries without explicit HA context are still not auto-routed to HA.
- Added status summarization path for both ON and OFF views constrained by HA allowlists.
- Fixed climate control behavior for `turn on ... to <temp>`:
  - parser now carries `power_on_requested=True` for climate-set intents derived from `turn on` phrasing
  - executor now calls `climate.turn_on` when no HVAC mode is supplied, then applies `climate.set_temperature`
  - execution text reflects power-on when that path is used

## Verification

- Static/runtime checks:
  - `python3 -m py_compile src/telegram_bridge/ha_control.py src/telegram_bridge/main.py`
  - `bash src/telegram_bridge/smoke_test.sh`
  - Result: pass (`self-test: ok`, `smoke-test: ok`)
- Targeted parser checks:
  - `parse_ha_status_query_mode('whats off?', allow_implicit=True) -> 'off'`
  - `parse_ha_status_query_mode('whats off in HA?', allow_implicit=False) -> 'off'`
  - `parse_ha_status_query_mode('whats off?', allow_implicit=False) -> None`
  - `_parse_control_intent('turn on AC living to 25')` includes `power_on_requested=True`
- Live service verification after restart:
  - `ActiveState=active`
  - `SubState=running`
  - `ExecMainPID=81950`
  - `ExecMainStartTimestamp=Fri 2026-02-20 07:35:51 AEST`
  - startup journal confirms bridge started with strict chat routing enabled

## Notes

- No secrets were committed.
- No `/etc/default` environment key changes were required for this fix.
