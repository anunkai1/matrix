# Server3 Change Log - Chat Routing Contract Drift Guard

- Timestamp: 2026-03-05 16:56:04 AEST
- Scope: Govorun Telegram/WhatsApp cross-channel routing consistency guardrails

## What changed
- Added canonical contract file:
  - `infra/contracts/server3-chat-routing.contract.env`
- Added validator:
  - `ops/chat-routing/validate_chat_routing_contract.py`
- Added daily systemd drift-check units:
  - `infra/systemd/server3-chat-routing-contract-check.service`
  - `infra/systemd/server3-chat-routing-contract-check.timer`
- Added timer installer:
  - `ops/chat-routing/install_contract_check_timer.sh`
- Wired contract preflight checks into Govorun service operations:
  - `ops/whatsapp_govorun/install_user_service.sh`
  - `ops/whatsapp_govorun/start_service.sh`
  - `ops/telegram-bridge/restart_and_verify.sh` (for `govorun-whatsapp-bridge.service`)
  - `ops/telegram-bridge/install_systemd.sh` (when `UNIT_NAME=govorun-whatsapp-bridge.service`)
- Added validator regression tests:
  - `tests/chat_routing/test_validate_chat_routing_contract.py`

## Verification
- `python3 ops/chat-routing/validate_chat_routing_contract.py --contract infra/contracts/server3-chat-routing.contract.env --telegram-env infra/env/govorun-whatsapp-bridge.server3.redacted.env --whatsapp-env infra/env/whatsapp-govorun-bridge.server3.redacted.env`
- `python3 -m unittest tests.chat_routing.test_validate_chat_routing_contract`
- `python3 -m unittest discover -s tests -p 'test_*.py'`
