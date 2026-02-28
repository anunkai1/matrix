# Change Log - Joplin WebDAV Path Correction

Timestamp: 2026-02-28T19:11:27+10:00
Timezone: Australia/Brisbane

## Objective
- Correct Server3 Joplin sync path to user-provided WebDAV location and verify note visibility.

## Scope
- In scope:
  - local Joplin config (`sync.5.path`)
  - `infra/system/joplin/server3.joplin-cli.target-state.md`
  - `infra/system/joplin/architect.joplin-sync.target-state.redacted.md`
  - `SERVER3_SUMMARY.md`
  - this `logs/changes` record
- Out of scope:
  - no Nextcloud server changes
  - no credential rotation
  - no mobile/desktop client configuration changes

## Changes Made
1. Updated local Joplin sync path:
   - from `https://mavali.top/remote.php/dav/files/admin/Joplin`
   - to `https://mavali.top/remote.php/dav/files/admin/VladsPhoneMoto/Joplin`
2. Ran sync and verification commands:
   - `joplin sync --use-lock 0`
   - `joplin status`
   - `joplin ls / -l`
3. Updated infra target-state files to the corrected path.

## Validation
- Sync completed without HTTP auth/path errors.
- `joplin config sync.5.path` reflects corrected path.
- Current dataset remains empty after sync:
  - `Total: 0/0`
  - no notebooks listed

## Notes
- The corrected WebDAV path is active on Server3.
- If notes still do not appear, source devices may be syncing to a different endpoint/account or have not pushed data yet.
