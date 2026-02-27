# Helper Bot Target State (Server3)

This document mirrors the intended live state for the dedicated helper Telegram bot runtime.

## Host User

- Linux user: `helperbot`
- Home: `/home/helperbot`
- Shell: `/bin/bash`
- Sudo group membership: none

## Access Prerequisites

- `/home/architect` requires execute traversal for `helperbot` to reach repo paths.
  - Current live fallback: mode includes `o+x` (set when ACL tooling is unavailable).

## Live Environment Files

- `/etc/default/telegram-helper-bridge`
  - owner/group: `root:helperbot`
  - mode: `640`
- `/etc/default/ha-ops-helper`
  - owner/group: `root:helperbot`
  - mode: `640`

## Sudo Policy

- `/etc/sudoers.d/helperbot-telegram-ha`
  - owner/group: `root:root`
  - mode: `440`
  - allowed commands:
    - `ops/ha/schedule_entity_power.sh`
    - `ops/ha/schedule_climate_temperature.sh`
    - `ops/ha/schedule_climate_mode.sh`
    - `ops/telegram-bridge/restart_and_verify.sh`

## Service

- Unit: `telegram-helper-bridge.service`
- Source-of-truth unit file: `infra/systemd/telegram-helper-bridge.service`
- Runtime user/group: `helperbot:helperbot`
- State root: `/home/helperbot/.local/state/telegram-helper-bridge`
