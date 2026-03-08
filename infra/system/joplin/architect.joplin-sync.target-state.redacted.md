# Architect Joplin Sync Target State (Redacted)

- Timestamp (Australia/Brisbane ISO-8601): 2026-02-28T19:11:27+10:00
- Owner: `architect`
- Sync direction (initial bootstrap): `pull from Nextcloud`

## Sync Endpoint
- Base URL: `https://mavali.top`
- WebDAV path: `/remote.php/dav/files/admin/VladsPhoneMoto/Joplin`
- Full sync path: `https://mavali.top/remote.php/dav/files/admin/VladsPhoneMoto/Joplin`

## Credentials
- Username: `admin`
- App password: redacted (stored only in local Joplin profile config, not in git)

## Validation Targets
- `joplin version` returns installed version
- `joplin config sync.target` returns `5`
- `joplin sync --use-lock 0` completes without HTTP auth/path errors
- `systemctl status joplin-architect-sync.timer` shows the timer active
- `systemctl list-timers joplin-architect-sync.timer` shows the next 5-minute run
- current remote dataset may still be empty (`0/0`) until source clients sync into this path
