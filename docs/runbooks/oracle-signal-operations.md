# Oracle Signal Operations

## Runtime identity
- User: `oracle`
- Transport service: `signal-oracle-bridge.service`
- Python bridge service: `oracle-signal-bridge.service`
- Signal transport root: `/home/oracle/signal-oracle`
- Oracle bridge root: `/home/oracle/oraclebot`
- Oracle bridge workspace layout is intentionally minimal:
  - `/home/oracle/oraclebot/AGENTS.md` is the Oracle persona/identity truth file
  - `/home/oracle/oraclebot/src/telegram_bridge/` contains thin shared-core overlay entrypoints
  - shared bridge implementation lives in `/home/architect/matrix/src/telegram_bridge`

## Provisioning flow
1. `ops/signal_oracle/setup_runtime_user.sh`
2. `ops/signal_oracle/deploy_bridge.sh`
3. `ops/signal_oracle/install_user_service.sh`
4. Copy env templates:
   - `/etc/default/signal-oracle-bridge`
   - `/etc/default/oracle-signal-bridge`
   - ensure Oracle bridge restart overrides are present:
     - `TELEGRAM_RESTART_SCRIPT=/home/architect/matrix/ops/telegram-bridge/restart_and_verify.sh`
     - `TELEGRAM_RESTART_UNIT=oracle-signal-bridge.service`
5. Provision Codex CLI auth for the `oracle` runtime user before first start:
   - required path: `/home/oracle/.codex/auth.json`
   - preferred Server3 bootstrap:
     - `ops/codex/install_shared_auth.sh oracle`
   - this links Oracle's `auth.json` to the canonical shared auth file at `/etc/server3-codex/auth.json` and keeps Oracle's other `.codex` state local
   - see [Server3 Shared Codex Auth](server3-shared-codex-auth.md) for the host-wide model and future-user onboarding
   - if this step is skipped, `oracle-signal-bridge.service` will accept chats but executor calls will fail with OpenAI `401 Unauthorized`
6. Authenticate the dedicated Signal account:
   - link mode: `ops/signal_oracle/run_auth.sh link`
   - register mode: `ops/signal_oracle/run_auth.sh register`
   - verify mode: `ops/signal_oracle/run_auth.sh verify <CODE>`
7. Start services: `ops/signal_oracle/start_service.sh`
8. For Signal voice-note transcription, install Oracle's local whisper runtime:
   - `sudo -iu oracle env TELEGRAM_VOICE_WHISPER_VENV=/home/oracle/.local/share/telegram-voice/venv bash /home/architect/matrix/ops/telegram-voice/install_faster_whisper.sh`

## Trigger policy
- DM behavior: always respond
- Group behavior: summon required
- Accepted group prefixes:
  - `@oracle`
  - `oracle`
- Keyword routing is disabled in v1 (`TELEGRAM_KEYWORD_ROUTING_ENABLED=false`)
- Memory is isolated by channel key (`sig:<chat_id>`)

## Health checks
- Transport: `curl http://127.0.0.1:18797/health`
- Bridge status:
  - `sudo systemctl status signal-oracle-bridge.service --no-pager -n 50`
  - `sudo systemctl status oracle-signal-bridge.service --no-pager -n 50`
- Logs:
  - `sudo journalctl -u signal-oracle-bridge.service -n 200 --no-pager`
  - `sudo journalctl -u oracle-signal-bridge.service -n 200 --no-pager`

## Operational notes
- Use a dedicated Signal account/device for Oracle. Do not reuse a personal Signal account.
- `ops/signal_oracle/deploy_bridge.sh` syncs the Signal transport app plus the Oracle overlay shims, and preserves the existing Oracle `AGENTS.md`.
- `ops/signal_oracle/install_user_service.sh` installs a least-privilege sudoers rule so Oracle can run in-chat `/restart` against `oracle-signal-bridge.service` only.
- `ops/signal_oracle/start_service.sh` now fails fast if `/home/oracle/.codex/auth.json` is missing.
- `oracle-signal-bridge.service` now waits for the local Signal transport `/health` endpoint before its Python bridge starts, which prevents boot-time `Connection refused` churn when the transport is still warming up.
- `TELEGRAM_RUNTIME_ROOT=/home/oracle/oraclebot` and `TELEGRAM_SHARED_CORE_ROOT=/home/architect/matrix` are now carried in the unit so policy/runtime identity stays separate from the shared code root.
- Signal message edits are not supported in v1. The bridge uses a single progress message plus typing updates.
- Signal voice-note transcription uses Oracle's own faster-whisper runtime under `/home/oracle/.local/share/telegram-voice/venv` and the shared script `/home/architect/matrix/ops/telegram-voice/transcribe_voice.sh`.
- Recommended Oracle Signal voice defaults on Server3:
  - `HF_HOME=/home/oracle/.cache/huggingface`
  - `TELEGRAM_VOICE_WHISPER_MODEL=tiny.en`
  - `TELEGRAM_VOICE_WHISPER_LANGUAGE=en`
- Group messages are accepted in joined groups only when the summon prefix is present.
