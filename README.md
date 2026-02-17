# 🚀 🕶️💊🟩 Welcome to the Matrix 🟩💊🕶️

Source-of-truth repository for Server3 automation and operations. The current primary workload is the Telegram Architect bridge that forwards Telegram prompts to local Codex execution on Server3.

## Current Status

- Active component: `telegram-architect-bridge.service`
- Runtime mode: Telegram long polling + local `codex exec` executor
- Input modes: text, photo (image + optional caption), and voice snippets (transcribed to text)
- Context behavior: per-chat context persistence (`chat_id -> thread_id`) with `/reset`

## Repository Structure

- `src/` runtime code
- `infra/` source-of-truth mirrors for live server state (systemd units, env templates, managed shell profile content)
- `ops/` apply/rollback/restart/status scripts for live rollout
- `docs/` operator runbooks
- `logs/` repo-tracked execution/change records
- `SERVER3_PROGRESS.md` running high-level context log
- `ARCHITECT_INSTRUCTION.md` authoritative workflow rules

## Prerequisites

- Linux host (Server3) with `bash`, `python3`, `systemd`, `sudo`
- `codex` CLI installed and authenticated for user `architect`
- Telegram bot token and allowlisted chat IDs
- Git remote configured to `origin` for this repository

## Quick Start

```bash
cd /home/architect
git clone https://github.com/anunkai1/matrix.git
cd matrix
bash src/telegram_bridge/smoke_test.sh
```

Configure runtime environment:

```bash
sudo cp infra/env/telegram-architect-bridge.env.example /etc/default/telegram-architect-bridge
sudo nano /etc/default/telegram-architect-bridge
```

Install and start service:

```bash
bash ops/telegram-bridge/install_systemd.sh apply
bash ops/telegram-bridge/restart_service.sh
bash ops/telegram-bridge/status_service.sh
```

## Operations

- Restart bridge: `bash ops/telegram-bridge/restart_service.sh`
- Check status: `bash ops/telegram-bridge/status_service.sh`
- Check logs: `sudo journalctl -u telegram-architect-bridge.service -n 200 --no-pager`
- Roll back systemd install: `bash ops/telegram-bridge/install_systemd.sh rollback`

## Change Control Rules

- This repo is the single source of truth.
- Every change set must be GitHub-traceable through commit + push.
- For live edits outside repo paths, mirror intended/final state under `infra/`, use `ops/` for apply/rollback, document in `docs/`, and record applied changes under `logs/` in the same session.
- No task is complete without updating `SERVER3_PROGRESS.md` and pushing.

## Progress Tracking

Use `SERVER3_PROGRESS.md` as the session-to-session status log. Add one high-level entry after each completed task/change set.

## Security Notes

- Never commit secrets, tokens, or private keys.
- Keep production secrets in live environment files (for example `/etc/default/telegram-architect-bridge`) and out of git.
- Review command outputs before sharing to avoid exposing sensitive values.

## Troubleshooting

- Service fails at startup: validate required env vars in `/etc/default/telegram-architect-bridge`.
- Voice messages fail: validate `TELEGRAM_VOICE_TRANSCRIBE_CMD` and ensure the command prints transcript text to stdout.
- Bridge replies with execution failure: verify `codex` is installed and authenticated for `architect`.
- No Telegram responses: confirm bot token/chat allowlist and check service journal logs.

## Related Docs

- `ARCHITECT_INSTRUCTION.md`
- `docs/telegram-architect-bridge.md`
- `docs/server-setup.md`
- `SERVER3_PROGRESS.md`
