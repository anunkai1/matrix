# Home Assistant Ops

This runbook provides a reliable path for delayed Home Assistant climate setpoint changes without inline `systemd-run` shell expansion issues.

## Scripts

- Immediate set: `ops/ha/set_climate_temperature.sh`
- Delayed schedule: `ops/ha/schedule_climate_temperature.sh`

Both scripts avoid embedding `${...}` variables in transient unit command lines.

## Immediate Action

```bash
bash ops/ha/set_climate_temperature.sh \
  --entity climate.master_brm_aircon \
  --temperature 25 \
  --env-file /etc/default/telegram-architect-bridge
```

## Schedule for Later

```bash
bash ops/ha/schedule_climate_temperature.sh \
  --delay 2h \
  --entity climate.master_brm_aircon \
  --temperature 25 \
  --env-file /etc/default/telegram-architect-bridge
```

The command prints transient timer and service unit names.

## Safe Validation (Canary)

Use a short dry-run to validate timer wiring without writing to Home Assistant:

```bash
bash ops/ha/schedule_climate_temperature.sh \
  --delay 15s \
  --entity climate.master_brm_aircon \
  --temperature 25 \
  --env-file /etc/default/telegram-architect-bridge \
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
- If `/etc/default/telegram-architect-bridge` no longer contains HA keys, pass an explicit `--env-file` that does.
- If the timer already fired and started execution, stop the service with `sudo systemctl stop <service-unit-name>.service`.
