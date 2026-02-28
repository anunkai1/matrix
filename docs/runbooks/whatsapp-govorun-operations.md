# WhatsApp Govorun Operations (Server3)

## Runtime identity
- User: `wa-govorun`
- Runtime root: `/home/wa-govorun/whatsapp-govorun`
- Service: `whatsapp-govorun-bridge.service` (user-level)

## Provisioning flow
1. `ops/whatsapp_govorun/setup_runtime_user.sh`
2. `ops/whatsapp_govorun/install_node22.sh`
3. `ops/whatsapp_govorun/deploy_bridge.sh`
4. `ops/whatsapp_govorun/install_user_service.sh`

## WhatsApp auth
- Stop service first: `sudo -iu wa-govorun systemctl --user stop whatsapp-govorun-bridge.service`
- Run: `ops/whatsapp_govorun/run_auth.sh`
- QR opens in browser when available; fallback prints terminal QR.
- Optional pairing-code fallback:
  - Set `WA_PAIRING_PHONE=<digits with country code>` in `/home/wa-govorun/whatsapp-govorun/app/.env`
  - Re-run `ops/whatsapp_govorun/run_auth.sh` and enter printed code in WhatsApp Linked Devices.

## Service controls
- Start/restart: `ops/whatsapp_govorun/start_service.sh`
- Status: `sudo -iu wa-govorun systemctl --user status whatsapp-govorun-bridge.service --no-pager -n 50`
- Logs:
  - `/home/wa-govorun/whatsapp-govorun/state/logs/service.log`
  - `/home/wa-govorun/whatsapp-govorun/state/logs/service.err.log`

## Backup
- Run: `ops/whatsapp_govorun/backup_state.sh`
- Backups stored in: `/home/wa-govorun/whatsapp-govorun/backup`
- Retention: latest 7 snapshots

## Trigger policy
- Group trigger: `@govorun`
- Group behavior: trigger required
- DM behavior: always respond
