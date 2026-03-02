# Live Change Record - 2026-03-02T17:48:29+10:00

## Objective
Add deterministic primitives for the complex Server3 browser flow: pause Brave YouTube playback, then reuse existing Firefox window for top-result playback.

## Repo State
- Branch: `main`
- Repo: `/home/architect/matrix`

## Changes Applied
1. Added new script:
   - `ops/tv-desktop/server3-tv-browser-youtube-pause.sh`
   - Focuses target browser (`brave`/`firefox`) and sends explicit media pause key.
2. Enhanced existing URL opener:
   - `ops/tv-desktop/server3-tv-open-browser-url.sh`
   - Reuses existing browser window by default (`Ctrl+L` + URL + Enter).
   - Supports optional `--new-window` override.
3. Updated Server3 script allowlist in bridge prompt wrapper:
   - `src/telegram_bridge/handlers.py`
   - Added `ops/tv-desktop/server3-tv-browser-youtube-pause.sh`.
4. Updated docs/target-state entries for new behavior and helper availability.

## Verification Outcomes
1. Static checks passed:
   - `bash -n` on changed scripts
   - `python3 -m py_compile src/telegram_bridge/handlers.py`
   - `python3 -m unittest tests/telegram_bridge/test_bridge_core.py -q` (`85 OK`)
2. Live sequence check passed:
   - `bash ops/tv-desktop/server3-tv-open-browser-url.sh brave https://www.youtube.com/watch?v=9HDkGAgIdMo`
     - output: `reused_existing_window=1`
   - `bash ops/tv-desktop/server3-tv-browser-youtube-pause.sh brave`
     - output includes Brave window id
   - `bash ops/tv-desktop/server3-youtube-open-top-result.sh --query "history legends" --browser firefox`
     - output: `reused_existing_window=1` and `playback_fallback_attempted=1`

## Repo Mirrors Updated
- `ops/tv-desktop/server3-tv-browser-youtube-pause.sh`
- `ops/tv-desktop/server3-tv-open-browser-url.sh`
- `src/telegram_bridge/handlers.py`
- `docs/server3-tv-desktop.md`
- `docs/telegram-architect-bridge.md`
- `infra/system/desktop/server3-tv-desktop.target-state.md`
- `SERVER3_SUMMARY.md`
- `logs/changes/20260302-174829-server3-brave-pause-firefox-reuse.md`
