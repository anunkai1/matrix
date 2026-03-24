# Diary Telegram Runtime Live

Time: 2026-03-24 12:28:04 AEST

## Objective
Provision a new isolated Telegram diary runtime for `Diary` using the shared bridge core.

## Repo Changes
- Added `infra/systemd/telegram-diary-bridge.service`.
- Added `infra/env/telegram-diary-bridge.env.example`.
- Added `infra/env/telegram-diary-bridge.server3.redacted.env`.
- Added `infra/runtime_personas/diary.AGENTS.md`.
- Added `docs/runtime_docs/diary/*`.
- Added `infra/system/sudoers/diary-telegram-bridge`.
- Updated the runtime manifest, runtime-doc link checker, restart helper allowlist, and state restore/backup coverage for the live `Diary` runtime.
- Corrected `ops/server3_state/bootstrap_host.sh` so `mavali_eth` keeps UID/GID `1012` and `diary` uses UID/GID `1013`.

## Live Changes
- Created Linux user `diary` with isolated runtime root `/home/diary/diarybot`.
- Linked `/home/diary/diarybot/src` to the shared repo source tree under `/home/architect/matrix/src`.
- Linked the live diary runtime docs back to the repo copies under `infra/runtime_personas/diary.AGENTS.md` and `docs/runtime_docs/diary/*`.
- Installed shared Codex auth for `diary` and seeded `/home/diary/.codex/config.toml`.
- Installed live env file `/etc/default/telegram-diary-bridge`.
- Installed sudoers rule `/etc/sudoers.d/diary-telegram-bridge`.
- Installed and enabled `telegram-diary-bridge.service`.
- Allowed owner private Telegram chat `211761499` only.

## Follow-up Fix During Rollout
- The first service start failed because the env file did not yet set `TELEGRAM_BRIDGE_STATE_DIR`, so the bridge fell back to Architect's default state path and hit `sqlite3.OperationalError: attempt to write a readonly database`.
- Fixed the env by setting `TELEGRAM_BRIDGE_STATE_DIR=/home/diary/.local/state/telegram-diary-bridge`, then restarted and re-verified the service.
- A later owner voice-note test exposed that Diary still lacked `TELEGRAM_VOICE_TRANSCRIBE_CMD`; fixed the live env by reusing `/home/architect/matrix/ops/telegram-voice/transcribe_voice.sh {file}` with `TELEGRAM_VOICE_TRANSCRIBE_TIMEOUT_SECONDS=180`, then restarted and re-verified the service.

## Verification
- `bash /home/architect/matrix/ops/telegram-bridge/restart_and_verify.sh --unit telegram-diary-bridge.service` passed after the state-dir fix.
- `systemctl status telegram-diary-bridge.service` showed `active (running)`.
- `python3 ops/server3_runtime_status.py` reported `Diary` at expected `active` state after restart.
- `bash /home/architect/matrix/ops/runtime_personas/check_runtime_repo_links.sh` should include the new Diary symlink set as tracked runtime docs.
- Bot API outbound proof succeeded with `Diary runtime is live on Server3.` to chat `211761499`.

## Notes
- `getUpdates` for the fresh bot was still empty at rollout time, so the owner DM id was taken from the already-verified owner-only runtime pattern (`211761499`) and confirmed by the successful outbound Bot API smoke.
