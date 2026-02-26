# Change Record: Telegram HA Live Env Config (No Restart)

## Timestamp
- 2026-02-18 00:11:18 UTC

## Scope
- Live path edited: /etc/default/telegram-architect-bridge
- Repo mirror updated: infra/env/telegram-architect-bridge.server3.redacted.env

## Applied HA keys
- TELEGRAM_HA_ENABLED=true
- TELEGRAM_HA_BASE_URL=http://192.168.0.114:8123
- TELEGRAM_HA_TOKEN=<redacted>
- TELEGRAM_HA_APPROVAL_TTL_SECONDS=3600
- TELEGRAM_HA_TEMP_MIN_C=16
- TELEGRAM_HA_TEMP_MAX_C=30
- TELEGRAM_HA_ALLOWED_DOMAINS=climate,switch,light,water_heater,input_boolean,fan,cover,script,scene,media_player,vacuum,humidifier,select,number,input_number
- TELEGRAM_HA_ALLOWED_ENTITIES=
- TELEGRAM_HA_ALIASES_PATH=/home/architect/.local/state/telegram-architect-bridge/ha_aliases.json
- TELEGRAM_HA_CLIMATE_FOLLOWUP_SCRIPT=script.architect_schedule_climate_followup
- TELEGRAM_HA_SOLAR_SENSOR_ENTITY=sensor.sh10rs_a23a1801637_total_export_active_power
- TELEGRAM_HA_SOLAR_EXCESS_THRESHOLD_W=2000

## Verification
- Confirmed live key presence via redacted grep/awk output.

## Operator request boundary
- Per owner instruction, service restart was intentionally NOT executed in this change set.
