# Change Log - Telegram Phase 4 Execution Path Hardening

Timestamp: 2026-02-28T23:06:16+10:00
Timezone: Australia/Brisbane

## Objective
- Implement Phase 4 final execution-path hardening for outbound Telegram delivery.

## Scope
- In scope:
  - `src/telegram_bridge/handlers.py`
  - `tests/telegram_bridge/test_bridge_core.py`
  - `SERVER3_SUMMARY.md`
  - this `logs/changes` record
- Out of scope:
  - transport retry algorithm changes
  - live service config changes

## Changes Made
1. Added structured outbound JSON envelope parsing in `handlers.py`:
   - new parser for payloads shaped as:
     - `{"telegram_outbound": {"text": "...", "media_ref": "...", "as_voice": true|false}}`
   - keeps legacy `[[media:...]]`/`[[audio_as_voice]]` directive support unchanged.
2. Added execution-path observability for outbound payload parsing:
   - `bridge.outbound_payload_parsed`
   - `bridge.outbound_payload_parse_failed`
3. Added deterministic parse-failure fallback:
   - invalid structured payloads now safely fall back to raw text send, instead of ambiguous behavior.
4. Hardened finalize flow against directive corruption:
   - control outputs (legacy media directives and structured envelopes) are no longer pre-trimmed by `max_output_chars`.
   - plain text still follows existing trim behavior.
5. Expanded tests in `test_bridge_core.py`:
   - structured envelope parse success and schema failure
   - structured envelope delivery path
   - invalid structured payload fallback behavior
   - control-directive detection
   - finalize trim behavior split: skip trim for control payloads, keep trim for plain text

## Validation
- Test command:
  - `python3 -m unittest tests.telegram_bridge.test_bridge_core -v`
- Result:
  - `Ran 66 tests ... OK`

## Notes
- This phase finalizes the staged 1-4 hardening track by stabilizing the outbound execution path while preserving backward compatibility.
