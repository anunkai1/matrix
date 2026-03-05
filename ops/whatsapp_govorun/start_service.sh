#!/usr/bin/env bash
set -euo pipefail

UNIT_NAME="whatsapp-govorun-bridge.service"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CHAT_ROUTING_VALIDATOR="${REPO_ROOT}/ops/chat-routing/validate_chat_routing_contract.py"

sudo /usr/bin/python3 "${CHAT_ROUTING_VALIDATOR}"
sudo systemctl restart "${UNIT_NAME}"
sudo systemctl status "${UNIT_NAME}" --no-pager -n 30
