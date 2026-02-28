# Change Log - Telegram Phase 3 Observability and Test Hardening

Timestamp: 2026-02-28T22:58:15+10:00
Timezone: Australia/Brisbane

## Objective
- Implement Phase 3 of Telegram quality hardening:
  - improve structured observability for outbound delivery and retry/failure paths
  - increase test coverage for these operational paths

## Scope
- In scope:
  - `src/telegram_bridge/transport.py`
  - `src/telegram_bridge/handlers.py`
  - `tests/telegram_bridge/test_bridge_core.py`
  - `SERVER3_SUMMARY.md`
  - this `logs/changes` record
- Out of scope:
  - live runtime config changes
  - Phase 4 execution path updates

## Changes Made
1. Added structured transport retry/failure events in `transport.py`:
   - `bridge.telegram_api_retry_scheduled`
   - `bridge.telegram_api_retry_succeeded`
   - `bridge.telegram_api_failed`
   - included fields such as method, attempt counters, error type/code, and retry delay.
2. Added structured outbound media delivery events in `handlers.py`:
   - `bridge.outbound_delivery_attempt`
   - `bridge.outbound_delivery_succeeded`
   - `bridge.outbound_delivery_fallback` (voice -> audio on `VOICE_MESSAGES_FORBIDDEN`)
   - `bridge.outbound_delivery_failed` (with text fallback path)
3. Expanded tests in `test_bridge_core.py`:
   - delivery event emission validation for voice fallback and hard media-send failure
   - retry event emission validation for transient retry success
   - failure event validation when retries are exhausted
4. Updated rolling server summary with this Phase 3 change set.

## Validation
- Test command:
  - `python3 -m unittest tests.telegram_bridge.test_bridge_core -v`
- Result:
  - `Ran 59 tests ... OK`

## Notes
- Behavior stays backward compatible for users; this phase primarily improves operational visibility and regression protection.
