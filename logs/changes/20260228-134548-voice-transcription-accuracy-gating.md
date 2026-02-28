# Server3 Change Record - Voice Transcription Accuracy and Confidence Gating

Timestamp: 2026-02-28T13:45:48+10:00 (Australia/Brisbane)
Type: repo-only implementation update

## Objective
Improve voice-command reliability by reducing transcription mistakes and preventing low-confidence auto-execution.

## Files Updated
- `src/telegram_bridge/main.py`
- `src/telegram_bridge/handlers.py`
- `src/telegram_bridge/voice_transcribe.py`
- `src/telegram_bridge/voice_transcribe_service.py`
- `tests/telegram_bridge/test_bridge_core.py`
- `tests/telegram_bridge/test_voice_transcribe_service.py`
- `ops/telegram-voice/configure_env.sh`
- `infra/env/telegram-architect-bridge.env.example`
- `docs/telegram-architect-bridge.md`
- `SERVER3_SUMMARY.md`
- `SERVER3_ARCHIVE.md`

## Changes Applied
1. Improved transcription defaults and decode quality:
- Default Whisper model/language set to `small` + `en`.
- Added decode env knobs with defaults:
  - `TELEGRAM_VOICE_WHISPER_BEAM_SIZE=5`
  - `TELEGRAM_VOICE_WHISPER_BEST_OF=5`
  - `TELEGRAM_VOICE_WHISPER_TEMPERATURE=0.0`

2. Added transcript confidence pipeline:
- Voice service now computes and returns confidence from segment scores.
- Client path emits `VOICE_CONFIDENCE=<value>` marker on stderr for bridge consumption.

3. Added safety gate for low-confidence transcripts:
- New config flags:
  - `TELEGRAM_VOICE_LOW_CONFIDENCE_CONFIRMATION_ENABLED`
  - `TELEGRAM_VOICE_LOW_CONFIDENCE_THRESHOLD`
- If confidence is below threshold (default `0.45`), bridge sends confirmation prompt and does not auto-execute.

4. Added alias correction before execution:
- Added default phrase replacements (for common ASR misses), with env extension support via:
  - `TELEGRAM_VOICE_ALIAS_REPLACEMENTS` (`source=>target;...`)

5. Updated docs/templates/scripts:
- Env template and env updater include new voice tuning and confidence keys.
- Bridge docs updated for new behavior and configuration.

6. Added tests:
- Coverage for confidence parsing, alias replacement, low-confidence blocking, and success-path alias application.

## Validation
- `python3 -m unittest tests/telegram_bridge/test_voice_transcribe_service.py -v` -> pass (4 tests)
- `python3 -m unittest tests/telegram_bridge/test_bridge_core.py -v` -> pass (46 tests)
