# ASTER Trader Operations Runbook

## Purpose

Run a dedicated Telegram + CLI runtime for ASTER futures trading with confirmation and risk guards.

## Components

- Service unit template: `infra/systemd/telegram-aster-trader-bridge.service`
- Env template: `infra/env/telegram-aster-trader-bridge.env.example`
- Trading backend: `ops/trading/aster/assistant_entry.py`
- CLI wrapper: `ops/trading/aster/trade_cli.sh`

## Provisioning Checklist

1. Create dedicated runtime user and working copy:

```bash
sudo useradd -m -s /bin/bash aster-trader || true
sudo mkdir -p /home/aster-trader/asterbot
sudo rsync -a --delete --exclude '.git' /home/architect/matrix/ /home/aster-trader/asterbot/
sudo chown -R aster-trader:aster-trader /home/aster-trader
```

2. Install bridge environment file:

```bash
sudo cp /home/aster-trader/asterbot/infra/env/telegram-aster-trader-bridge.env.example /etc/default/telegram-aster-trader-bridge
sudo chmod 600 /etc/default/telegram-aster-trader-bridge
sudo chown root:root /etc/default/telegram-aster-trader-bridge
sudo nano /etc/default/telegram-aster-trader-bridge
```

3. Configure required values in `/etc/default/telegram-aster-trader-bridge`:
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_ALLOWED_CHAT_IDS`
- `ASTER_API_KEY`
- `ASTER_API_SECRET`
- Risk limits (`ASTER_MAX_ORDER_NOTIONAL_USDT`, `ASTER_NOTIONAL_MAX_OVERSHOOT_PCT`, `ASTER_MAX_LEVERAGE`, `ASTER_DAILY_MAX_REALIZED_LOSS_USDT`)

4. Install and start the systemd service:

```bash
UNIT_NAME=telegram-aster-trader-bridge.service bash /home/aster-trader/asterbot/ops/telegram-bridge/install_systemd.sh apply
UNIT_NAME=telegram-aster-trader-bridge.service bash /home/aster-trader/asterbot/ops/telegram-bridge/restart_and_verify.sh
```

## Telegram Usage

- Draft preview from free-form text:
  - `Trade long BTC 2000 USDT 10x market`
- Confirm execution:
  - `Trade confirm <ticket_id>`
- Cancel pending ticket:
  - `Trade cancel <ticket_id>`
- Runtime status:
  - `Trade status`

## CLI Usage

Run as `aster-trader`:

```bash
sudo -u aster-trader bash /home/aster-trader/asterbot/ops/trading/aster/trade_cli.sh "Trade long BTC 1000 USDT 5x market"
```

## Notes

- Confirmation tickets are single-use and expire by `ASTER_CONFIRM_TTL_SECONDS`.
- Trading backend persists state in `ASTER_STATE_DB_PATH`.
- API secrets must never be stored in git-tracked files.
