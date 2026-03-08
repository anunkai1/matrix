# Server3 Joplin CLI Target State

- Timestamp (Australia/Brisbane ISO-8601): 2026-02-28T19:11:27+10:00
- Scope: local Joplin CLI runtime for user `architect` with Nextcloud WebDAV sync target

## Runtime Components
- User-level npm prefix: `~/.local`
- Joplin binary: `~/.local/bin/joplin`
- Joplin profile: `~/.config/joplin`
- Automatic sync timer: `joplin-architect-sync.timer`
- Automatic sync service: `joplin-architect-sync.service`

## Target Sync Configuration
- `sync.target`: `5` (Nextcloud)
- `sync.5.path`: `https://mavali.top/remote.php/dav/files/admin/VladsPhoneMoto/Joplin`
- `sync.5.username`: `admin`
- `sync.5.password`: set locally at runtime (redacted, never committed)
- Automatic sync cadence: every 5 minutes via systemd timer

## Apply / Rollback
- Apply: `bash ops/joplin/apply_server3.sh --url https://mavali.top --username admin --app-password '<secret>' --webdav-path /remote.php/dav/files/admin/VladsPhoneMoto/Joplin --direction pull`
- Rollback: `bash ops/joplin/rollback_server3.sh` (add `--purge-profile` to remove local profile)
