# Live Change Record - 2026-02-17 06:38:54 UTC

## Objective
Enable Telegram voice transcription end-to-end for `telegram-architect-bridge.service` on Server3 and verify runtime behavior.

## Repo State
- Branch: `main`
- Repo: `/home/architect/matrix`

## Live Changes Applied
1. Re-applied voice runtime dependencies and verification:
   - `bash ops/telegram-voice/install_faster_whisper.sh`
   - Result: `ffmpeg` and `python3-venv` confirmed installed; `faster-whisper` import succeeded in managed venv.
2. Re-applied voice env wiring to live service env file:
   - `bash ops/telegram-voice/configure_env.sh`
   - Live path: `/etc/default/telegram-architect-bridge`
3. Restarted service to load env/runtime:
   - `bash ops/telegram-bridge/restart_service.sh`
   - `ExecMainStartTimestamp=Tue 2026-02-17 06:38:24 UTC`
   - `ExecMainPID=93490`
4. Verified runtime env inside running process includes:
   - `TELEGRAM_VOICE_TRANSCRIBE_CMD=/home/architect/matrix/ops/telegram-voice/transcribe_voice.sh {file}`
   - `TELEGRAM_VOICE_TRANSCRIBE_TIMEOUT_SECONDS=180`
   - `TELEGRAM_VOICE_WHISPER_VENV=/home/architect/.local/share/telegram-voice/venv`
   - `TELEGRAM_VOICE_WHISPER_MODEL=base`
   - `TELEGRAM_VOICE_WHISPER_DEVICE=cpu`
   - `TELEGRAM_VOICE_WHISPER_COMPUTE_TYPE=int8`
5. Functional transcription test (wrapper path):
   - Generated sample speech audio using `ffmpeg` `flite` filter.
   - Ran: `ops/telegram-voice/transcribe_voice.sh <sample.ogg>`
   - Output: `Hello this is a voice test from server 3.`

## Notes
- This run completes repo-traceable live rollout for voice transcription runtime + configuration.
- Final user-path validation still depends on sending an actual Telegram voice note to the bot chat.
