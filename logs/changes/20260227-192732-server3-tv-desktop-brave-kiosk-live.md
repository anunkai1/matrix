# Live Change Record - 2026-02-27T19:27:32+10:00

## Objective
Add a command-start desktop environment for HDMI TV usage on Server3 while keeping default boot in CLI mode.

## Repo State
- Branch: `main`
- Repo: `/home/architect/matrix`

## Live Changes Applied
1. Installed desktop/browser stack and dependencies:
   - `xorg`, `lightdm`, `lightdm-gtk-greeter`, `xfce4`, `xfce4-terminal`, `dbus-x11`
   - `pipewire-audio`, `wireplumber`, `pulseaudio-utils`
   - `brave-browser`
2. Added dedicated local desktop user:
   - `tv` user created (if missing)
   - password locked
   - groups: `audio`, `video`
   - confirmed no `sudo` group membership
3. Applied LightDM tv autologin config:
   - `/etc/lightdm/lightdm.conf.d/50-server3-tv-autologin.conf`
4. Installed command control wrappers:
   - `/usr/local/bin/server3-tv-start`
   - `/usr/local/bin/server3-tv-stop`
5. Installed tv session startup assets:
   - `/home/tv/.config/autostart/server3-tv-brave.desktop`
   - `/home/tv/.local/bin/server3-tv-session-start.sh`
   - `/home/tv/.local/bin/server3-tv-audio.sh`
6. Kept boot default in CLI mode:
   - `systemctl set-default multi-user.target`

## Verification Outcomes
- `systemctl get-default` => `multi-user.target`
- `id tv` => `uid=1003(tv) gid=1003(tv) groups=1003(tv),29(audio),44(video)`
- `sudo passwd -S tv` => `tv L ...` (locked)
- `brave-browser --version` => `Brave Browser 145.1.87.191`
- start/stop smoke checks:
  - `/usr/local/bin/server3-tv-start` -> `lightdm` became `active (running)`
  - `/usr/local/bin/server3-tv-stop` -> `lightdm` returned to `inactive (dead)`

## Repo Mirrors Updated
- `infra/system/tv-desktop/lightdm/50-server3-tv-autologin.conf`
- `infra/system/tv-desktop/usr-local-bin/server3-tv-start`
- `infra/system/tv-desktop/usr-local-bin/server3-tv-stop`
- `infra/system/tv-desktop/home-tv/.config/autostart/server3-tv-brave.desktop`
- `infra/system/tv-desktop/home-tv/.local/bin/server3-tv-session-start.sh`
- `infra/system/tv-desktop/home-tv/.local/bin/server3-tv-audio.sh`
- `infra/system/desktop/server3-tv-desktop.target-state.md`
- `infra/system/users/tv.user.target-state.md`
- `ops/tv-desktop/apply_server3.sh`
- `ops/tv-desktop/rollback_server3.sh`
- `docs/server3-tv-desktop.md`

## Notes
- `lightdm.service` shows `Loaded: ...; static` on this host, but command-start behavior works through explicit `systemctl start/stop lightdm`.
- Kernel update notice observed during apt install (`6.8.0-101-generic` available), reboot not performed in this change.
