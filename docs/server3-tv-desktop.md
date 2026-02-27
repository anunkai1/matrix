# Server3 TV Desktop (Command-Start)

This runbook configures Server3 for HDMI TV usage while keeping default boot in CLI mode.

## What It Does
- Keeps default boot target as `multi-user.target` (CLI).
- Installs Xfce + LightDM + Brave.
- Creates dedicated `tv` desktop user (locked password, no sudo).
- Adds on-demand desktop commands:
  - `server3-tv-start`
  - `server3-tv-stop`
- Auto-opens Brave maximized at login (`https://www.youtube.com`).
- Prefers HDMI audio sink in the `tv` session.

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

## TV Session Behavior
- LightDM autologins `tv` only when desktop is started.
- Xfce autostarts `server3-tv-session-start.sh`.
- Brave launches maximized (not forced fullscreen).
- You can still press `F11` if you want fullscreen temporarily.

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
