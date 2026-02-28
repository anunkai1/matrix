# Change Log - Telegram Phase 1 Media, Voice Routing, and Fallback

Timestamp: 2026-02-28T22:36:47+10:00
Timezone: Australia/Brisbane

## Objective
- Implement Phase 1 of Telegram outbound hardening:
  - outbound media send support
  - audio-to-voice routing when requested
  - fallback when Telegram blocks voice messages

## Scope
- In scope:
  - `src/telegram_bridge/transport.py`
  - `src/telegram_bridge/handlers.py`
  - `tests/telegram_bridge/test_bridge_core.py`
  - `SERVER3_SUMMARY.md`
  - this `logs/changes` record
- Out of scope:
  - retry/backoff framework (Phase 2)
  - broader observability overhaul and pipeline refactor (later phases)

## Changes Made
1. Added outbound Telegram media methods in transport:
   - `send_photo`, `send_document`, `send_audio`, `send_voice`
   - local-file multipart uploads and remote URL/file-id sends
   - caption length guard (`TELEGRAM_CAPTION_LIMIT`)
2. Added structured Telegram API error type:
   - `TelegramApiError` with method/description/error_code
   - HTTP error body parsing for clearer failure details
3. Added outbound media directive handling in handlers:
   - parses `[[media:...]]` and `[[audio_as_voice]]` from executor output
   - routes photo/audio/document sends by extension
   - routes audio to `send_voice` when `audio_as_voice` is requested and compatible
4. Added voice-forbidden fallback:
   - on `VOICE_MESSAGES_FORBIDDEN`, falls back from `send_voice` to `send_audio`
   - if media send fails unexpectedly, falls back to text send
5. Wired final response path to use media-aware sender:
   - `finalize_prompt_success` now calls `send_executor_output(...)`

## Validation
- Test command:
  - `python3 -m unittest tests.telegram_bridge.test_bridge_core -v`
- Result:
  - `Ran 53 tests ... OK`
  - includes new tests for directive parsing, voice routing, voice-forbidden fallback, and transport media path selection.

## Notes
- This phase introduces outbound media/voice behavior via explicit output directives.
- Later phases will add retry/backoff and expanded telemetry for delivery operations.
