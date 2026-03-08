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
- Chat-routing contract: `infra/contracts/server3-chat-routing.contract.env`

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
5. Validate routing contract and enable daily drift checks:
   - `python3 ops/chat-routing/validate_chat_routing_contract.py`
   - `ops/chat-routing/install_contract_check_timer.sh apply`

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

## Runtime observer
- Purpose:
  - Compute KPI snapshots off-path without changing chat behavior.
  - Persist local snapshots for operator inspection (`status`, `summary`).
  - Optional Telegram delivery modes for daily summaries, proactive alerts, or both.
- Install/enable timer:
  - `ops/runtime_observer/install_systemd.sh apply`
- Optional env override file:
  - `/etc/default/server3-runtime-observer` (template: `infra/env/server3-runtime-observer.env.example`)
- Current live Server3 delivery mode:
  - `RUNTIME_OBSERVER_MODE=telegram_daily_summary`
  - current Server3 timer cadence is once daily at `08:05 AEST`
  - current routing is centralized through `staker_alerts_bot` to chat `211761499`
- Supported Telegram delivery modes:
  - `telegram_daily_summary`: daily summary only
  - `telegram_alerts`: proactive alerts + recovery notices only
  - `telegram_alerts_daily`: both alerts and daily summary
- Enable Telegram delivery:
  - Set the desired `RUNTIME_OBSERVER_MODE` in `/etc/default/server3-runtime-observer`
  - Optional: set `RUNTIME_OBSERVER_TELEGRAM_CHAT_IDS` for explicit routing
  - If explicit Telegram vars are not set, observer falls back to `/etc/default/telegram-architect-bridge` (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_ALLOWED_CHAT_IDS`)
  - Reload/restart timer path:
    - `sudo systemctl daemon-reload`
    - `sudo systemctl restart server3-runtime-observer.timer`
  - Validate send path:
    - `sudo /home/architect/matrix/ops/runtime_observer/runtime_observer.py notify-test`
- Timer/service checks:
  - `sudo systemctl status server3-runtime-observer.timer --no-pager -n 20`
  - `sudo systemctl status server3-runtime-observer.service --no-pager -n 50`
- Operator commands (Brisbane-time output):
  - Current KPI status: `sudo /home/architect/matrix/ops/runtime_observer/runtime_observer.py status`
  - Force snapshot collection now: `sudo /home/architect/matrix/ops/runtime_observer/runtime_observer.py collect`
  - Last 24h summary: `sudo /home/architect/matrix/ops/runtime_observer/runtime_observer.py summary --hours 24`
