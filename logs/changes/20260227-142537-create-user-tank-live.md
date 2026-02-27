# Live Change Record - 2026-02-27T14:25:37+10:00

## Objective
Create a clean baseline Linux user `tank` on Server3.

## Repo State
- Branch: `main`
- Repo: `/home/architect/matrix`

## Live Changes Applied
1. Pre-check:
   - `id tank` confirmed user did not exist.
2. Created user:
   - `useradd -m -s /bin/bash tank`

## Verification
- `id tank` -> `uid=1002(tank) gid=1002(tank) groups=1002(tank)`
- `getent passwd tank` -> home `/home/tank`, shell `/bin/bash`
- `ls -ld /home/tank` -> directory exists and owned by `tank:tank`
- `sudo -l -U tank` -> `User tank is not allowed to run sudo on server3.`

## Repo Mirrors Updated
- Added:
  - `infra/system/users/tank.user.target-state.md`
- Updated:
  - `SERVER3_SUMMARY.md`
