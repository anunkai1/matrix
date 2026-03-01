# Change Log - Phase F Dual Runtime (Telegram + WhatsApp Parallel)

Timestamp: 2026-03-01T12:20:07+10:00
Timezone: Australia/Brisbane

## Objective
- Run Telegram and WhatsApp channel paths in parallel safely by adding a separate WhatsApp bridge service, while keeping the existing Telegram bridge unchanged and active.

## Scope
- In scope:
  - New systemd unit mirror: `infra/systemd/telegram-architect-whatsapp-bridge.service`
  - New live env: `/etc/default/telegram-architect-whatsapp-bridge`
  - New env mirrors/examples under `infra/env`
  - New ops scripts under `ops/telegram-bridge`
  - WhatsApp runtime plugin mode env in `/home/wa-govorun/whatsapp-govorun/app/.env`
  - WhatsApp deploy script safety fix: `ops/whatsapp_govorun/deploy_bridge.sh`
  - Runbook + summary + this trace log
- Out of scope:
  - WhatsApp account linking/auth completion
  - Replacement of Telegram primary service
  - Single-process multi-channel gateway refactor

## Changes Made
1. Added dual-runtime scaffolding in repo:
   - `infra/systemd/telegram-architect-whatsapp-bridge.service`
   - `infra/env/telegram-architect-whatsapp-bridge.env.example`
   - `infra/env/telegram-architect-whatsapp-bridge.server3.redacted.env`
   - `infra/env/whatsapp-govorun-bridge.env.example`
   - `infra/env/whatsapp-govorun-bridge.server3.redacted.env`
   - `ops/telegram-bridge/install_whatsapp_bridge_service.sh`
   - `ops/telegram-bridge/start_whatsapp_bridge_service.sh`
   - `ops/telegram-bridge/status_whatsapp_bridge_service.sh`
   - `docs/runbooks/telegram-whatsapp-dual-runtime.md`
2. Applied live parallel service wiring:
   - Created `/etc/default/telegram-architect-whatsapp-bridge` with:
     - `TELEGRAM_CHANNEL_PLUGIN=whatsapp`
     - `TELEGRAM_ENGINE_PLUGIN=codex`
     - `WHATSAPP_PLUGIN_ENABLED=true`
     - `WHATSAPP_BRIDGE_API_BASE=http://127.0.0.1:8787`
     - isolated state/sqlite paths under `/home/architect/.local/state/telegram-architect-whatsapp-bridge`
   - Installed and enabled `telegram-architect-whatsapp-bridge.service`.
   - Started `telegram-architect-whatsapp-bridge.service`.
3. Prepared WhatsApp API runtime for plugin queue mode:
   - Updated `/home/wa-govorun/whatsapp-govorun/app/.env` with:
     - `WA_PLUGIN_MODE=true`
     - `WA_API_HOST=127.0.0.1`
     - `WA_API_PORT=8787`
     - API queue/file limits
   - Restarted `whatsapp-govorun-bridge.service`.
4. Fixed deploy safety issue discovered during rollout:
   - Updated `ops/whatsapp_govorun/deploy_bridge.sh` to preserve live `.env` during `rsync` using `--exclude ".env"`.
   - Reason: deploy could otherwise wipe runtime env keys (including `WA_PLUGIN_MODE`).

## Validation
- Primary Telegram service remained active:
  - `systemctl is-active telegram-architect-bridge.service` -> `active`
- New WhatsApp bridge service is active:
  - `systemctl is-active telegram-architect-whatsapp-bridge.service` -> `active`
  - `journalctl -u telegram-architect-whatsapp-bridge.service ...` includes:
    - `Channel plugin active=whatsapp`
    - `bridge.started` with `"channel_plugin":"whatsapp"`
- WhatsApp API runtime is active:
  - `sudo -iu wa-govorun systemctl --user is-active whatsapp-govorun-bridge.service` -> `active`
  - `/home/wa-govorun/whatsapp-govorun/state/logs/service.log` shows latest startup with `pluginMode=true`
- WhatsApp API endpoint reachable:
  - `curl http://127.0.0.1:8787/health` -> `{"ok":true,"result":{"ready":false}}`
  - `curl http://127.0.0.1:8787/updates?offset=0&timeout=1` -> `{"ok":true,"result":[]}`

## Notes
- `ready:false` is expected until WhatsApp linking/auth is completed.
- Telegram and WhatsApp bridge processes now run in parallel without switching Telegram off.
