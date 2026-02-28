# Server3 Change Record - Voice Prefix From Transcript

Timestamp: 2026-02-28T13:24:08+10:00
Timezone: Australia/Brisbane

## Objective
- Fix required-prefix behavior for voice-only messages so prefix is checked from the transcript (not pre-transcription empty caption).

## Scope
- In scope:
  - `src/telegram_bridge/handlers.py`
  - `tests/telegram_bridge/test_bridge_core.py`
  - `SERVER3_SUMMARY.md`
  - this `logs/changes` record
- Out of scope:
  - no allowlist/env value changes
  - no memory model changes

## Changes Made
1. Updated request flow in `handlers.py`:
   - voice without caption now defers required-prefix enforcement to transcript stage
   - text and captioned voice keep existing immediate prefix enforcement
   - transcript-stage failures return the same helper guidance message
2. Threaded a new worker/prompt flag (`enforce_voice_prefix_from_transcript`) across worker call path.
3. Added/updated tests in `test_bridge_core.py` for:
   - deferred worker dispatch for voice-without-caption under prefix mode
   - transcript-stage reject when transcript lacks required prefix
   - transcript-stage accept when transcript includes required prefix

## Validation
- `python3 -m unittest tests/telegram_bridge/test_bridge_core.py` -> `OK` (42 tests)
- `python3 -m unittest tests/telegram_bridge/test_memory_engine.py` -> `OK` (14 tests)

## Live Runtime Action
- Restarted `telegram-tank-bridge.service` to load current handler code.
- Service status after restart:
  - `active (running)`
  - start time: `Sat 2026-02-28 13:24:18 AEST`
  - main pid: `107785`

## Notes
- Tank runtime file `/home/tank/tankbot/src/telegram_bridge/handlers.py` matches repo handler hash in this session.
- Voice behavior should now be:
  - respond when transcript starts with required prefix
  - ignore/reject when transcript does not include required prefix
