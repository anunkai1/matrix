# Change Record - 2026-02-27T21:22:45+10:00

## Objective
Add TV desktop shell command references to Telegram `/help` and `/h` output so operators can discover start/stop actions quickly.

## Repo State
- Branch: `main`
- Repo: `/home/architect/matrix`

## Changes Applied (Repo-Only)
1. Updated bridge help text generator:
   - `src/telegram_bridge/handlers.py`
   - added lines for:
     - `server3-tv-start`
     - `server3-tv-stop`
2. Updated regression test assertion:
   - `tests/telegram_bridge/test_bridge_core.py`
   - verifies `/h` response includes both TV commands
3. Updated operator docs command list:
   - `docs/telegram-architect-bridge.md`

## Verification
- `python3 -m unittest tests/telegram_bridge/test_bridge_core.py` -> pass

## Notes
- No live service/env/systemd changes were required for this update.
