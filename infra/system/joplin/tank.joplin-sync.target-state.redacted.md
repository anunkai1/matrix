# Tank Joplin Sync Target State (Redacted)

- Timestamp (Australia/Brisbane ISO-8601): 2026-03-01T10:21:18+10:00
- Owner: `tank`
- Sync direction (bootstrap): copied existing profile state, then validated local CLI/config

## Runtime Components
- User-level npm prefix: `~/.local`
- Joplin binary: `~/.local/bin/joplin`
- Joplin profile: `~/.config/joplin`

## Sync Endpoint
- Base URL: `https://mavali.top`
- WebDAV path: `/remote.php/dav/files/admin/VladsPhoneMoto/Joplin`
- Full sync path: `https://mavali.top/remote.php/dav/files/admin/VladsPhoneMoto/Joplin`

## Credentials
- Username: `admin`
- App password: redacted (stored only in local Joplin profile config, not in git)

## Validation Targets
- `sudo -u tank bash -lc 'command -v joplin'` returns `/home/tank/.local/bin/joplin`
- `sudo -u tank bash -lc 'joplin version'` reports current CLI version
- `sudo -u tank bash -lc 'joplin config sync.target'` returns `5`
- `sudo -u tank bash -lc 'joplin config sync.5.path'` returns the path above
