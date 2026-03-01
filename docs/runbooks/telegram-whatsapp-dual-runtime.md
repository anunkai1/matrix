# Telegram + WhatsApp Dual Runtime (Server3)

## Goal
- Keep Telegram bridge stable as primary.
- Run a separate WhatsApp bridge process in parallel.
- Avoid channel-switch outages by never flipping the Telegram service to `whatsapp`.

## Services
- Telegram primary: `telegram-architect-bridge.service`
- WhatsApp parallel: `telegram-architect-whatsapp-bridge.service`
- WhatsApp API runtime: `whatsapp-govorun-bridge.service` (user `wa-govorun`)

## Config files
- Telegram primary env: `/etc/default/telegram-architect-bridge`
- WhatsApp parallel env: `/etc/default/telegram-architect-whatsapp-bridge`
- WhatsApp API env: `/home/wa-govorun/whatsapp-govorun/app/.env`

## Install / update WhatsApp parallel service
1. Install unit:
   - `ops/telegram-bridge/install_whatsapp_bridge_service.sh apply`
2. Ensure env file exists:
   - copy from `infra/env/telegram-architect-whatsapp-bridge.env.example`
   - set real `TELEGRAM_BOT_TOKEN`
3. Start service:
   - `ops/telegram-bridge/start_whatsapp_bridge_service.sh`
4. Verify status:
   - `ops/telegram-bridge/status_whatsapp_bridge_service.sh`

## WhatsApp API requirements
- In `/home/wa-govorun/whatsapp-govorun/app/.env` set:
  - `WA_PLUGIN_MODE=true`
  - `WA_API_HOST=127.0.0.1`
  - `WA_API_PORT=8787`
- Restart user service:
  - `ops/whatsapp_govorun/start_service.sh`
- Health check:
  - `curl http://127.0.0.1:8787/health`

## Linking behavior
- Before WhatsApp link: `/health` may show `ready:false` and WhatsApp bridge gets no updates.
- Telegram primary remains unaffected and should continue serving chats.
- After link success: `/health` should transition to `ready:true`, then WhatsApp updates flow to the parallel bridge.

## Rollback
1. Stop and disable parallel service:
   - `ops/telegram-bridge/install_whatsapp_bridge_service.sh rollback`
2. Leave Telegram primary running as-is.
3. Confirm:
   - `systemctl status telegram-architect-bridge.service`
