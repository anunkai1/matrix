# Server3 Architect Bridge Google Removal

- Timestamp: 2026-03-02T17:00:05+10:00
- Operator: Codex (Architect)
- Objective: remove disabled Google account integration from Architect bridge runtime code, env, docs, and ops tooling.

## Repo Changes Applied
- Removed Google runtime module:
  - `src/telegram_bridge/google_ops.py` (deleted)
- Removed Google config and routing from bridge runtime:
  - `src/telegram_bridge/main.py`
  - `src/telegram_bridge/handlers.py`
  - `src/telegram_bridge/state_store.py`
- Removed Google test coverage tied to removed runtime:
  - `tests/telegram_bridge/test_bridge_core.py`
- Removed Google docs/env/ops artifacts:
  - `docs/runbooks/architect-google-oauth.md` (deleted)
  - `docs/telegram-architect-bridge.md`
  - `infra/env/google-architect-oauth.env.example` (deleted)
  - `infra/env/telegram-architect-bridge.env.example`
  - `infra/env/telegram-architect-bridge.server3.redacted.env`
  - `infra/system/google/architect-google-oauth.target-state.redacted.md` (deleted)
  - `ops/google/architect_google_oauth_device.py` (deleted)
  - `ops/google/architect_google_verify.py` (deleted)

## Live Changes Applied
1. Removed live Google env keys from Architect bridge env file:
   - `sudo sed -i '/^TELEGRAM_GOOGLE_/d' /etc/default/telegram-architect-bridge`
2. Restarted Architect bridge:
   - `sudo systemctl restart telegram-architect-bridge.service`
3. Verified no remaining live Google keys:
   - `sudo grep -n '^TELEGRAM_GOOGLE' /etc/default/telegram-architect-bridge` (no output)

## Validation
- Unit tests:
  - `python3 -m unittest tests.telegram_bridge.test_bridge_core`
  - Result: `Ran 79 tests ... OK`
- Runtime:
  - `telegram-architect-bridge.service` active after restart
  - Bridge startup logs show expected `channel_plugin=telegram`, `engine_plugin=codex`

## Notes
- `telegram-architect-whatsapp-bridge.service` remains active but currently logs repeated API connection failures to `http://127.0.0.1:8787` (`Connection refused`), which is separate from Google removal.
