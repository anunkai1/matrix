# Change Record - 2026-02-28

- Timestamp (Australia/Brisbane): 2026-02-28T08:56:45+10:00
- Change type: live + repo mirror
- Objective: Apply H3 restart restriction to live sudoers so Tank can only restart its own bridge unit.

## What Changed
- Backed up live sudoers file:
  - `/etc/sudoers.d/tank-telegram-ha.bak.20260228-085645`
- Applied repo mirror to live path:
  - source: `infra/system/sudoers/tank-telegram-ha`
  - destination: `/etc/sudoers.d/tank-telegram-ha`
- Effective live restart rule is now restricted to:
  - `/home/architect/matrix/ops/telegram-bridge/restart_and_verify.sh --unit telegram-tank-bridge.service`

## Verification
- `sudo -n visudo -cf /etc/sudoers.d/tank-telegram-ha`
  - Result: `parsed OK`
- `sudo -n cat /etc/sudoers.d/tank-telegram-ha`
  - Result: file contents match repo mirror restriction.
- `sudo -n -l -U tank`
  - Result: Tank command allowlist shows only restricted restart form (no wildcard restart argument).

## Rollback
- Restore backup:
  - `sudo cp -a /etc/sudoers.d/tank-telegram-ha.bak.20260228-085645 /etc/sudoers.d/tank-telegram-ha`
- Re-validate:
  - `sudo visudo -cf /etc/sudoers.d/tank-telegram-ha`

## Notes
- This closes the remaining live gap after the prior repo-only H3 hardening commit.
