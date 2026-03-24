# Diary Summary

Last updated: 2026-03-24 (AEST, +10:00)

## Purpose
- Fast restart context for the Diary runtime.
- Keep this file compact, current, and diary-operation focused.

## Current Snapshot
- Runtime role: dedicated Telegram diary assistant on Server3
- Intended runtime root: `/home/diary/diarybot`
- Shared core dependency: `/home/architect/matrix/src/telegram_bridge`
- Live service: `telegram-diary-bridge.service`
- Live state dir: `/home/diary/.local/state/telegram-diary-bridge`
- Diary local root: `/home/diary/.local/share/diary`
- Nextcloud remote root: `/Diary`
- Current rollout state: live, owner-DM-allowlisted, and ready for structured daily document saves on Server3

## Operational Memory (Pinned)
- In the dedicated diary chat, incoming text, voice, and photos should be treated as diary material by default.
- Default diary model is one document per day with multiple time-stamped entries.
- Voice should be transcribed before composing the diary entry.
- Photo batches should stay together in one entry when they belong to the same user moment.
- Diary capture now batches nearby messages before saving, so text + voice + photos can land in one entry block.
- Closed diary batches now queue FIFO behind the active save, so later captures wait their turn instead of being merged into one long pending batch or hitting `chat_busy`.
- Current owner private chat allowlist is `211761499`.
- When save destination is ambiguous, ask once and then reuse the configured path.
- Never claim a diary file was updated without verifying the resulting file.
- If file delivery destination is ambiguous, explicitly ask whether the user wants inline content or a Telegram attachment.

## Recent Changes
- 2026-03-24: rolled out the live `Diary` Telegram runtime on Server3 with isolated runtime docs under `/home/diary/diarybot`, shared Codex auth wiring, owner DM allowlist `211761499`, installed env/systemd/sudoers, and verified outbound Bot API delivery.
- 2026-03-24: fixed the initial live Diary startup failure by setting `TELEGRAM_BRIDGE_STATE_DIR=/home/diary/.local/state/telegram-diary-bridge` so the service no longer fell back to Architect's readonly default state path.
- 2026-03-24: enabled voice transcription in the live Diary env with a Diary-local whisper runtime under `/home/diary/.local/share/telegram-voice/venv`, a dedicated socket/log path, and the medium-class English model `medium.en`.
- 2026-03-24: added the first deterministic diary-save pipeline in the shared bridge core: Diary-mode messages now batch on a quiet window, queue closed batches FIFO, save structured per-day JSON under `/home/diary/.local/share/diary`, regenerate a daily `.docx`, and upload/verify that document in Nextcloud under `/Diary/YYYY/MM/`.

## Current Risks/Watchouts
- The deterministic diary-save path now exists, but live end-to-end verification still depends on a real post-deploy save through the running bot.
- Diary is currently owner-DM-only; expand allowlists deliberately if shared trip capture is needed later.
