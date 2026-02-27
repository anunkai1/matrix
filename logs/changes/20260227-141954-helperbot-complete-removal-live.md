# Live Change Record - 2026-02-27T14:19:54+10:00

## Objective
Completely remove HelperBot runtime from Server3, including helper service, helper live configuration, and the `helperbot` Linux account/home.

## Repo State
- Branch: `main`
- Repo: `/home/architect/matrix`

## Live Changes Applied
1. Stopped and disabled helper service:
   - `telegram-helper-bridge.service`
2. Removed helper live service/config artifacts:
   - `/etc/systemd/system/telegram-helper-bridge.service`
   - `/etc/default/telegram-helper-bridge`
   - `/etc/default/ha-ops-helper`
   - `/etc/sudoers.d/helperbot-telegram-ha`
3. Reloaded systemd state:
   - `systemctl daemon-reload`
   - `systemctl reset-failed`
4. Removed helper runtime account and data:
   - deleted Linux user/group `helperbot`
   - removed `/home/helperbot`

## Verification
- `id helperbot` -> `no such user`
- `systemctl status telegram-helper-bridge.service` -> `Unit ... could not be found`
- `systemctl is-enabled telegram-helper-bridge.service` -> `not-found`
- `systemctl is-active telegram-helper-bridge.service` -> `inactive`
- `/home/helperbot` absent
- helper live files above absent

## Repo Mirrors Updated
- Removed helper-only source-of-truth artifacts:
  - `infra/env/ha-ops-helper.server3.redacted.env`
  - `infra/env/telegram-helper-bridge.env.example`
  - `infra/env/telegram-helper-bridge.server3.redacted.env`
  - `infra/helperbot/AGENTS.md`
  - `infra/helperbot/HELPER_INSTRUCTION.md`
  - `infra/system/sudoers/helperbot-telegram-ha`
  - `infra/system/telegram-bridge/helperbot.target-state.md`
  - `infra/systemd/telegram-helper-bridge.service`
  - `ops/telegram-bridge/deploy_helper_workspace.sh`
  - `src/telegram_bridge/executor_helper.sh`
- Updated:
  - `SERVER3_SUMMARY.md`
