# Telegram + WhatsApp Dual Runtime (Server3)

## Goal
- Keep Telegram bridge stable as primary.
- Run a separate WhatsApp bridge process in parallel.
- Avoid channel-switch outages by never flipping the Telegram service to `whatsapp`.

## Services
- Telegram primary: `telegram-architect-bridge.service`
- Govorun WhatsApp bridge: `govorun-whatsapp-bridge.service`
- WhatsApp API runtime: `whatsapp-govorun-bridge.service` (user `govorun`)

## Config files
- Telegram primary env: `/etc/default/telegram-architect-bridge`
- Govorun WhatsApp env: `/etc/default/govorun-whatsapp-bridge`
- WhatsApp API env: `/home/govorun/whatsapp-govorun/app/.env`

## Install / update Govorun WhatsApp service
1. Follow canonical provisioning/auth/service controls in:
   - `docs/runbooks/whatsapp-govorun-operations.md`
2. Ensure bridge env file exists:
   - `/etc/default/govorun-whatsapp-bridge`
   - set real `TELEGRAM_BOT_TOKEN` and `TELEGRAM_ALLOWED_CHAT_IDS`
3. Start/restart both Govorun services per operations runbook.
4. Verify status:
   - `sudo systemctl status whatsapp-govorun-bridge.service --no-pager -n 50`
   - `sudo systemctl status govorun-whatsapp-bridge.service --no-pager -n 50`
   - `sudo systemctl status telegram-architect-bridge.service --no-pager -n 50`

## WhatsApp API requirements
- API env keys and limits are defined in:
  - `docs/runbooks/whatsapp-govorun-operations.md` (Plugin API mode section)
- Health check:
  - `curl http://127.0.0.1:8787/health`

## Linking behavior
- Before WhatsApp link: `/health` may show `ready:false` and WhatsApp bridge gets no updates.
- Telegram primary remains unaffected and should continue serving chats.
- After link success: `/health` should transition to `ready:true`, then WhatsApp updates flow to Govorun bridge.

## Rollback
1. Stop and disable Govorun services:
   - `sudo systemctl disable --now govorun-whatsapp-bridge.service whatsapp-govorun-bridge.service`
2. Leave Telegram primary running as-is.
3. Confirm:
   - `systemctl status telegram-architect-bridge.service`
