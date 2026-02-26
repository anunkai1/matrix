# 20260227-093829 - Telegram HA Keyword Routing (Repo-only)

## Scope
- Force explicit Home Assistant routing for Telegram messages that start with `HA` or `Home Assistant`.
- Prevent fallback to generic free-form HA execution patterns for keyword-triggered requests.

## Objective
- Make user phrasing like `HA turn on masters AC to dry mode at 9:25am` reliably use the hardened `ops/ha/*.sh` paths.

## Changes Applied
1. Updated bridge handler routing:
   - `src/telegram_bridge/handlers.py`
   - added keyword parser for `HA` and `Home Assistant`
   - added strict HA-mode prompt wrapper with script allowlist:
     - `ops/ha/turn_entity_power.sh`
     - `ops/ha/schedule_entity_power.sh`
     - `ops/ha/set_climate_temperature.sh`
     - `ops/ha/schedule_climate_temperature.sh`
     - `ops/ha/set_climate_mode.sh`
     - `ops/ha/schedule_climate_mode.sh`
   - keyword-routed requests now run `stateless=true`
   - keyword-only requests (no action text) now fail fast with a usage hint
2. Added tests:
   - `tests/telegram_bridge/test_bridge_core.py`
   - keyword extraction variants
   - HA keyword routing enters stateless worker path
   - keyword-only rejection behavior
3. Updated operator docs:
   - `docs/telegram-architect-bridge.md`
   - documented keyword behavior and stateless routing rule

## Validation
- `python3 -m unittest tests/telegram_bridge/test_bridge_core.py` (pass)
- `python3 src/telegram_bridge/main.py --self-test` (pass)

## Outcome
- Telegram HA requests with explicit `HA`/`Home Assistant` prefix are now routed through a deterministic HA mode with stronger script-path guardrails.
