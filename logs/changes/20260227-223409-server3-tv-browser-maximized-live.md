# Live Change Record - 2026-02-27T22:34:09+10:00

## Objective
Change TV startup browser mode from fullscreen to maximized for `server3-tv-start` sessions.

## Repo State
- Branch: `main`
- Repo: `/home/architect/matrix`

## Changes Applied
1. Updated TV session startup template:
   - `infra/system/tv-desktop/home-tv/.local/bin/server3-tv-session-start.sh`
   - changed Brave flag:
     - `--start-fullscreen` -> `--start-maximized`
2. Deployed updated script to live tv user path:
   - `/home/tv/.local/bin/server3-tv-session-start.sh`
   - owner/group confirmed `tv:tv`

## Verification
- Live script content confirms `--start-maximized` is present.
- `--start-fullscreen` is no longer present in live startup script.

## Repo Artifacts Updated
- `infra/system/tv-desktop/home-tv/.local/bin/server3-tv-session-start.sh`
- `logs/changes/20260227-223409-server3-tv-browser-maximized-live.md`
- `SERVER3_SUMMARY.md`
