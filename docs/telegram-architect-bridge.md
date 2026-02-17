# Telegram Architect Bridge

This bridge lets Telegram users chat with local Architect/Codex on Server3 without using OpenAI API integration in bridge code.

## Architecture

- Transport: Telegram Bot API (long polling)
- Executor: local CLI command (default wrapper: `src/telegram_bridge/executor.sh`)
- Runtime: `systemd` service

## Files

- Bridge runtime: `src/telegram_bridge/main.py`
- Safe executor wrapper: `src/telegram_bridge/executor.sh`
- Local smoke test: `src/telegram_bridge/smoke_test.sh`
- Systemd source-of-truth unit: `infra/systemd/telegram-architect-bridge.service`
- Install/rollback unit: `ops/telegram-bridge/install_systemd.sh`
- Restart helper: `ops/telegram-bridge/restart_service.sh`
- Status helper: `ops/telegram-bridge/status_service.sh`

## Bot Setup

1. Create a bot via BotFather and capture the token.
2. Find your Telegram chat ID.
3. Create `/etc/default/telegram-architect-bridge`:

```bash
sudo cp infra/env/telegram-architect-bridge.env.example /etc/default/telegram-architect-bridge
sudo nano /etc/default/telegram-architect-bridge
```

Equivalent manual content:

```bash
sudo tee /etc/default/telegram-architect-bridge >/dev/null <<'EOF'
TELEGRAM_BOT_TOKEN=123456:replace_me
TELEGRAM_ALLOWED_CHAT_IDS=123456789
TELEGRAM_EXEC_TIMEOUT_SECONDS=300
TELEGRAM_MAX_INPUT_CHARS=4000
TELEGRAM_MAX_OUTPUT_CHARS=20000
TELEGRAM_RATE_LIMIT_PER_MINUTE=12
# Optional override:
# TELEGRAM_EXECUTOR_CMD=/home/architect/matrix/src/telegram_bridge/executor.sh
EOF
```

## Install and Start

```bash
bash ops/telegram-bridge/install_systemd.sh apply
bash ops/telegram-bridge/restart_service.sh
bash ops/telegram-bridge/status_service.sh
```

## Bridge Commands

- `/start` basic intro
- `/help` command list
- `/status` bridge health and uptime

Any non-command text is forwarded to the local executor.

## Safety Controls

- Chat ID allowlist (`TELEGRAM_ALLOWED_CHAT_IDS`)
- Per-chat single in-flight request (`busy` response on overlap)
- Request timeout guard (`TELEGRAM_EXEC_TIMEOUT_SECONDS`)
- Input and output size limits
- Per-chat rate limit per minute
- Generic user-facing error responses, detailed errors in journal logs

## Troubleshooting

Service status and logs:

```bash
bash ops/telegram-bridge/status_service.sh
sudo journalctl -u telegram-architect-bridge.service -n 200 --no-pager
```

Config mistakes (missing env vars) cause startup failure. Correct `/etc/default/telegram-architect-bridge` and restart service.

## Rollback

```bash
bash ops/telegram-bridge/install_systemd.sh rollback
```

This stops/disables the service and removes `/etc/systemd/system/telegram-architect-bridge.service`.
