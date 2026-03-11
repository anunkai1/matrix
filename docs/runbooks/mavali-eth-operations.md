# Mavali ETH Operations

`mavali_eth` is a dedicated Ethereum mainnet wallet runtime built on the shared Telegram bridge.

## Runtime Shape

- Linux user: `mavali_eth`
- Runtime root: `/home/mavali_eth/mavali_ethbot`
- Bridge unit: `telegram-mavali-eth-bridge.service`
- Receipt monitor:
  - `mavali-eth-receipt-monitor.service`
  - `mavali-eth-receipt-monitor.timer`
- Env file: `/etc/default/telegram-mavali-eth-bridge`

## What The MVP Does

- creates or loads one encrypted wallet
- shows wallet address
- shows ETH balance
- estimates ETH needed for gas
- prepares native ETH send confirmations
- sends native ETH on `Ethereum mainnet`
- polls every `30 minutes` for new inbound ETH and reports confirmed receipts

## Provisioning Order

1. Create the runtime user and root.

```bash
sudo useradd -m -s /bin/bash mavali_eth || true
sudo mkdir -p /home/mavali_eth/mavali_ethbot
sudo chown -R mavali_eth:mavali_eth /home/mavali_eth
```

2. Add or sync the shared-core overlay.

```bash
sudo python3 /home/architect/matrix/ops/runtime_overlays/sync_server3_runtime_overlays.py --runtime "Mavali ETH"
```

3. Install the signing helper venv.

```bash
sudo -iu mavali_eth MAVALI_ETH_VENV=/home/mavali_eth/.local/share/mavali-eth/venv \
  bash /home/architect/matrix/ops/mavali_eth/install_runtime_venv.sh
```

4. Create the live env file.

```bash
sudo cp /home/architect/matrix/infra/env/telegram-mavali-eth-bridge.env.example /etc/default/telegram-mavali-eth-bridge
sudo chmod 600 /etc/default/telegram-mavali-eth-bridge
sudo chown root:root /etc/default/telegram-mavali-eth-bridge
```

Required live values:

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_ALLOWED_CHAT_IDS`
- `MAVALI_ETH_TELEGRAM_OWNER_CHAT_ID`
- `MAVALI_ETH_RPC_URL`
- `MAVALI_ETH_KEYSTORE_PASSPHRASE`
- `MAVALI_ETH_PYTHON_BIN`

5. Install the bridge unit.

```bash
UNIT_NAME=telegram-mavali-eth-bridge.service bash /home/architect/matrix/ops/telegram-bridge/install_systemd.sh apply
```

6. Install and enable the receipt monitor timer.

```bash
sudo install -m 0644 /home/architect/matrix/infra/systemd/mavali-eth-receipt-monitor.service /etc/systemd/system/mavali-eth-receipt-monitor.service
sudo install -m 0644 /home/architect/matrix/infra/systemd/mavali-eth-receipt-monitor.timer /etc/systemd/system/mavali-eth-receipt-monitor.timer
sudo systemctl daemon-reload
sudo systemctl enable --now mavali-eth-receipt-monitor.timer
```

## Verification

Bridge:

```bash
sudo systemctl status telegram-mavali-eth-bridge.service --no-pager
sudo journalctl -u telegram-mavali-eth-bridge.service -n 200 --no-pager
```

Timer:

```bash
sudo systemctl status mavali-eth-receipt-monitor.timer --no-pager
sudo journalctl -u mavali-eth-receipt-monitor.service -n 100 --no-pager
```

CLI:

```bash
python3 /home/architect/matrix/src/mavali_eth_cli/main.py "what is my wallet address"
python3 /home/architect/matrix/src/mavali_eth_cli/main.py "show my eth balance"
```

Telegram checks:

- `what is my wallet address`
- `what is my eth balance`
- `how much eth do I need for gas`
- `send 0.03 ETH to 0x...`
- `confirm`

## Notes

- The bridge runtime itself stays on system Python.
- Cryptographic wallet creation and transaction signing are delegated to the helper script in `ops/mavali_eth/eth_account_helper.py`, which should run under the dedicated `mavali_eth` venv.
- The first inbound receipt poll sets the confirmed-block cursor and does not backfill old receipts as new alerts.

