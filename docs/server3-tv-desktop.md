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
  - `ops/tv-desktop/server3-tv-itgmania.sh`

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

Launch ITGmania full-screen on the HDMI desktop:
```bash
bash ops/tv-desktop/server3-tv-itgmania.sh
bash ops/tv-desktop/server3-tv-itgmania.sh --restart
```

The launcher defaults the HDMI X session to `1920x1080` at `119.88Hz` for lower display latency on the current TV. Override with `SERVER3_TV_ITGMANIA_MODE` and `SERVER3_TV_ITGMANIA_RATE` if a different display needs the earlier `1280x720` behavior.

Before fresh launches, the ITGmania helper also keeps the game preferences on the low-latency path: true fullscreen at `1920x1080`, vsync off, and input debounce `0`. Override the saved game render size with `SERVER3_TV_ITGMANIA_DISPLAY_WIDTH`, `SERVER3_TV_ITGMANIA_DISPLAY_HEIGHT`, and `SERVER3_TV_ITGMANIA_REFRESH_RATE`.

The installed Server3 build is ITGmania `1.2.1` under `/opt/itgmania`, installed from the official Linux tarball at `https://github.com/itgmania/itgmania/releases/download/v1.2.1/ITGmania-1.2.1-Linux.tar.gz`. The LTEK pad currently enumerates as `/dev/input/js0` (`LTEK L-TEK Dance Pad PRO`). The launcher enforces the L-TEK button order in `/home/tv/.itgmania/Save/Keymaps.ini`: left `Joy1_B1`, right `Joy1_B2`, up `Joy1_B3`, down `Joy1_B4`.

Installed song packs:
- `Club Fantastic Season 1` and `Club Fantastic Season 2` are bundled with the ITGmania install.
- `GG Basics` is installed under `/opt/itgmania/Songs/GG Basics`. It was downloaded from StepMania Online pack ID `1745` (`https://stepmaniaonline.net/download/pack/1745/`) on 2026-04-25 and contains 22 `.ssc` pop-song charts.
- `V` is installed under `/opt/itgmania/Songs/V` for individually added requested songs. It currently contains:
  - `Starships` by Nicki Minaj, downloaded from ZIv simfile ID `23437` (`https://zenius-i-vanisher.com/v5.2/viewsimfile.php?simfileid=23437`) on 2026-04-25. The local `.sm` chart meters are Beginner `1`, Basic/Easy `4`, Difficult/Medium `6`, and Expert/Hard `10`.
  - `Macarena` by 2 Locos In A Room, downloaded from ZIv simfile ID `40892` (`https://zenius-i-vanisher.com/v5.2/viewsimfile.php?simfileid=40892`) on 2026-04-25. The local `.sm` single chart meters are Basic/Easy `2`, Difficult/Medium `3`, and Expert/Hard `6`; double meters are Basic/Easy `2` and Difficult/Medium `4`.
  - `Mambo NO.5` by Lou Bega, downloaded from ZIv simfile ID `64122` (`https://zenius-i-vanisher.com/v5.2/viewsimfile.php?simfileid=64122`) on 2026-04-25. The local `.sm` single chart meter is Difficult/Medium `5`.
  - `DRAGOSTEA DIN TEI` by O-Zone, downloaded from ZIv simfile ID `35635` (`https://zenius-i-vanisher.com/v5.2/viewsimfile.php?simfileid=35635`) on 2026-04-25. The local `.sm` single chart meters are Beginner `1`, Basic/Easy `3`, Difficult/Medium `4`, and Expert/Hard `7`, with an edit chart at `6`.

Note:
- `server3-youtube-open-top-result.sh` requires `yt-dlp`.
- For Firefox autoplay-block fallback (focus + click + `k` play key), install:
  - `wmctrl`
  - `xdotool`
- ITGmania requires the compatibility package `libusb-0.1-4`.
- Install if needed:
```bash
sudo apt-get install -y yt-dlp wmctrl xdotool libusb-0.1-4
```

## TV Session Behavior
- LightDM autologins `tv` only when desktop is started.
- Xfce autostarts `server3-tv-session-start.sh`.
- The session bootstrap only prepares display/audio state; it does not force any browser open.
- The session bootstrap disables XFCE window-manager compositing for lower display latency.
- The display bootstrap runs `server3-tv-display.sh`, making HDMI the only active output at `1280x720` by default for the base Server3 TV session. The ITGmania launcher switches HDMI to its own low-latency `1920x1080@119.88Hz` mode before launching the game.
- Browser windows are opened by `server3-tv-open-browser-url.sh` or the YouTube helper when explicitly requested.
- Firefox launches with a dedicated TV-only profile path so it does not collide with stale/default-profile state.
- ITGmania launches only when explicitly requested through `server3-tv-itgmania.sh`; the helper reuses an existing game process unless `--restart` is passed.

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
