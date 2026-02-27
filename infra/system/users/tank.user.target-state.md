# Server3 User Target State - tank

Last verified: 2026-02-27T14:25:37+10:00

## Objective
Track the intended baseline for the `tank` Linux user on Server3.

## Current State
- User: `tank`
- UID/GID: `1002:1002`
- Home: `/home/tank`
- Shell: `/bin/bash`
- Telegram runtime workspace: `/home/tank/tankbot` (code-only)
- Primary group: `tank`
- Supplementary groups: none
- Sudo privileges: scoped allowlist via `/etc/sudoers.d/tank-telegram-ha`

## Validation Commands
- `id tank`
- `getent passwd tank`
- `ls -ld /home/tank`
- `sudo -l -U tank`
