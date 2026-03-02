# Server3 Firefox Install (Desktop)

- Timestamp: 2026-03-02T16:02:17+10:00
- Operator: Codex (Architect)
- Objective: install Firefox as an additional desktop browser on Server3 TV desktop environment.

## Live Commands Run
1. `sudo apt-get update`
2. `sudo apt-get install -y firefox`
3. Verification:
   - `which firefox` -> `/usr/bin/firefox`
   - `snap list firefox` -> `firefox 148.0-1` installed
   - Desktop launcher present: `/var/lib/snapd/desktop/applications/firefox_firefox.desktop`

## Observations
- Ubuntu `firefox` package installed the Firefox snap (`1:1snap1-0ubuntu5` transitional package behavior).
- `needrestart` restarted these services automatically during package install:
  - `telegram-tank-bridge.service`
  - `telegram-architect-whatsapp-bridge.service`
- Post-install check confirms services are active.

## Repo Mirrors Updated
- `infra/system/desktop/server3-tv-desktop.target-state.md`
- `docs/server3-tv-desktop.md`
- `SERVER3_SUMMARY.md`
