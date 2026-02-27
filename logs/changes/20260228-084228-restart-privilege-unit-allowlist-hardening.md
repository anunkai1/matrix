# Change Record - 2026-02-28

- Timestamp (Australia/Brisbane): 2026-02-28T08:42:28+10:00
- Change type: repo-only
- Objective: Close H3 by restricting restart privileges to approved Telegram bridge units only.

## What Changed
- Updated `ops/telegram-bridge/restart_and_verify.sh`:
  - added explicit allowlist for restartable units:
    - `telegram-architect-bridge.service`
    - `telegram-tank-bridge.service`
  - added validation to reject non-allowlisted `UNIT_NAME` values before any sudo/systemctl execution.
- Updated sudoers mirror `infra/system/sudoers/tank-telegram-ha`:
  - narrowed restart permission from broad wildcard:
    - `/home/architect/matrix/ops/telegram-bridge/restart_and_verify.sh *`
  - to exact tank restart shape:
    - `/home/architect/matrix/ops/telegram-bridge/restart_and_verify.sh --unit telegram-tank-bridge.service`

## Verification
- `bash -n ops/telegram-bridge/restart_and_verify.sh`
  - Result: pass
- `bash ops/telegram-bridge/restart_and_verify.sh --unit ssh.service`
  - Result: rejected with allowlist error, exit `1`
- `python3 -m unittest discover -s tests -v`
  - Result: `Ran 52 tests` -> `OK`

## Notes
- This is a repo-side hardening change; no live `/etc/sudoers.d` file was modified in this step.
- To apply the sudoers hardening live, mirror this change to `/etc/sudoers.d/tank-telegram-ha` in a separate live rollout task.
