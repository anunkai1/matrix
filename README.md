# 🚀 🕶️💊🟩 Welcome to the Matrix 🟩💊🕶️

Source-of-truth repository for Server3 automation and operations. The current primary workload is the Telegram Architect bridge that forwards Telegram prompts to local Codex execution on Server3.

## Current Status

- Active component: `telegram-architect-bridge.service`
- Runtime mode: Telegram long polling + local `codex exec` executor
- Input modes: text, photo (image + optional caption), voice snippets (transcribed to text and echoed back), and generic files/documents for analysis
- Context behavior: per-chat context persistence (`chat_id -> thread_id`) with `/reset`
- Optional persistent worker-session manager via env flag (`TELEGRAM_PERSISTENT_WORKERS_ENABLED=true`)
- Optional canonical session-store mode via env flag (`TELEGRAM_CANONICAL_SESSIONS_ENABLED=true`); legacy mirror writes are optional via `TELEGRAM_CANONICAL_LEGACY_MIRROR_ENABLED=true` for temporary rollback compatibility
- Built-in safe `/restart` command (queues restart until active work completes)
- Restart interruption notice: if bridge restarts mid-request, affected chats get a resend prompt on startup
- Help alias: `/h` (same as `/help`)
- Live request progress: typing heartbeat + in-place progress status updates while Architect is running
- Architect-only routing for all allowlisted chats
- CI checks: `.github/workflows/telegram-bridge-ci.yml` (compile + unit tests + self/smoke tests)

## Repository Structure

- `src/` runtime code
  - Telegram bridge modules now split into `main.py` (bootstrap/poll loop), `handlers.py`, `transport.py`, `executor.py`, `state_store.py`, `session_manager.py`, `media.py`
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

Local validation:

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
python3 src/telegram_bridge/main.py --self-test
bash src/telegram_bridge/smoke_test.sh
```

## Operations

- Restart bridge (verified): `bash ops/telegram-bridge/restart_and_verify.sh`
- Check status: `bash ops/telegram-bridge/status_service.sh`
- Check logs: `sudo journalctl -u telegram-architect-bridge.service -n 200 --no-pager`
- Roll back systemd install: `bash ops/telegram-bridge/install_systemd.sh rollback`
- HA climate set/schedule runbook: `docs/home-assistant-ops.md`

## Change Control Rules

- This repo is the single source of truth.
- Default path: every non-exempt change set is GitHub-traceable through commit + push.
- For non-exempt live edits outside repo paths, mirror intended/final state under `infra/`, use `ops/` for apply/rollback, document in `docs/`, and record applied changes under `logs/` in the same session.
- For non-exempt change sets, update `SERVER3_PROGRESS.md` and push in the same session.
- Exception boundaries and operational exemptions are defined in `ARCHITECT_INSTRUCTION.md`.

## Progress Tracking

Use `SERVER3_PROGRESS.md` as the session-to-session status log. Add one high-level entry after each completed non-exempt task/change set.

## Security Notes

- Never commit secrets, tokens, or private keys.
- Keep production secrets in live environment files (for example `/etc/default/telegram-architect-bridge`) and out of git.
- Review command outputs before sharing to avoid exposing sensitive values.

## Troubleshooting

- Service fails at startup: validate required env vars in `/etc/default/telegram-architect-bridge`.
- Persistent worker sessions not behaving as expected: check `TELEGRAM_PERSISTENT_WORKERS_*` env values and bridge journal.
- Voice messages fail: validate `TELEGRAM_VOICE_TRANSCRIBE_CMD` and ensure the command prints transcript text to stdout.
- For GPU transcription, set `TELEGRAM_VOICE_WHISPER_DEVICE=cuda`; if CUDA is unavailable at runtime, transcription now retries on CPU fallback.
- Bridge replies with execution failure: verify `codex` is installed and authenticated for `architect`.
- No Telegram responses: confirm bot token/chat allowlist and check service journal logs.

## Related Docs

- `ARCHITECT_INSTRUCTION.md`
- `docs/home-assistant-ops.md`
- `docs/telegram-architect-bridge.md`
- `docs/server-setup.md`
- `SERVER3_PROGRESS.md`
