# Home Assistant Ops

This runbook provides reliable script-based Home Assistant operations without inline `systemd-run` shell expansion issues.

Default credential source for HA ops scripts: `/etc/default/ha-ops`

## Power Scripts (Any HA Entity)

- Immediate power action: `ops/ha/turn_entity_power.sh`
- Delayed/scheduled power action: `ops/ha/schedule_entity_power.sh`

Use these for any HA entity that supports on/off, including aircons, switches, lights, fans, and similar domains.

### Immediate Action (On/Off)

```bash
bash ops/ha/turn_entity_power.sh \
  --action off \
  --entity climate.master_brm_aircon
```

### Schedule by Relative Time (`in ...`)

```bash
bash ops/ha/schedule_entity_power.sh \
  --in "2 hours" \
  --action off \
  --entity climate.master_brm_aircon
```

```bash
bash ops/ha/schedule_entity_power.sh \
  --in "5 minutes" \
  --action on \
  --entity switch.pool_pump
```

### Schedule by Clock Time (`at ...`)

```bash
bash ops/ha/schedule_entity_power.sh \
  --at "07:00" \
  --action off \
  --entity climate.master_brm_aircon
```

```bash
bash ops/ha/schedule_entity_power.sh \
  --at "2026-02-23 19:00" \
  --action on \
  --entity light.entry
```

Notes:
- `--in` accepts values like `5 minutes`, `2h`, `30s`, and `in 5 minutes`.
- `--at "HH:MM"` schedules the next occurrence of that local time (today if future, otherwise tomorrow).
- `--at` with a full datetime must resolve to a future timestamp.
- Scheduler scripts run a preflight check before creating timers; if credentials or HA API access is broken, they fail immediately.

## Climate Temperature Scripts

- Immediate setpoint action: `ops/ha/set_climate_temperature.sh`
- Delayed setpoint action: `ops/ha/schedule_climate_temperature.sh`

```bash
bash ops/ha/set_climate_temperature.sh \
  --entity climate.master_brm_aircon \
  --temperature 25
```

```bash
bash ops/ha/schedule_climate_temperature.sh \
  --delay 2h \
  --entity climate.master_brm_aircon \
  --temperature 25
```

## Safe Validation (Canary)

Use short dry-runs to validate timer wiring without writing to Home Assistant:

```bash
bash ops/ha/schedule_entity_power.sh \
  --in "15 seconds" \
  --action off \
  --entity climate.master_brm_aircon \
  --dry-run
```

```bash
bash ops/ha/schedule_climate_temperature.sh \
  --delay 15s \
  --entity climate.master_brm_aircon \
  --temperature 25 \
  --dry-run
```

## Cancel a Scheduled Action

```bash
sudo systemctl stop <timer-unit-name>.timer
sudo systemctl status <timer-unit-name>.timer --no-pager
```

## Verify Outcome

```bash
sudo journalctl -u <service-unit-name>.service -n 50 --no-pager
```

Notes:
- Keep tokens in live env files only; do not commit them to git.
- If `/etc/default/ha-ops` is unavailable, pass an explicit `--env-file` with HA keys.
- If the timer already fired and started execution, stop the service with `sudo systemctl stop <service-unit-name>.service`.
