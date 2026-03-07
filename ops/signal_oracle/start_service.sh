#!/usr/bin/env bash
set -euo pipefail

ORACLE_HOME="/home/oracle"
CODEX_AUTH_PATH="${ORACLE_HOME}/.codex/auth.json"

if ! sudo -u oracle test -s "${CODEX_AUTH_PATH}"; then
  echo "Missing Codex auth for oracle runtime: ${CODEX_AUTH_PATH}" >&2
  echo "Provision Codex CLI auth for user oracle before starting Oracle Signal services." >&2
  exit 1
fi

sudo systemctl stop oracle-signal-bridge.service || true
sudo systemctl restart signal-oracle-bridge.service
sudo systemctl start oracle-signal-bridge.service
sudo systemctl status signal-oracle-bridge.service --no-pager -n 30
sudo systemctl status oracle-signal-bridge.service --no-pager -n 30
