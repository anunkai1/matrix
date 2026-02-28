# Server3 Change Record - Voice Alias Self-Learning with Explicit Approval

Timestamp: 2026-02-28T14:07:53+10:00 (Australia/Brisbane)
Type: repo-only implementation update

## Objective
Add controlled self-learning for voice correction so the system improves from repeated low-confidence confirmations while requiring explicit approval before new aliases become active.

## Files Updated
- `src/telegram_bridge/voice_alias_learning.py` (new)
- `src/telegram_bridge/main.py`
- `src/telegram_bridge/handlers.py`
- `src/telegram_bridge/state_store.py`
- `tests/telegram_bridge/test_voice_alias_learning.py` (new)
- `tests/telegram_bridge/test_bridge_core.py`
- `infra/env/telegram-architect-bridge.env.example`
- `ops/telegram-voice/configure_env.sh`
- `docs/telegram-architect-bridge.md`

## Changes Applied
1. Added persistent voice-alias learning store:
- Tracks repeated correction pairs from low-confidence transcript confirmations.
- Stores pending suggestions and approved aliases in a JSON state file.
- Keeps activation explicit: no auto-apply of new learned aliases.

2. Added runtime integration:
- On low-confidence transcription, bridge records a pending confirmation context.
- When user later confirms by text, bridge extracts replacement candidates and increments evidence counts.
- After threshold is reached, bridge emits suggestion(s) for review.

3. Added operator controls in chat:
- `/voice-alias list`
- `/voice-alias approve <id>`
- `/voice-alias reject <id>`
- `/voice-alias add <source> => <target>`

4. Added config/env options:
- `TELEGRAM_VOICE_ALIAS_LEARNING_ENABLED`
- `TELEGRAM_VOICE_ALIAS_LEARNING_PATH`
- `TELEGRAM_VOICE_ALIAS_LEARNING_MIN_EXAMPLES`
- `TELEGRAM_VOICE_ALIAS_LEARNING_CONFIRMATION_WINDOW_SECONDS`

## Validation
- `python3 -m unittest tests/telegram_bridge/test_voice_alias_learning.py -v` -> pass (2 tests)
- `python3 -m unittest tests/telegram_bridge/test_bridge_core.py -v` -> pass (46 tests)
- `python3 -m unittest discover -s tests -v` -> pass (66 tests)
- `bash src/telegram_bridge/smoke_test.sh` -> `self-test: ok`, `smoke-test: ok`
