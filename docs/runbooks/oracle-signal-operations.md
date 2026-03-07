# Oracle Signal Operations

## Runtime identity
- User: `oracle`
- Transport service: `signal-oracle-bridge.service`
- Python bridge service: `oracle-signal-bridge.service`
- Signal transport root: `/home/oracle/signal-oracle`
- Oracle bridge root: `/home/oracle/oraclebot`

## Provisioning flow
1. `ops/signal_oracle/setup_runtime_user.sh`
2. `ops/signal_oracle/deploy_bridge.sh`
3. `ops/signal_oracle/install_user_service.sh`
4. Copy env templates:
   - `/etc/default/signal-oracle-bridge`
   - `/etc/default/oracle-signal-bridge`
5. Authenticate the dedicated Signal account:
   - link mode: `ops/signal_oracle/run_auth.sh link`
   - register mode: `ops/signal_oracle/run_auth.sh register`
   - verify mode: `ops/signal_oracle/run_auth.sh verify <CODE>`
6. Start services: `ops/signal_oracle/start_service.sh`

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
- Signal message edits are not supported in v1. The bridge uses a single progress message plus typing updates.
- Voice-note transcription uses the same optional `TELEGRAM_VOICE_TRANSCRIBE_CMD` path as other bridge runtimes.
- Group messages are accepted in joined groups only when the summon prefix is present.
