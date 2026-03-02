# Live Change Record - 2026-03-02T18:05:35+10:00

## Objective
Fix Brave playback reliability on Server3 TV by removing toggle-prone click behavior and adding deterministic play control.

## Repo State
- Branch: `main`
- Repo: `/home/architect/matrix`

## Changes Applied
1. Updated pause helper:
   - `ops/tv-desktop/server3-tv-browser-youtube-pause.sh`
   - Removed player click step before media pause key.
2. Added deterministic play helper:
   - `ops/tv-desktop/server3-tv-browser-youtube-play.sh`
   - Focuses target browser window, then sends `XF86AudioPause` followed by `XF86AudioPlay`.
3. Updated Server3 script allowlist:
   - `src/telegram_bridge/handlers.py`
   - Added `ops/tv-desktop/server3-tv-browser-youtube-play.sh`.
4. Updated docs and target-state mirrors:
   - `docs/server3-tv-desktop.md`
   - `docs/telegram-architect-bridge.md`
   - `infra/system/desktop/server3-tv-desktop.target-state.md`
   - `SERVER3_SUMMARY.md`

## Verification Outcomes
1. Static checks:
   - `bash -n` for both pause/play scripts
   - `python3 -m py_compile src/telegram_bridge/handlers.py`
   - `python3 -m unittest tests/telegram_bridge/test_bridge_core.py -q` (`85 OK`)
2. Live check:
   - Initial run failed while desktop was stopped (`lightdm desktop is not active`).
   - Started desktop with `server3-tv-start`.
   - Opened Brave to a known YouTube URL.
   - `server3-tv-browser-youtube-play.sh brave` succeeded and returned Brave window id.
