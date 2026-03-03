# Live Change Record - 2026-03-02T23:36:46+10:00

## Objective
Add `Nextcloud ...` keyword routing with deterministic ops scripts, and change Server3 desktop keyword trigger from `Server3 ...` to `Server3 TV ...`.

## Changes Applied
1. Bridge routing updates in `src/telegram_bridge/handlers.py`:
   - Added `extract_nextcloud_keyword_request()` and `build_nextcloud_keyword_prompt()`.
   - Added Nextcloud script allowlist.
   - Added `Nextcloud` keyword stateless priority routing.
   - Updated Server3 keyword parsing to require `Server3 TV` prefix.
   - Updated help text to show `Server3 TV ...` and `Nextcloud ...` usage.
2. Added deterministic Nextcloud ops scripts:
   - `ops/nextcloud/nextcloud-common.sh`
   - `ops/nextcloud/nextcloud-files-list.sh`
   - `ops/nextcloud/nextcloud-file-upload.sh`
   - `ops/nextcloud/nextcloud-file-delete.sh`
   - `ops/nextcloud/nextcloud-calendars-list.sh`
   - `ops/nextcloud/nextcloud-calendar-create-event.sh`
3. Added docs/mirrors:
   - `docs/nextcloud-ops.md`
   - `infra/env/nextcloud-ops.env.example`
   - `infra/env/nextcloud-ops.server3.redacted.env`
   - `infra/system/nextcloud/server3.nextcloud-ops.target-state.md`
   - `docs/telegram-architect-bridge.md`
   - `SERVER3_SUMMARY.md`

## Live Secret Path
- `/home/architect/.config/nextcloud/ops.env` (not in git)

## Verification Outcomes
1. `python3 -m py_compile src/telegram_bridge/handlers.py`
2. `bash -n` on new Nextcloud scripts
3. `python3 -m unittest tests/telegram_bridge/test_bridge_core.py -q` (`88 OK`)
4. Live script checks:
   - `nextcloud-files-list.sh /` returned expected root listing.
   - `nextcloud-calendars-list.sh` returned expected calendar inventory.
   - `nextcloud-file-upload.sh` + `nextcloud-file-delete.sh` succeeded (`201` then `204`) for a temporary file.
