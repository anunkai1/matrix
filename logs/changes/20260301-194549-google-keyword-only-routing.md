# Google Keyword-Only Routing

- Timestamp: 2026-03-01T19:45:49+10:00
- Operator: Codex (Architect)
- Objective: remove `/google ...` command interface and keep only `Google ...` keyword free-text AI routing.

## Changes Applied
- Updated `src/telegram_bridge/handlers.py`:
  - removed legacy `/google` command parser implementation.
  - removed direct GoogleOps command execution path from command handler.
  - kept `Google ...` keyword stateless AI routing.
  - `/google` now returns a migration hint: use `Google ...` (no slash).
  - removed now-unused Google parser imports/helpers.
- Updated `tests/telegram_bridge/test_bridge_core.py`:
  - removed slash-command parser behavior tests.
  - added/updated test to assert `/google ...` returns deprecation hint and does not dispatch worker.
  - retained keyword routing test coverage.
- Updated `docs/telegram-architect-bridge.md`:
  - removed `/google ...` command list from bridge commands.
  - documented keyword-only Google routing behavior.
- Updated `SERVER3_SUMMARY.md` with the latest change-set.

## Verification
- Unit tests: `python3 -m unittest tests/telegram_bridge/test_bridge_core.py -q`
- Compile check: `python3 -m py_compile src/telegram_bridge/handlers.py`
- Service restart and journal check completed.
