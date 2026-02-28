# Change Log - Telegram Phase 2 Retry/Backoff and Chat Actions

Timestamp: 2026-02-28T22:47:48+10:00
Timezone: Australia/Brisbane

## Objective
- Implement Phase 2 of Telegram outbound hardening:
  - retry/backoff for transient Telegram delivery failures
  - improved chat-action signaling for outbound media sends

## Scope
- In scope:
  - `src/telegram_bridge/transport.py`
  - `src/telegram_bridge/handlers.py`
  - `tests/telegram_bridge/test_bridge_core.py`
  - `SERVER3_SUMMARY.md`
  - this `logs/changes` record
- Out of scope:
  - observability expansion and test matrix hardening (later phases)
  - configuration docs/env template updates unless requested

## Changes Made
1. Added Telegram API retry/backoff in transport:
   - transient retry for `429`, `500`, `502`, `503`, `504`
   - retry for network/timeout failures (`URLError`, socket timeout classes)
   - bounded exponential backoff with configurable base sleep
   - honors Telegram `parameters.retry_after` when present
2. Extended `TelegramApiError` metadata:
   - includes optional `retry_after_seconds` for backoff orchestration
3. Wrapped both form-encoded and multipart requests with retry executor:
   - `_request(...)` and `_request_multipart(...)` now share retry behavior
4. Improved outbound chat actions in handlers:
   - photo -> `upload_photo`
   - document -> `upload_document`
   - audio -> `upload_audio`
   - voice path -> `record_voice` then `upload_voice`
   - voice-forbidden fallback path emits `upload_audio`
   - chat-action sends are now best-effort via safe helper (no user-facing breakage if action send fails)
5. Expanded tests:
   - retries once on transient `503` then succeeds
   - does not retry on non-transient `400`
   - updated media chat-action assertions to match new signaling

## Validation
- Test command:
  - `python3 -m unittest tests.telegram_bridge.test_bridge_core -v`
- Result:
  - `Ran 55 tests ... OK`
  - includes new retry semantics and updated chat-action expectations.

## Notes
- This phase improves delivery resilience and UX feedback without changing user command surface.
- Next phases should add richer observability and broader integration tests around failure paths.
