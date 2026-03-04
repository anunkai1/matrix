# Govorun WhatsApp restart fix + model rollback (live + repo mirror)

## Objective
- Fix broken in-chat `/restart` path for `govorun-whatsapp-bridge.service`.
- Roll back Govorun WhatsApp model profile to `gpt-5.3-codex` with `high` reasoning.

## Changes Applied
1. Restart target configurability in bridge runtime:
   - Updated `src/telegram_bridge/session_manager.py`:
     - `TELEGRAM_RESTART_SCRIPT` env override support.
     - `TELEGRAM_RESTART_UNIT` env override support.
     - Restart invocation now runs: `bash <script> --unit <unit>`.
     - Failure message now includes resolved script/unit.
2. Restart helper allowlist:
   - Updated `ops/telegram-bridge/restart_and_verify.sh` allowlist to include:
     - `govorun-whatsapp-bridge.service`
3. Sudoers least-privilege mirror:
   - Added `infra/system/sudoers/govorun-whatsapp-bridge` mirroring:
     - `govorun ALL=(root) NOPASSWD: /home/architect/matrix/ops/telegram-bridge/restart_and_verify.sh --unit govorun-whatsapp-bridge.service`
4. Runtime env and mirror updates:
   - `/etc/default/govorun-whatsapp-bridge`:
     - `ARCHITECT_EXEC_ARGS="--model gpt-5.3-codex --config model_reasoning_effort=\"high\""`
     - `TELEGRAM_RESTART_SCRIPT=/home/architect/matrix/ops/telegram-bridge/restart_and_verify.sh`
     - `TELEGRAM_RESTART_UNIT=govorun-whatsapp-bridge.service`
   - `/home/govorun/whatsapp-govorun/app/.env`:
     - `CODEX_MODEL=gpt-5.3-codex`
     - `CODEX_REASONING_EFFORT=high`
   - Synced repo redacted mirrors:
     - `infra/env/govorun-whatsapp-bridge.server3.redacted.env`
     - `infra/env/whatsapp-govorun-bridge.server3.redacted.env`
5. Docs/summary sync:
   - `docs/runbooks/whatsapp-govorun-operations.md`
   - `SERVER3_SUMMARY.md`

## Verification
- Runtime health:
  - `systemctl is-active whatsapp-govorun-bridge.service govorun-whatsapp-bridge.service` -> both `active`
- Restart helper as runtime user:
  - `sudo -u govorun bash /home/architect/matrix/ops/telegram-bridge/restart_and_verify.sh --unit govorun-whatsapp-bridge.service`
  - Result: `verification=pass`
- Node bridge startup model evidence:
  - `/home/govorun/whatsapp-govorun/state/logs/service.log` shows:
    - `model:"gpt-5.3-codex"`
    - `reasoningEffort:"high"`
- Test suite:
  - `python3 -m unittest -q tests.telegram_bridge.test_bridge_core`
  - `Ran 104 tests ... OK`

## Notes
- Existing unrelated working-tree modification in `AGENTS.md` was intentionally left untouched and excluded from this change set.
