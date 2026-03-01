# Tank Joplin Sync Target State (Redacted)

- Timestamp (Australia/Brisbane ISO-8601): 2026-03-01T13:43:58+10:00
- Owner: `tank`
- Sync direction: isolated profile + dedicated WebDAV folder for Tank-only data

## Runtime Components
- User-level npm prefix: `~/.local`
- Joplin binary: `~/.local/bin/joplin`
- Joplin profile (active): `~/.config/joplin-tank`
- Joplin profile (legacy shared): removed from Tank home after backup

## Sync Endpoint
- Base URL: `https://mavali.top`
- WebDAV path: `/remote.php/dav/files/admin/VladsPhoneMoto/Joplin-Tank`
- Full sync path: `https://mavali.top/remote.php/dav/files/admin/VladsPhoneMoto/Joplin-Tank`

## Credentials
- Username: `admin`
- App password: redacted (stored only in local Joplin profile config, not in git)
- Latest app-password update applied live: `2026-03-01T13:43:58+10:00`

## Validation Targets
- `sudo -u tank bash -lc 'command -v joplin'` returns `/home/tank/.local/bin/joplin`
- `sudo -u tank bash -lc 'joplin --profile ~/.config/joplin-tank config sync.target'` returns `5`
- `sudo -u tank bash -lc 'joplin --profile ~/.config/joplin-tank config sync.5.path'` returns the path above
- `sudo -u tank bash -lc 'joplin --profile ~/.config/joplin-tank ls / -l'` shows notebook `Tank`
- `/etc/default/telegram-tank-bridge` includes:
  - `JOPLIN_PROFILE=/home/tank/.config/joplin-tank`
