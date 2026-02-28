# Server3 Change Record - Live Voice Accuracy Env Apply and Bridge Restart

Timestamp: 2026-02-28T13:55:07+10:00 (Australia/Brisbane)
Type: live server apply + repo mirror sync

## Objective
Apply the new voice-transcription accuracy settings to live `/etc/default/telegram-architect-bridge` and restart the bridge so changes are active.

## Live Changes Applied
1. Backed up live env file:
- `/etc/default/telegram-architect-bridge.bak.20260228-135507`

2. Applied voice env updater:
- Command: `bash ops/telegram-voice/configure_env.sh`
- Live target updated: `/etc/default/telegram-architect-bridge`

3. Restarted bridge service:
- Command: `bash ops/telegram-bridge/restart_and_verify.sh --unit telegram-architect-bridge.service`

## Verified Live State
- Service state: `active/running`
- Start timestamp: `Sat 2026-02-28 13:55:13 AEST`
- PID: `114392`
- Verified live env keys now active:
  - `TELEGRAM_VOICE_WHISPER_MODEL=small`
  - `TELEGRAM_VOICE_WHISPER_LANGUAGE=en`
  - `TELEGRAM_VOICE_WHISPER_BEAM_SIZE=5`
  - `TELEGRAM_VOICE_WHISPER_BEST_OF=5`
  - `TELEGRAM_VOICE_WHISPER_TEMPERATURE=0.0`
  - `TELEGRAM_VOICE_LOW_CONFIDENCE_CONFIRMATION_ENABLED=true`
  - `TELEGRAM_VOICE_LOW_CONFIDENCE_THRESHOLD=0.45`

## Repo Mirror Updates
- `infra/env/telegram-architect-bridge.server3.redacted.env` synced to reflect the live non-secret voice settings above.
