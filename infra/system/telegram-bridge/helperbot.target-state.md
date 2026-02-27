# Helper Bot Target State (Server3)

This document mirrors the intended live state for the dedicated helper Telegram bot runtime.

## Host User

- Linux user: `helperbot`
- Home: `/home/helperbot`
- Shell: `/bin/bash`
- Sudo group membership: none

## Access Prerequisites

- Helper workspace root:
  - `/home/helperbot/helperbot`
- Helper identity files in workspace root:
  - `AGENTS.md`
  - `HELPER_INSTRUCTION.md`

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
  - command paths are pinned to helper workspace under `/home/helperbot/helperbot`.

## Service

- Unit: `telegram-helper-bridge.service`
- Source-of-truth unit file: `infra/systemd/telegram-helper-bridge.service`
- Runtime user/group: `helperbot:helperbot`
- Runtime code root: `/home/helperbot/helperbot`
- State root: `/home/helperbot/.local/state/telegram-helper-bridge`
