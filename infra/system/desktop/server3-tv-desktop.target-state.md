# Server3 TV Desktop Target State

## Intent
Provide a command-start desktop mode for HDMI TV use while keeping Server3 default boot in CLI mode.

## Live Paths (mirrored by repo templates)
- LightDM autologin config:
  - `/etc/lightdm/lightdm.conf.d/50-server3-tv-autologin.conf`
  - source: `infra/system/tv-desktop/lightdm/50-server3-tv-autologin.conf`
- Start/stop command wrappers:
  - `/usr/local/bin/server3-tv-start`
  - `/usr/local/bin/server3-tv-stop`
  - source: `infra/system/tv-desktop/usr-local-bin/`
- TV session startup assets:
  - `/home/tv/.local/bin/server3-tv-session-start.sh`
  - `/home/tv/.local/bin/server3-tv-audio.sh`
  - `/home/tv/.local/bin/server3-tv-display.sh`
  - `/home/tv/.config/autostart/server3-tv-brave.desktop`
  - source: `infra/system/tv-desktop/home-tv/`

## Runtime Policy
- Default boot target: `multi-user.target` (CLI)
- Desktop launch: on demand via `server3-tv-start`
- Desktop stop: via `server3-tv-stop`
- Browser: Brave, autostart maximized to YouTube
- Display preference: HDMI-only `1280x720` by default in every tv session
- Audio preference: first detected HDMI sink set as default in tv session

## User Model
- Desktop user: `tv`
- Local desktop account only
- Password locked
- No sudo membership

## Package Baseline
- `xorg`
- `lightdm`
- `lightdm-gtk-greeter`
- `xfce4`
- `xfce4-terminal`
- `dbus-x11`
- `pipewire-audio`
- `wireplumber`
- `pulseaudio-utils`
- `brave-browser`

## Live Additive Packages (Server3)
- `firefox` (Ubuntu transitional package installing snap `firefox`)
- Installed manually on 2026-03-02 for alternate TV desktop browser access.
- `yt-dlp`
- Installed manually on 2026-03-02 to enable deterministic YouTube top-result resolver script.
- `wmctrl`
- `xdotool`
- Installed manually on 2026-03-02 to support Firefox autoplay-block UI fallback (focus/click/play key).
- `libusb-0.1-4`
- Installed manually on 2026-04-25 for ITGmania's Linux runtime compatibility.

## Live Additive Applications (Server3)
- `ITGmania 1.2.1`
- Installed manually on 2026-04-25 from the official Linux tarball to `/opt/itgmania`.
- Source URL: `https://github.com/itgmania/itgmania/releases/download/v1.2.1/ITGmania-1.2.1-Linux.tar.gz`
- Runtime launcher:
  - `bash ops/tv-desktop/server3-tv-itgmania.sh`
- Launcher display default:
  - HDMI-only `1280x720`, matching ITGmania's generated render mode on Server3; override with `SERVER3_TV_ITGMANIA_MODE`.
- LTEK dance pad detected as:
  - USB: `03eb:8041 Atmel Corp. L-TEK Dance Pad PRO`
  - joystick: `/dev/input/js0`
  - event device: `/dev/input/event11`

## Operations
- Apply: `bash ops/tv-desktop/apply_server3.sh`
- Rollback: `bash ops/tv-desktop/rollback_server3.sh`
- Runtime helpers (repo scripts used by `Server3 TV ...` keyword executor):
  - `bash ops/tv-desktop/server3-tv-open-browser-url.sh <firefox|brave> <url>`
  - `bash ops/tv-desktop/server3-youtube-open-top-result.sh --query "<text>" [--min-duration-seconds <n>]`
  - `bash ops/tv-desktop/server3-tv-browser-youtube-pause.sh <brave|firefox>`
  - `bash ops/tv-desktop/server3-tv-browser-youtube-play.sh <brave|firefox>`
  - `bash ops/tv-desktop/server3-tv-itgmania.sh [--restart] [--no-fullscreen]`
