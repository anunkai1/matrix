# Live Change Record - 2026-03-02T17:19:00+10:00

## Objective
Add a `Server3 ...` keyword execution path so Telegram requests can route into deterministic Server3 desktop/browser operations from one natural-language sentence.

## Repo State
- Branch: `main`
- Repo: `/home/architect/matrix`

## Changes Applied
1. Added Server3 keyword routing in bridge handler:
   - new keyword extraction: `Server3` / `Server 3`
   - stateless priority mode prompt wrapper for Server3 operations
   - empty keyword-only guard message
   - memory bypass for priority keyword modes (`HA`, `Server3`)
2. Added deterministic Server3 helper scripts:
   - `ops/tv-desktop/server3-tv-open-browser-url.sh`
   - `ops/tv-desktop/server3-youtube-open-top-result.sh`
3. Added unit coverage for:
   - Server3 keyword parsing variants
   - Server3 keyword stateless routing
   - Server3 keyword empty-action rejection
   - help-text inclusion for `Server3 ...` usage
4. Updated docs:
   - `docs/telegram-architect-bridge.md`
   - `docs/server3-tv-desktop.md`
   - `infra/system/desktop/server3-tv-desktop.target-state.md`

## Verification Outcomes
- `python3 -m py_compile src/telegram_bridge/handlers.py` passed.
- `python3 -m unittest tests/telegram_bridge/test_bridge_core.py -q` passed.

## Notes
- `server3-youtube-open-top-result.sh` depends on `yt-dlp` + `jq`.
- If `yt-dlp` is missing, the script exits with install guidance.
