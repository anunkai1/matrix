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
  - `/home/tv/.config/autostart/server3-tv-brave.desktop`
  - source: `infra/system/tv-desktop/home-tv/`

## Runtime Policy
- Default boot target: `multi-user.target` (CLI)
- Desktop launch: on demand via `server3-tv-start`
- Desktop stop: via `server3-tv-stop`
- Browser: Brave, autostart fullscreen to YouTube
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

## Operations
- Apply: `bash ops/tv-desktop/apply_server3.sh`
- Rollback: `bash ops/tv-desktop/rollback_server3.sh`
