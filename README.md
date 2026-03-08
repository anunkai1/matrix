# Matrix (Server3 Operations)

Source-of-truth repository for Server3 automation and operations. The current primary workload is the Telegram Architect bridge that forwards Telegram prompts to local Codex execution on Server3, alongside sibling Telegram, WhatsApp, and Signal runtimes that reuse the same bridge core.

## Current Status

- Active component: `telegram-architect-bridge.service`
- Runtime mode: Telegram long polling + local `codex exec` executor
- Additional active runtimes: `telegram-tank-bridge.service`, `telegram-aster-trader-bridge.service`, `whatsapp-govorun-bridge.service` + `govorun-whatsapp-bridge.service`, `signal-oracle-bridge.service` + `oracle-signal-bridge.service`
- Input modes: text, photo (image + optional caption), voice snippets (transcribed to text and echoed back), and generic files/documents for analysis
- Context behavior: shared SQLite memory engine (Telegram + CLI) with per-conversation-key isolation and default `all_context` memory mode
- Optional persistent worker-session manager via env flag (`TELEGRAM_PERSISTENT_WORKERS_ENABLED=true`)
- Optional canonical session-store mode via env flag (`TELEGRAM_CANONICAL_SESSIONS_ENABLED=true`), with optional SQLite backend (`TELEGRAM_CANONICAL_SQLITE_ENABLED=true`) and optional rollback mirrors (`TELEGRAM_CANONICAL_LEGACY_MIRROR_ENABLED=true`, `TELEGRAM_CANONICAL_JSON_MIRROR_ENABLED=true`)
- Memory commands: `/memory ...`, `/remember`, `/forget`, `/forget-all`, `/reset-session`, `/hard-reset-memory`, `/ask` (stateless one-turn)
- Retention default: memory rows persist until per-key reset/forget commands are used
- Built-in safe `/restart` command (queues restart until active work completes)
- Restart interruption notice: if bridge restarts mid-request, affected chats get a resend prompt on startup
- Help alias: `/h` (same as `/help`)
- Live request progress: typing heartbeat + in-place progress status updates while Architect is running
- Architect-only routing for all allowlisted chats
- Keyword operation routing:
  - `HA ...` / `Home Assistant ...` for HA stateless operation mode
  - `Server3 TV ...` for desktop/browser control mode
  - `Nextcloud ...` for Nextcloud file/calendar operation mode
- Google integration in Architect bridge: removed from live runtime
- CI checks: `.github/workflows/telegram-bridge-ci.yml` (compile + unit tests + self/smoke tests)

## Runtime Inventory

- Canonical runtime inventory: `infra/server3-runtime-manifest.json`
- Shared live inspection command: `python3 ops/server3_runtime_status.py`
- Major runtime groups tracked there: Architect, Tank, ASTER, Govorun transport/bridge, Oracle transport/bridge, network layer, guardrail timers, optional UI

## Repository Structure

- `src/` runtime code
  - Telegram bridge modules now split into `main.py` (bootstrap/poll loop), `runtime_config.py`, `handlers.py`, `transport.py`, `executor.py`, `state_store.py`, `session_manager.py`, `media.py`, `memory_engine.py`
  - Shared-memory CLI wrapper: `src/architect_cli/main.py`
- `infra/` source-of-truth mirrors for live server state (systemd units, env templates, managed shell profile content)
- `ops/` apply/rollback/restart/status scripts for live rollout
- `docs/` operator runbooks
- `logs/` repo-tracked execution/change records
- `SERVER3_SUMMARY.md` summary-first session context log
- `SERVER3_ARCHIVE.md` canonical long-term archive index
- `SERVER3_ARCHIVE_LEGACY_*.md` preserved verbatim historical snapshots
- `ARCHITECT_INSTRUCTION.md` authoritative execution policy
- `AGENTS.md` startup checklist + pointer to authoritative policy

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
python3 ops/server3_runtime_status.py
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
- Check shared Server3 runtime status: `python3 ops/server3_runtime_status.py`
- Check Architect-only unit detail: `bash ops/telegram-bridge/status_service.sh`
- Check logs: `sudo journalctl -u telegram-architect-bridge.service -n 200 --no-pager`
- Roll back systemd install: `bash ops/telegram-bridge/install_systemd.sh rollback`
- Runtime observer:
  - Install timer: `bash ops/runtime_observer/install_systemd.sh apply`
  - Live daily-summary mode uses `RUNTIME_OBSERVER_MODE=telegram_daily_summary`
  - Live Server3 schedule is once daily at `08:05 AEST`
  - Current KPI state: `sudo /home/architect/matrix/ops/runtime_observer/runtime_observer.py status`
  - Last 24h KPI summary: `sudo /home/architect/matrix/ops/runtime_observer/runtime_observer.py summary --hours 24`
  - Delivery-path test: `sudo /home/architect/matrix/ops/runtime_observer/runtime_observer.py notify-test`
- Chat-routing drift guard (Govorun Telegram/WhatsApp):
  - Manual check: `python3 ops/chat-routing/validate_chat_routing_contract.py`
  - Install daily timer: `bash ops/chat-routing/install_contract_check_timer.sh apply`
- HA on/off scheduling + climate set/schedule runbook: `docs/home-assistant-ops.md`
- Server3 NordVPN rollout + rollback runbook: `docs/nordvpn-server3.md`

## Change Control Rules

- This repo is the single source of truth.
- Non-exempt change sets are GitHub-traceable through commit + push.
- Policy details (approval, exemptions, verification, proof requirements) are defined in `ARCHITECT_INSTRUCTION.md`.

## Summary and Archive Tracking

- Read `SERVER3_SUMMARY.md` first for current state.
- Use `SERVER3_ARCHIVE.md` for deeper history.
- Keep summary/archive maintenance aligned with the operator-first retention policy in `ARCHITECT_INSTRUCTION.md`.

## Security Notes

- Never commit secrets, tokens, or private keys.
- Keep production secrets in live environment files (for example `/etc/default/telegram-architect-bridge` and `/etc/default/ha-ops`) and out of git.
- Review command outputs before sharing to avoid exposing sensitive values.

## Troubleshooting

- Service fails at startup: validate required env vars in `/etc/default/telegram-architect-bridge`.
- Persistent worker sessions not behaving as expected: check `TELEGRAM_PERSISTENT_WORKERS_*` env values and bridge journal.
- Voice messages fail: validate `TELEGRAM_VOICE_TRANSCRIBE_CMD` and ensure the command prints transcript text to stdout.
- For GPU transcription, set `TELEGRAM_VOICE_WHISPER_DEVICE=cuda`; if CUDA is unavailable at runtime, transcription now retries on CPU fallback.
- Bridge replies with execution failure: verify `codex` is installed and authenticated for `architect`.
- No Telegram responses: confirm bot token/chat allowlist and check service journal logs.

## Related Docs

- `AGENTS.md`
- `ARCHITECT_INSTRUCTION.md`
- `docs/server3-mental-model.md`
- `docs/home-assistant-ops.md`
- `docs/telegram-architect-bridge.md`
- `docs/telegram-bridge-debug-checklist.md`
- `docs/runbooks/aster-trader-operations.md`
- `docs/runbooks/whatsapp-govorun-operations.md`
- `docs/runbooks/oracle-signal-operations.md`
- `docs/server-setup.md`
- `SERVER3_SUMMARY.md`
- `SERVER3_ARCHIVE.md`
- `SERVER3_ARCHIVE_LEGACY_20260228.md`
