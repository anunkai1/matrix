# Live Change Record - 2026-03-01T13:21:24+10:00

## Objective
Isolate Tank Joplin access into a dedicated profile and dedicated WebDAV folder so Tank cannot access the prior shared Joplin dataset.

## Repo State
- Branch: `main`
- Repo: `/home/architect/matrix`

## Live Changes Applied
1. Created/validated Tank isolated Joplin profile:
   - Active profile: `/home/tank/.config/joplin-tank`
   - Sync target: `5` (Nextcloud)
   - Sync path: `https://mavali.top/remote.php/dav/files/admin/VladsPhoneMoto/Joplin-Tank`
2. Reused same credentials/account:
   - Username: `admin`
   - Existing app password reused from current local Tank Joplin secure config.
3. Initialized Tank-only notebook set:
   - Created notebook `Tank`
   - Synced isolated profile (`sync --use-lock 0`)
4. Removed Tank access to previous shared profile:
   - Old profile path removed: `/home/tank/.config/joplin`
   - Backup archives created:
     - `/home/architect/backups/20260301-132026-tank-joplin-isolation-redo`
     - `/home/architect/backups/20260301-132055-tank-joplin-shared-profile-final`
5. Pinned Tank runtime to isolated profile:
   - Updated `/etc/default/telegram-tank-bridge` with:
     - `JOPLIN_PROFILE=/home/tank/.config/joplin-tank`
   - Restarted `telegram-tank-bridge.service`

## Verification Evidence
- `sudo -u tank bash -lc 'joplin --profile ~/.config/joplin-tank config sync.5.path'`
  - `https://mavali.top/remote.php/dav/files/admin/VladsPhoneMoto/Joplin-Tank`
- `sudo -u tank bash -lc 'joplin --profile ~/.config/joplin-tank ls / -l'`
  - shows only notebook `Tank`
- `sudo -u tank bash -lc 'joplin --profile ~/.config/joplin-tank status'`
  - `Folder: 1/1`, `Total: 1/1`, `Tank: 0 notes`
- `sudo -u tank bash -lc 'ls -ld ~/.config/joplin ~/.config/joplin-tank 2>/dev/null || true'`
  - only `/home/tank/.config/joplin-tank` exists
- `sudo grep '^JOPLIN_PROFILE=' /etc/default/telegram-tank-bridge`
  - `JOPLIN_PROFILE=/home/tank/.config/joplin-tank`
- `sudo systemctl is-active telegram-tank-bridge.service`
  - `active`

## Repo Mirrors Updated
- `infra/env/telegram-tank-bridge.server3.redacted.env`
- `infra/system/joplin/tank.joplin-sync.target-state.redacted.md`
- `SERVER3_SUMMARY.md`

## Notes
- During implementation, an intermediate attempt copied legacy notes into `joplin-tank`; this was corrected in-session by rebuilding `joplin-tank` from a clean profile before final verification.
