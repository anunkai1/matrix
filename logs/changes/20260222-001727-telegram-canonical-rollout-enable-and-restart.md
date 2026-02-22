# Telegram Canonical Rollout Enable + Restart (Server3)

- Timestamp (UTC): 2026-02-22 00:17:27
- Operator: Codex (Architect)
- Scope: Live runtime env update + service restart/verification

## Objective
Enable canonical session mode with temporary legacy-mirror safety during rollout, then restart and verify `telegram-architect-bridge.service`.

## Live Paths Changed
- `/etc/default/telegram-architect-bridge`

## Backup
- `/etc/default/telegram-architect-bridge.bak-20260222-001727-canonical-rollout`

## Applied Env Flags
- `TELEGRAM_CANONICAL_SESSIONS_ENABLED=true`
- `TELEGRAM_CANONICAL_LEGACY_MIRROR_ENABLED=true`

## Apply Commands (high level)
1. Backup live env file.
2. Set/append canonical flags in live env.
3. Restart and verify bridge via:
   - `bash ops/telegram-bridge/restart_and_verify.sh`

## Restart Verification Evidence
- `verification=pass`
- Before PID: `1154`
- After PID: `16981`
- Active/Sub state: `active` / `running`
- New service start timestamp: `Sun 2026-02-22 10:17:57 AEST`

## Journal Confirmation (post-restart)
- `Canonical sessions enabled=True count=1 path=/home/architect/.local/state/telegram-architect-bridge/chat_sessions.json`
- `Canonical legacy mirror enabled=True`

## Repo Mirrors Updated
- `infra/env/telegram-architect-bridge.server3.redacted.env`
- `infra/env/telegram-architect-bridge.env.example`

## Notes
- No systemd unit content change was required.
- This is an operational rollout only; bridge code behavior is unchanged in this step.
