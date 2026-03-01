# Change Log - Google Keyword Free-Text Parity

Timestamp: 2026-03-01T18:56:14+10:00
Timezone: Australia/Brisbane

## Objective
Make Google actions behave like HA keyword routing by allowing `Google ...` free-text invocation in Telegram while keeping explicit confirmation for write actions.

## Scope
- In scope:
  - Add `Google` keyword routing in bridge message handling.
  - Add free-text alias mapping for `Google summarize/summarise last email`.
  - Extend Google ops helper with latest-message retrieval.
  - Expand tests and docs for keyword/free-text behavior.
- Out of scope:
  - OAuth/auth changes.
  - Removing `/google ...` command support.

## Files Changed
- `src/telegram_bridge/handlers.py`
- `src/telegram_bridge/google_ops.py`
- `tests/telegram_bridge/test_bridge_core.py`
- `docs/telegram-architect-bridge.md`
- `SERVER3_SUMMARY.md`

## Behavioral Changes
- `Google ...` now routes to Google command handling similarly to `HA ...` routing style.
- Supported free-text alias:
  - `Google summarize last email`
  - `Google summarise last email`
- Existing explicit commands still work unchanged:
  - `/google ...`
  - confirmation gate for send/create (`/google confirm <code>`).

## Validation
- `python3 -m unittest tests/telegram_bridge/test_bridge_core.py -q` (pass, 86 tests)
- `python3 -m py_compile src/telegram_bridge/handlers.py src/telegram_bridge/google_ops.py` (pass)

