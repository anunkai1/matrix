# Oracle Signal Operations

## Runtime identity
- User: `oracle`
- Transport service: `signal-oracle-bridge.service`
- Python bridge service: `oracle-signal-bridge.service`
- Signal transport root: `/home/oracle/signal-oracle`
- Oracle bridge root: `/home/oracle/oraclebot`
- Oracle bridge workspace layout is intentionally minimal:
  - `/home/oracle/oraclebot/AGENTS.md` is blank
  - `/home/oracle/oraclebot/src/telegram_bridge/` contains the runtime implementation files

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
   - required file: `/home/oracle/.codex/auth.json`
   - simplest bootstrap on Server3:
     - `sudo install -d -m 700 -o oracle -g oracle /home/oracle/.codex`
     - `sudo install -m 600 -o oracle -g oracle /home/architect/.codex/auth.json /home/oracle/.codex/auth.json`
     - `sudo install -m 600 -o oracle -g oracle /home/architect/.codex/config.toml /home/oracle/.codex/config.toml`
   - if this step is skipped, `oracle-signal-bridge.service` will accept chats but executor calls will fail with OpenAI `401 Unauthorized`
6. Authenticate the dedicated Signal account:
   - link mode: `ops/signal_oracle/run_auth.sh link`
   - register mode: `ops/signal_oracle/run_auth.sh register`
   - verify mode: `ops/signal_oracle/run_auth.sh verify <CODE>`
7. Start services: `ops/signal_oracle/start_service.sh`

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
- `ops/signal_oracle/deploy_bridge.sh` intentionally does not copy the full Architect workspace into `/home/oracle/oraclebot`; it deploys only `src/telegram_bridge` and a blank `AGENTS.md`.
- `ops/signal_oracle/install_user_service.sh` installs a least-privilege sudoers rule so Oracle can run in-chat `/restart` against `oracle-signal-bridge.service` only.
- `ops/signal_oracle/start_service.sh` now fails fast if `/home/oracle/.codex/auth.json` is missing.
- Signal message edits are not supported in v1. The bridge uses a single progress message plus typing updates.
- Voice-note transcription uses the same optional `TELEGRAM_VOICE_TRANSCRIBE_CMD` path as other bridge runtimes.
- Group messages are accepted in joined groups only when the summon prefix is present.
