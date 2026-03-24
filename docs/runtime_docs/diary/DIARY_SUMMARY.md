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
- Current rollout state: live and owner-DM-allowlisted on Server3

## Operational Memory (Pinned)
- In the dedicated diary chat, incoming text, voice, and photos should be treated as diary material by default.
- Default diary model is one document per day with multiple time-stamped entries.
- Voice should be transcribed before composing the diary entry.
- Photo batches should stay together in one entry when they belong to the same user moment.
- Current owner private chat allowlist is `211761499`.
- When save destination is ambiguous, ask once and then reuse the configured path.
- Never claim a diary file was updated without verifying the resulting file.
- If file delivery destination is ambiguous, explicitly ask whether the user wants inline content or a Telegram attachment.

## Recent Changes
- 2026-03-24: rolled out the live `Diary` Telegram runtime on Server3 with isolated runtime docs under `/home/diary/diarybot`, shared Codex auth wiring, owner DM allowlist `211761499`, installed env/systemd/sudoers, and verified outbound Bot API delivery.
- 2026-03-24: fixed the initial live Diary startup failure by setting `TELEGRAM_BRIDGE_STATE_DIR=/home/diary/.local/state/telegram-diary-bridge` so the service no longer fell back to Architect's readonly default state path.
- 2026-03-24: enabled voice transcription in the live Diary env by reusing `/home/architect/matrix/ops/telegram-voice/transcribe_voice.sh {file}` with a `180` second timeout, matching the working Architect/Tank pattern.

## Current Risks/Watchouts
- Dedicated diary behavior currently depends on runtime policy and prompt handling; any fully automatic save pipeline should still be verified end to end after deployment.
- Diary is currently owner-DM-only; expand allowlists deliberately if shared trip capture is needed later.
