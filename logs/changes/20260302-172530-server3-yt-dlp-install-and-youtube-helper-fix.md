# Live Change Record - 2026-03-02T17:25:30+10:00

## Objective
Enable Server3 one-sentence YouTube top-result playback helper end-to-end by installing missing runtime dependency (`yt-dlp`) and validating/fixing helper execution on this host.

## Repo State
- Branch: `main`
- Repo: `/home/architect/matrix`

## Live Changes Applied
1. Installed package:
   - `sudo apt-get update`
   - `sudo apt-get install -y yt-dlp`
2. Verified dependency:
   - `command -v yt-dlp` -> `/usr/bin/yt-dlp`
   - `yt-dlp --version` -> `2024.04.09`

## Runtime Finding + Fix
- Initial helper run failed minimum-duration check because this host's `yt-dlp --dump-single-json ytsearch1:` returned null top-entry fields.
- Updated script `ops/tv-desktop/server3-youtube-open-top-result.sh` to use a reliable host-compatible extraction path:
  - `yt-dlp --flat-playlist --print '%(id)s|%(title)s|%(duration)s' "ytsearch1:<query>"`
  - parse `id/title/duration` deterministically
  - build canonical watch URL from `id`

## Verification Outcomes
1. Script syntax check passed:
   - `bash -n ops/tv-desktop/server3-youtube-open-top-result.sh`
2. End-to-end helper run passed:
   - `bash ops/tv-desktop/server3-youtube-open-top-result.sh --query "deephouse 2026" --browser firefox --min-duration-seconds 1`
   - Output:
     - `[server3-tv-open-browser-url] launched browser=firefox url=https://www.youtube.com/watch?v=9HDkGAgIdMo&autoplay=1`
     - `[server3-youtube-open-top-result] query=deephouse 2026 ... duration_seconds=3635 ...`
3. Service health after package-triggered restarts (`needrestart`):
   - `telegram-architect-bridge.service` active
   - `telegram-tank-bridge.service` active
   - `telegram-architect-whatsapp-bridge.service` active

## Repo Mirrors Updated
- `ops/tv-desktop/server3-youtube-open-top-result.sh`
- `docs/server3-tv-desktop.md`
- `infra/system/desktop/server3-tv-desktop.target-state.md`
- `SERVER3_SUMMARY.md`
- `logs/changes/20260302-172530-server3-yt-dlp-install-and-youtube-helper-fix.md`
