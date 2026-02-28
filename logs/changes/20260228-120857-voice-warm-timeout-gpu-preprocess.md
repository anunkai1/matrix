# Server3 Change Record - Voice Warm Runtime, Idle Timeout, GPU-First, Preprocessing

Timestamp: 2026-02-28T12:08:57+10:00 (Australia/Brisbane)
Type: repo-only implementation update (runtime behavior via code/scripts/docs)

## Objective
Improve voice transcription performance and reliability by:
- keeping Whisper warm after first voice request,
- auto-unloading model after idle timeout,
- using GPU-first with CPU fallback,
- applying fixed preprocessing before transcription.

## Files Updated
- `src/telegram_bridge/voice_transcribe_service.py` (new)
- `ops/telegram-voice/transcribe_voice.sh`
- `ops/telegram-voice/configure_env.sh`
- `infra/env/telegram-architect-bridge.env.example`
- `docs/telegram-architect-bridge.md`
- `tests/telegram_bridge/test_voice_transcribe_service.py` (new)
- `SERVER3_SUMMARY.md`

## Changes Applied
1. Added persistent transcription service:
- New `voice_transcribe_service.py` with `server`, `client`, and `ping` modes over Unix socket.
- Service keeps model loaded between requests and unloads on idle timeout (`TELEGRAM_VOICE_WHISPER_IDLE_TIMEOUT_SECONDS`, default `3600`).
- Primary profile uses configured GPU settings (`cuda/float16`) and falls back to CPU (`cpu/int8`) on backend failure.

2. Updated wrapper behavior:
- `transcribe_voice.sh` now:
  - preprocesses audio with ffmpeg when available (mono 16k + high/low-pass),
  - ensures service is running (starts on-demand),
  - sends transcription request through service client.

3. Updated voice env defaults:
- `configure_env.sh` now writes GPU-first defaults, fallback settings, idle-timeout/socket/log env keys.

4. Updated docs/env examples:
- `infra/env/telegram-architect-bridge.env.example` and `docs/telegram-architect-bridge.md` reflect warm service, idle timeout, and GPU-first defaults.

5. Added tests:
- New unit tests cover transcript collection, idle unload, and fallback behavior.

## Validation
- `bash -n ops/telegram-voice/transcribe_voice.sh ops/telegram-voice/configure_env.sh` -> pass
- `python3 -m unittest tests/telegram_bridge/test_voice_transcribe_service.py -v` -> pass (4 tests)
- `python3 -m unittest discover -s tests -v` -> pass (58 tests)
- `bash src/telegram_bridge/smoke_test.sh` -> `self-test: ok`, `smoke-test: ok`
