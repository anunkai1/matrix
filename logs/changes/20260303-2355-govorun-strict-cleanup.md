# Change Log - 2026-03-03 23:55 AEST

## Objective
Apply strict cleanup to use `govorun` only and remove legacy `wa-govorun` compatibility paths.

## Changes
- Updated WhatsApp ops scripts to remove legacy user fallback and run `govorun` only:
  - `ops/whatsapp_govorun/backup_state.sh`
  - `ops/whatsapp_govorun/deploy_bridge.sh`
  - `ops/whatsapp_govorun/install_user_service.sh`
  - `ops/whatsapp_govorun/run_auth.sh`
  - `ops/whatsapp_govorun/setup_runtime_user.sh`
  - `ops/whatsapp_govorun/start_service.sh`
  - `ops/whatsapp_govorun/sync_codex_auth.sh`
- Simplified env seeding in deploy flow to use:
  - `infra/env/whatsapp-govorun-bridge.env.example`
- Updated runbook runtime identity:
  - `docs/runbooks/whatsapp-govorun-operations.md`
- Removed obsolete legacy unit target-state:
  - `infra/systemd/user/whatsapp-govorun-bridge.service.target-state`

## Validation
- Bash syntax checks for all changed `ops/whatsapp_govorun/*.sh` scripts passed.
- Live service checks after restart:
  - `whatsapp-govorun-bridge.service` active
  - `govorun-whatsapp-bridge.service` active
  - `curl http://127.0.0.1:8787/health` returns ready true
