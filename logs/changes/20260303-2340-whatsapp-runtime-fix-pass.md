# Change Log - 2026-03-03 23:40 AEST

## Objective
Fix all identified WhatsApp runtime/repo issues from audit:
- test regression in Telegram bridge config constructor compatibility
- WhatsApp outbound caption return inconsistency
- runtime user/path drift (`govorun` vs legacy `wa-govorun`)
- service install script reliability
- missing Node dependency (`link-preview-js`)

## Repository Changes
- `src/telegram_bridge/main.py`
  - made `Config.progress_label` backward-compatible with default value.
- `src/telegram_bridge/handlers.py`
  - aligned media-path return value with actual delivered caption/follow-up text.
- `ops/whatsapp_govorun/*.sh`
  - added runtime-user auto-detection (`govorun` first, legacy `wa-govorun` fallback).
  - made `deploy_bridge.sh` seed `.env` with resolved runtime home path.
  - made `install_user_service.sh` install rendered system units from repo templates.
  - made `start_service.sh` and `run_auth.sh` handle system or legacy user service scope.
- Added system unit templates:
  - `infra/systemd/whatsapp-govorun-bridge.service`
  - `infra/systemd/govorun-whatsapp-bridge.service`
- Updated env/docs paths and trigger defaults:
  - `ops/whatsapp_govorun/bridge/.env.example`
  - `infra/env/whatsapp-govorun-bridge*.env*`
  - `docs/runbooks/*whatsapp*`
  - `ops/whatsapp_govorun/bridge/README.md`
- `ops/whatsapp_govorun/bridge/package.json`
  - added `link-preview-js` dependency.

## Validation
- Unit tests: `python3 -m unittest discover -s tests -p 'test_*.py'` -> `Ran 111 tests ... OK`
- Self test: `python3 src/telegram_bridge/main.py --self-test` -> `self-test: ok`
- Smoke test: `bash src/telegram_bridge/smoke_test.sh` -> `smoke-test: ok`
- Syntax checks:
  - Python compile -> OK
  - Node `--check` on bridge modules -> OK
  - Bash `-n` on changed scripts -> OK

## Live Apply (Server3)
- Deployed bridge app/deps: `bash ops/whatsapp_govorun/deploy_bridge.sh`
- Installed/enabled rendered system units: `bash ops/whatsapp_govorun/install_user_service.sh`
- Restarted services:
  - `whatsapp-govorun-bridge.service` -> active
  - `govorun-whatsapp-bridge.service` -> active
- API health: `curl http://127.0.0.1:8787/health` -> `{"ok":true,"result":{"ready":true}}`
- Dependency verified live: `npm ls link-preview-js` shows installed and deduped.
