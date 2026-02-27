# Live Change Record - 2026-02-27T13:46:59+10:00

## Objective
Move `telegram-helper-bridge.service` to a dedicated helper-owned workspace so HelperBot has its own identity files (`AGENTS.md`, `HELPER_INSTRUCTION.md`) and no longer inherits Architect workspace identity by default.

## Repo State
- Branch: `main`
- Repo: `/home/architect/matrix`

## Live Changes Applied
1. Created safety backups:
   - `/etc/systemd/system/telegram-helper-bridge.service.bak.20260227-134534`
   - `/etc/default/telegram-helper-bridge.bak.20260227-134534`
   - `/etc/sudoers.d/helperbot-telegram-ha.bak.20260227-134534`
2. Deployed helper workspace:
   - Command: `bash ops/telegram-bridge/deploy_helper_workspace.sh apply`
   - Path: `/home/helperbot/helperbot`
   - Helper identity files installed in workspace root:
     - `AGENTS.md`
     - `HELPER_INSTRUCTION.md`
3. Switched helper unit to helper workspace paths:
   - `WorkingDirectory=/home/helperbot/helperbot`
   - `ExecStart=/usr/bin/python3 /home/helperbot/helperbot/src/telegram_bridge/main.py`
   - `TELEGRAM_EXECUTOR_CMD=/home/helperbot/helperbot/src/telegram_bridge/executor_helper.sh`
4. Updated live helper env:
   - `/etc/default/telegram-helper-bridge`
   - Added: `TELEGRAM_ASSISTANT_NAME=HelperBot`
   - Updated executor path to helper workspace.
5. Updated live helper sudoers allowlist:
   - `/etc/sudoers.d/helperbot-telegram-ha`
   - Allowed script paths now pinned to `/home/helperbot/helperbot/...`
   - Validation: `visudo -cf /etc/sudoers.d/helperbot-telegram-ha` -> parsed OK.
6. Reloaded and restarted helper service.

## Verification
- Service active with new runtime path:
  - `ExecMainStartTimestamp=Fri 2026-02-27 13:46:25 AEST`
  - `MainPID=459256`
  - Process command:
    - `/usr/bin/python3 /home/helperbot/helperbot/src/telegram_bridge/main.py`
- Startup log confirms helper identity/executor path:
  - `HelperBot-only routing active for all allowlisted chats.`
  - `Executor command=['/home/helperbot/helperbot/src/telegram_bridge/executor_helper.sh']`
- Effective sudo policy for helperbot confirmed:
  - `sudo -iu helperbot sudo -l` shows only helper-workspace pinned commands.

## Repo Mirrors Updated
- `infra/systemd/telegram-helper-bridge.service`
- `infra/env/telegram-helper-bridge.env.example`
- `infra/env/telegram-helper-bridge.server3.redacted.env`
- `infra/system/sudoers/helperbot-telegram-ha`
- `infra/system/telegram-bridge/helperbot.target-state.md`
- `infra/helperbot/AGENTS.md`
- `infra/helperbot/HELPER_INSTRUCTION.md`
- `ops/telegram-bridge/deploy_helper_workspace.sh`
- `SERVER3_SUMMARY.md`
