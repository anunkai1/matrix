# Server3 TV Desktop (Command-Start)

This runbook configures Server3 for HDMI TV usage while keeping default boot in CLI mode.

## What It Does
- Keeps default boot target as `multi-user.target` (CLI).
- Installs Xfce + LightDM + Brave.
- Creates dedicated `tv` desktop user (locked password, no sudo).
- Adds on-demand desktop commands:
  - `server3-tv-start`
  - `server3-tv-stop`
- Starts to a neutral desktop session; browsers open only when explicitly requested.
- Firefox and Brave are both supported on demand.
- Prefers HDMI audio sink in the `tv` session.
- Includes helper scripts for intent-executor flows:
  - `ops/tv-desktop/server3-tv-open-browser-url.sh`
  - `ops/tv-desktop/server3-tv-brave-browser-brain-session.sh`
  - `ops/tv-desktop/server3-youtube-open-top-result.sh`
  - `ops/tv-desktop/server3-tv-browser-youtube-pause.sh`
  - `ops/tv-desktop/server3-tv-browser-youtube-play.sh`

## Apply
```bash
cd ~/matrix
bash ops/tv-desktop/apply_server3.sh
```

## Daily Use
Start desktop from local keyboard or SSH:
```bash
server3-tv-start
```

Stop desktop and return to CLI-only operation:
```bash
server3-tv-stop
```

Open a URL in Firefox/Brave under the `tv` desktop session:
```bash
bash ops/tv-desktop/server3-tv-open-browser-url.sh firefox https://www.youtube.com
```
By default, if a matching browser window already exists, it is reused (`Ctrl+L` + URL + Enter). Use `--new-window` to force a new window.

Open a visible Brave session intended for Browser Brain CDP attach:
```bash
bash ops/tv-desktop/server3-tv-brave-browser-brain-session.sh https://x.com/home
```
This launches Brave for the `tv` desktop user with a local remote-debugging port and a dedicated profile so Browser Brain can attach to it later without needing headed mode itself.

Resolve and open top YouTube search result (with optional duration constraint):
```bash
bash ops/tv-desktop/server3-youtube-open-top-result.sh --query "deephouse 2026"
bash ops/tv-desktop/server3-youtube-open-top-result.sh --query "mersheimer" --min-duration-seconds 600
```

Pause currently focused YouTube playback in a target browser window:
```bash
bash ops/tv-desktop/server3-tv-browser-youtube-pause.sh brave
bash ops/tv-desktop/server3-tv-browser-youtube-pause.sh firefox
```

Force deterministic YouTube playback in a target browser window:
```bash
bash ops/tv-desktop/server3-tv-browser-youtube-play.sh brave
bash ops/tv-desktop/server3-tv-browser-youtube-play.sh firefox
```

Note:
- `server3-youtube-open-top-result.sh` requires `yt-dlp`.
- For Firefox autoplay-block fallback (focus + click + `k` play key), install:
  - `wmctrl`
  - `xdotool`
- Install if needed:
```bash
sudo apt-get install -y yt-dlp wmctrl xdotool
```

## TV Session Behavior
- LightDM autologins `tv` only when desktop is started.
- Xfce autostarts `server3-tv-session-start.sh`.
- The session bootstrap only prepares display/audio state; it does not force any browser open.
- Browser windows are opened by `server3-tv-open-browser-url.sh` or the YouTube helper when explicitly requested.
- Firefox launches with a dedicated TV-only profile path so it does not collide with stale/default-profile state.

## Audio Routing
At session start, `server3-tv-audio.sh`:
- detects the first HDMI sink from `pactl list short sinks`
- sets it as default sink
- moves active sink inputs to HDMI

If needed, use `pavucontrol` inside desktop for manual output selection.

## Rollback
```bash
cd ~/matrix
bash ops/tv-desktop/rollback_server3.sh
```

Optional full removal:
```bash
cd ~/matrix
bash ops/tv-desktop/rollback_server3.sh --remove-packages --remove-user
```
