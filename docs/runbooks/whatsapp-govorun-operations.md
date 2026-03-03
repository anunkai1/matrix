# WhatsApp Govorun Operations (Server3)

## Runtime identity
- User: `govorun`
- Runtime root: `/home/govorun/whatsapp-govorun`
- Service: `whatsapp-govorun-bridge.service` (system-level)

## Provisioning flow
1. `ops/whatsapp_govorun/setup_runtime_user.sh`
2. `ops/whatsapp_govorun/install_node22.sh`
3. `ops/whatsapp_govorun/deploy_bridge.sh`
4. `ops/whatsapp_govorun/install_user_service.sh`

## WhatsApp auth
- Stop service first: `sudo systemctl stop whatsapp-govorun-bridge.service`
- Run: `ops/whatsapp_govorun/run_auth.sh`
- QR opens in browser when available; fallback prints terminal QR.
- Optional pairing-code fallback:
  - Set `WA_PAIRING_PHONE=<digits with country code>` in `/home/govorun/whatsapp-govorun/app/.env`
  - Re-run `ops/whatsapp_govorun/run_auth.sh` and enter printed code in WhatsApp Linked Devices.

## Service controls
- Start/restart: `ops/whatsapp_govorun/start_service.sh`
- Status: `sudo systemctl status whatsapp-govorun-bridge.service --no-pager -n 50`
- Logs:
  - `/home/govorun/whatsapp-govorun/state/logs/service.log`
  - `/home/govorun/whatsapp-govorun/state/logs/service.err.log`

## Backup
- Run: `ops/whatsapp_govorun/backup_state.sh`
- Backups stored in: `/home/govorun/whatsapp-govorun/backup`
- Retention: latest 7 snapshots

## Trigger policy
- Group trigger: `@говорун`
- Group behavior: trigger required
- DM behavior: always respond

## Plugin API mode
- Enable plugin-mode queueing for matrix channel plugin:
  - `WA_PLUGIN_MODE=true`
- API defaults:
  - `WA_API_HOST=127.0.0.1`
  - `WA_API_PORT=8787`
- Optional auth:
  - `WA_API_AUTH_TOKEN=<secret>`
- Recommended limits:
  - `WA_API_MAX_UPDATES_PER_POLL=100`
  - `WA_API_MAX_QUEUE_SIZE=2000`
  - `WA_API_MAX_LONG_POLL_SECONDS=30`
  - `WA_FILE_MAX_BYTES=52428800`
