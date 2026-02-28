# Server3 Change Record - Tank Voice Learning Live Apply and Restart

Timestamp: 2026-02-28T14:14:55+10:00 (Australia/Brisbane)
Type: live server apply + repo mirror sync

## Objective
Apply the latest voice improvements to Tank live runtime: improved decode defaults, confidence gate settings, and controlled alias-learning settings.

## Live Changes Applied
1. Backed up live Tank env file:
- `/etc/default/telegram-tank-bridge.bak.20260228-141455`

2. Updated `/etc/default/telegram-tank-bridge` keys:
- `TELEGRAM_VOICE_WHISPER_MODEL=small`
- `TELEGRAM_VOICE_WHISPER_LANGUAGE=en`
- `TELEGRAM_VOICE_WHISPER_BEAM_SIZE=5`
- `TELEGRAM_VOICE_WHISPER_BEST_OF=5`
- `TELEGRAM_VOICE_WHISPER_TEMPERATURE=0.0`
- `TELEGRAM_VOICE_LOW_CONFIDENCE_CONFIRMATION_ENABLED=true`
- `TELEGRAM_VOICE_LOW_CONFIDENCE_THRESHOLD=0.45`
- `TELEGRAM_VOICE_ALIAS_LEARNING_ENABLED=true`
- `TELEGRAM_VOICE_ALIAS_LEARNING_PATH=/home/tank/.local/state/telegram-tank-bridge/voice_alias_learning.json`
- `TELEGRAM_VOICE_ALIAS_LEARNING_MIN_EXAMPLES=2`
- `TELEGRAM_VOICE_ALIAS_LEARNING_CONFIRMATION_WINDOW_SECONDS=900`

3. Restarted Tank bridge:
- Command: `UNIT_NAME=telegram-tank-bridge.service bash ops/telegram-bridge/restart_and_verify.sh`

## Verification
- Service state: `active/running`
- Restart start time: `Sat 2026-02-28 14:15:04 AEST`
- Main PID: `119811`
- Startup logs confirm learning config loaded:
  - `Voice alias learning enabled=True path=/home/tank/.local/state/telegram-tank-bridge/voice_alias_learning.json min_examples=2 confirmation_window_seconds=900`

## Repo Mirror/Template Sync
- Synced live mirror file:
  - `infra/env/telegram-tank-bridge.server3.redacted.env`
- Updated Tank env template defaults/options:
  - `infra/env/telegram-tank-bridge.env.example`
