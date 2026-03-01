# Live Change Record - 2026-03-01T10:21:18+10:00

## Objective
Enable Joplin access for user `tank` so Tank can read/manage notes and to-do lists via local CLI.

## Repo State
- Branch: `main`
- Repo: `/home/architect/matrix`

## Live Changes Applied
1. Installed Joplin CLI for `tank`:
   - Command: `sudo -u tank ... npm install -g joplin`
   - Binary: `/home/tank/.local/bin/joplin`
2. Bootstrapped Tank Joplin profile from existing Server3 profile state:
   - Source: `/home/architect/.config/joplin/`
   - Destination: `/home/tank/.config/joplin/`
3. Added service PATH to include Tank user-local binaries:
   - File: `/etc/default/telegram-tank-bridge`
   - Added: `PATH=/home/tank/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin`
4. Restarted bridge service:
   - `sudo systemctl restart telegram-tank-bridge.service`

## Verification Evidence
- `sudo -u tank bash -lc 'command -v joplin'` -> `/home/tank/.local/bin/joplin`
- `sudo -u tank bash -lc 'joplin version | head -n 6'` -> `joplin 3.5.1 (prod, linux)`
- `sudo -u tank bash -lc 'joplin config sync.target'` -> `5`
- `sudo -u tank bash -lc 'joplin config sync.5.path'` -> `https://mavali.top/remote.php/dav/files/admin/VladsPhoneMoto/Joplin`
- `sudo -u tank bash -lc 'joplin config sync.5.username'` -> `admin`
- `sudo systemctl is-active telegram-tank-bridge.service` -> `active`

## Repo Mirrors Updated
- `infra/env/telegram-tank-bridge.server3.redacted.env`
- `infra/system/joplin/tank.joplin-sync.target-state.redacted.md`
- `SERVER3_SUMMARY.md`

## Notes
- npm install output includes upstream deprecation warnings from transitive dependencies; install completed successfully.
- Existing transient Telegram API/network poll errors in historical journals are unchanged by this Joplin setup.
