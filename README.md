# 🚀 🕶️💊🟩 Welcome to the Matrix 🟩💊🕶️

Source-of-truth repository for Server3 automation and operations. The current primary workload is the Telegram Architect bridge that forwards Telegram prompts to local Codex execution on Server3.

## Current Status

- Active component: `telegram-architect-bridge.service`
- Runtime mode: Telegram long polling + local `codex exec` executor
- Input modes: text, photo (image + optional caption), voice snippets (transcribed to text and echoed back), and generic files/documents for analysis
- Context behavior: per-chat context persistence (`chat_id -> thread_id`) with `/reset`
- Built-in safe `/restart` command (queues restart until active work completes)
- Restart interruption notice: if bridge restarts mid-request, affected chats get a resend prompt on startup
- Help alias: `/h` (same as `/help`), also shown in thinking reply hint
- HA scheduling supports relative/absolute timing with persistent queue and complex-plan `APPROVE` / `CANCEL`
- Optional strict split by chat ID: Architect-only chat(s) and HA-only chat(s)

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
bash ops/telegram-bridge/restart_and_verify.sh
bash ops/telegram-bridge/status_service.sh
```

Enable voice transcription runtime:

```bash
bash ops/telegram-voice/install_faster_whisper.sh
bash ops/telegram-voice/configure_env.sh
bash ops/telegram-bridge/restart_and_verify.sh
```

Home Assistant scheduling requests can be sent in plain text (for example `turn living aircon off in 1 hour`).
Complex multi-step plans require `APPROVE` in chat before execution.
For strict separation, set `TELEGRAM_ARCHITECT_CHAT_IDS` and `TELEGRAM_HA_CHAT_IDS` so one chat handles only Architect actions and another handles only HA actions.
In HA-only chats, read-only HA status queries are also supported (for example `what's on right now` and `what's off`).
HA-only voice messages are transcribed and passed through the same HA parser path.
HA parser now accepts natural cover-style commands such as `open garage` / `close garage`.
Climate parser now keeps room context in phrases like `turn on aircon in living room to 22 cold mode`.

## Operations

- Restart bridge (verified): `bash ops/telegram-bridge/restart_and_verify.sh`
- Check status: `bash ops/telegram-bridge/status_service.sh`
- Check logs: `sudo journalctl -u telegram-architect-bridge.service -n 200 --no-pager`
- Roll back systemd install: `bash ops/telegram-bridge/install_systemd.sh rollback`

## Change Control Rules

- This repo is the single source of truth.
- Default path: every non-exempt change set is GitHub-traceable through commit + push.
- For non-exempt live edits outside repo paths, mirror intended/final state under `infra/`, use `ops/` for apply/rollback, document in `docs/`, and record applied changes under `logs/` in the same session.
- For non-exempt change sets, update `SERVER3_PROGRESS.md` and push in the same session.
- Exception: routine HA quick-ops (device state control only, no persistent config/code changes) use journal-only runtime logging and do not require per-action repo commit/push; see `ARCHITECT_INSTRUCTION.md` for exact boundary.

## Progress Tracking

Use `SERVER3_PROGRESS.md` as the session-to-session status log. Add one high-level entry after each completed non-exempt task/change set.

## Security Notes

- Never commit secrets, tokens, or private keys.
- Keep production secrets in live environment files (for example `/etc/default/telegram-architect-bridge`) and out of git.
- Review command outputs before sharing to avoid exposing sensitive values.

## Troubleshooting

- Service fails at startup: validate required env vars in `/etc/default/telegram-architect-bridge`.
- If strict chat routing is enabled, ensure every `TELEGRAM_ALLOWED_CHAT_IDS` entry is assigned to either `TELEGRAM_ARCHITECT_CHAT_IDS` or `TELEGRAM_HA_CHAT_IDS`, with no overlap.
- Voice messages fail: validate `TELEGRAM_VOICE_TRANSCRIBE_CMD` and ensure the command prints transcript text to stdout.
- For GPU transcription, set `TELEGRAM_VOICE_WHISPER_DEVICE=cuda`; if CUDA is unavailable at runtime, transcription now retries on CPU fallback.
- HA actions unavailable: validate `TELEGRAM_HA_BASE_URL`, `TELEGRAM_HA_TOKEN`, and HA package deployment.
- Bridge replies with execution failure: verify `codex` is installed and authenticated for `architect`.
- No Telegram responses: confirm bot token/chat allowlist and check service journal logs.

## Related Docs

- `ARCHITECT_INSTRUCTION.md`
- `docs/telegram-architect-bridge.md`
- `docs/server-setup.md`
- `SERVER3_PROGRESS.md`
