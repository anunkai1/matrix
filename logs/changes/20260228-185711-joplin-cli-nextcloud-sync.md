# Change Log - Joplin CLI Nextcloud Sync on Server3

Timestamp: 2026-02-28T18:57:11+10:00
Timezone: Australia/Brisbane

## Objective
- Install Joplin CLI on Server3 and link it to Nextcloud for note sync.

## Scope
- In scope:
  - `ops/joplin/apply_server3.sh`
  - `ops/joplin/rollback_server3.sh`
  - `infra/system/joplin/server3.joplin-cli.target-state.md`
  - `infra/system/joplin/architect.joplin-sync.target-state.redacted.md`
  - `SERVER3_SUMMARY.md`
  - this `logs/changes` record
- Out of scope:
  - no Nextcloud server/database schema changes
  - no desktop GUI Joplin setup

## Changes Made
1. Added Joplin operations scripts:
   - `ops/joplin/apply_server3.sh`
   - `ops/joplin/rollback_server3.sh`
2. Added infra target-state records:
   - `infra/system/joplin/server3.joplin-cli.target-state.md`
   - `infra/system/joplin/architect.joplin-sync.target-state.redacted.md`
3. Ran apply script with approved credentials:
   - installed `joplin` CLI (user-level npm prefix `~/.local`)
   - configured `sync.target=5` (Nextcloud)
   - configured WebDAV path `https://mavali.top/remote.php/dav/files/admin/Joplin`
4. Resolved initial sync bootstrap issue:
   - first sync returned WebDAV `409 Parent node does not exist` for `locks/`
   - created remote folder via `MKCOL` on `.../Joplin` (`201 Created`)
   - re-ran sync successfully

## Validation
- `joplin version` shows `joplin 3.5.1 (prod, linux)`
- `joplin config sync.target` returns `5`
- `joplin config sync.5.path` returns `https://mavali.top/remote.php/dav/files/admin/Joplin`
- `joplin sync --use-lock 0` completed successfully after folder creation

## Notes
- App password was used only at runtime and is not committed to git.
- Credentials are stored in local Joplin profile config on Server3 as part of normal Joplin behavior.
