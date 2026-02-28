# Change Log - WhatsApp Govorun Runtime Rollout (Phase 1)

- Timestamp (AEST): 2026-02-28T17:00:24+10:00
- Scope: Server3 WhatsApp+Codex runtime provisioning, deployment, operational scripts, and validation.

## What Changed
- Added dedicated rollout tooling under `ops/whatsapp_govorun/`:
  - runtime user setup (`setup_runtime_user.sh`)
  - Node 22 install (`install_node22.sh`)
  - bridge deploy (`deploy_bridge.sh`)
  - user-service install/start/auth/backup helpers
  - codex auth sync helper (`sync_codex_auth.sh`)
- Added bridge app source under `ops/whatsapp_govorun/bridge/`.
- Added target-state user service file mirror:
  - `infra/systemd/user/whatsapp-govorun-bridge.service.target-state`
- Added operations runbook:
  - `docs/runbooks/whatsapp-govorun-operations.md`
- Updated handoff plan status and execution progress:
  - `docs/handoffs/whatsapp-server3-rollout-plan.md`

## Runtime Actions Performed
- Created user `wa-govorun` and runtime root `/home/wa-govorun/whatsapp-govorun`.
- Enabled linger for `wa-govorun` user services.
- Upgraded Node to `v22.22.0` and npm to `10.9.4`.
- Deployed bridge app and installed dependencies as `wa-govorun`.
- Installed/enabled `whatsapp-govorun-bridge.service` (user-level).
- Synced Codex auth context to `wa-govorun` for runtime execution.

## Validation / Tests
- Environment checks:
  - `node -v` -> `v22.22.0`
  - `npm -v` -> `10.9.4`
  - `/usr/local/bin/codex --version` -> `0.106.0`
- Privilege boundary:
  - `wa-govorun` is non-sudo (`sudo -n true` fails as expected).
- Codex runtime execution as `wa-govorun`:
  - `codex exec ... "Reply with exactly: wa-govorun-codex-ok"` -> success.
- Service lifecycle:
  - user service starts/stops/restarts correctly.
- Backup:
  - `ops/whatsapp_govorun/backup_state.sh` created backup archive and verified tar contents.
- Auth diagnostics:
  - Initially observed repeated connection close `statusCode=405` with stale WA web version.
  - Added latest-version fetch on startup/auth and retested.
  - Auth now produces QR successfully and writes `/home/wa-govorun/whatsapp-govorun/state/qr-auth.html`.

## Remaining Step (User Interaction Required)
- Complete WhatsApp linked-device auth by scanning QR (or provide phone for pairing-code mode).
- After successful link, run final live behavior tests:
  - DM reply path
  - group trigger-required path (`@govorun`)
  - group no-trigger ignore behavior
  - post-restart reconnect behavior

## Notes
- Runtime service is currently left `inactive (dead)` intentionally until auth is completed.
- No secrets or auth artifacts were committed to repo.
