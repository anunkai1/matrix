# Diary Summary

Last updated: 2026-03-24 (AEST, +10:00)

## Purpose
- Fast restart context for the Diary runtime.
- Keep this file compact, current, and diary-operation focused.

## Current Snapshot
- Runtime role: dedicated Telegram diary assistant on Server3
- Intended runtime root: `/home/diary/diarybot`
- Shared core dependency: `/home/architect/matrix/src/telegram_bridge`
- Current rollout state: repo scaffold prepared; live bot token and runtime deployment still pending

## Operational Memory (Pinned)
- In the dedicated diary chat, incoming text, voice, and photos should be treated as diary material by default.
- Default diary model is one document per day with multiple time-stamped entries.
- Voice should be transcribed before composing the diary entry.
- Photo batches should stay together in one entry when they belong to the same user moment.
- When save destination is ambiguous, ask once and then reuse the configured path.
- Never claim a diary file was updated without verifying the resulting file.
- If file delivery destination is ambiguous, explicitly ask whether the user wants inline content or a Telegram attachment.

## Recent Changes
- 2026-03-24: prepared the repo scaffold for a dedicated `Diary` Telegram runtime, including isolated persona docs, env example, and systemd unit template; live deployment is intentionally deferred until the bot token and target chat are ready.

## Current Risks/Watchouts
- The runtime is not live yet; token, allowlist, service user, and runtime-root provisioning still need to be completed.
- Dedicated diary behavior currently depends on runtime policy and prompt handling; any fully automatic save pipeline should still be verified end to end after deployment.
