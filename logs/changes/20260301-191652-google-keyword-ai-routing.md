# Change Log - Google Keyword AI Routing (Parser Removed)

Timestamp: 2026-03-01T19:16:52+10:00
Timezone: Australia/Brisbane

## Objective
Remove parser-dependent Google keyword behavior so `Google ...` requests behave like HA keyword mode (AI-routed free text).

## Scope
- In scope:
  - Remove Google keyword rewrite into `/google ...` parser flow.
  - Route `Google ...` requests through stateless AI worker with Google-priority prompt policy.
  - Keep explicit `/google ...` commands unchanged for deterministic operations and confirm/cancel safety.
  - Update docs/tests/summary.
- Out of scope:
  - OAuth/token setup changes.
  - Removal of `/google ...` command interface.

## Files Changed
- `src/telegram_bridge/handlers.py`
- `tests/telegram_bridge/test_bridge_core.py`
- `docs/telegram-architect-bridge.md`
- `SERVER3_SUMMARY.md`

## Behavioral Result
- `Google ...` messages now:
  - route to AI mode (stateless) similar to HA keyword routing
  - no longer depend on parser phrase aliases/mappings
- `/google ...` commands still work and remain the controlled path for write operations with confirmation.

## Validation
- `python3 -m unittest tests/telegram_bridge/test_bridge_core.py -q` (pass, 85 tests)
- `python3 -m py_compile src/telegram_bridge/handlers.py` (pass)

