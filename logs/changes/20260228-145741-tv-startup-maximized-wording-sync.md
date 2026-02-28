# Server3 Change Record - TV Startup Wording Sync

Timestamp: 2026-02-28T14:57:41+10:00 (Australia/Brisbane)
Type: repo-only documentation/state wording update

## Objective
Align TV desktop wording with current runtime behavior (Brave starts maximized, not fullscreen).

## Files Updated
- `infra/system/desktop/server3-tv-desktop.target-state.md`
- `infra/system/tv-desktop/home-tv/.config/autostart/server3-tv-brave.desktop`
- `SERVER3_SUMMARY.md`
- `SERVER3_ARCHIVE.md`

## Changes Applied
1. Updated TV target-state runtime policy wording from fullscreen to maximized.
2. Updated autostart desktop-entry comment to describe maximized startup.
3. Added the new rolling summary entry and migrated one oldest summary item into archive to keep the rolling bound.

## Validation
- Verified runtime template still launches Brave with `--start-maximized`.
- Confirmed summary/archive roll-forward references are consistent.
