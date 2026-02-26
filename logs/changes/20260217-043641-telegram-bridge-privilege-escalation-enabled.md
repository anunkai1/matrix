# Telegram Bridge Privilege Escalation Enabled

- Timestamp (UTC): 2026-02-17 04:36:41
- Host: Server3
- Operator: Codex (Architect)

## Objective
Allow Telegram-triggered Architect sessions to execute repo ops scripts that require `sudo` (for example `ops/telegram-bridge/restart_service.sh`).

## Applied
- Updated source-of-truth unit `infra/systemd/telegram-architect-bridge.service` to `NoNewPrivileges=false`.
- Applied the unit to live path `/etc/systemd/system/telegram-architect-bridge.service` using:
  - `bash ops/telegram-bridge/install_systemd.sh apply`
- Restarted live service using:
  - `bash ops/telegram-bridge/restart_service.sh`

## Verification
- `telegram-architect-bridge.service` is `active (running)`.
- `ExecMainStartTimestamp=Tue 2026-02-17 04:36:27 UTC`.
- Running bridge process shows `NoNewPrivs: 0`.
- Live unit content confirms `NoNewPrivileges=false`.

## Notes
- This enables sudo-capable operations from Telegram-triggered sessions under `architect` privileges.
- Keep `TELEGRAM_ALLOWED_CHAT_IDS` tightly restricted.
