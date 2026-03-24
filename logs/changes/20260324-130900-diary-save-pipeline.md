# 2026-03-24 13:09 AEST - Diary Save Pipeline

## What changed
- Added a Diary-only deterministic save path in the shared Telegram bridge core.
- Diary-mode messages now batch on a quiet window instead of going through the generic executor path.
- Each batch now writes structured per-day JSON and regenerates a daily `.docx`.
- Added Nextcloud upload and verification support for the generated diary document.
- Wired the live Diary service env for local diary storage and Nextcloud upload.

## Files changed
- `src/telegram_bridge/diary_store.py`
- `src/telegram_bridge/handlers.py`
- `src/telegram_bridge/runtime_config.py`
- `src/telegram_bridge/state_store.py`
- `infra/env/telegram-diary-bridge.env.example`
- `infra/env/telegram-diary-bridge.server3.redacted.env`
- `docs/runtime_docs/diary/DIARY_SUMMARY.md`
- `SERVER3_SUMMARY.md`
- `tests/telegram_bridge/test_runtime_config.py`
- `tests/telegram_bridge/test_diary_store.py`
- `tests/telegram_bridge/test_diary_bridge_flow.py`

## Verification
- `python3 -m unittest tests.telegram_bridge.test_runtime_config tests.telegram_bridge.test_diary_store tests.telegram_bridge.test_diary_bridge_flow`
- `python3 -m py_compile src/telegram_bridge/diary_store.py src/telegram_bridge/handlers.py src/telegram_bridge/runtime_config.py src/telegram_bridge/state_store.py`
- `git diff --check`
- `python3 ops/server3_runtime_status.py`
- Live smoke with Diary env overrides:
  - generated `.docx` at `/home/diary/.local/share/diary-smoke/exports/2026/03/2026-03-24 - Diary.docx`
  - uploaded to Nextcloud at `/Diary/_smoke/2026/03/2026-03-24 - Diary.docx`
  - remote cleanup delete returned `HTTP 204`
