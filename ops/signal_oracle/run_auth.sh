#!/usr/bin/env bash
set -euo pipefail

ENV_FILE="/etc/default/signal-oracle-bridge"
if [[ -f "${ENV_FILE}" ]]; then
  # shellcheck disable=SC1090
  source "${ENV_FILE}"
fi

MODE="${1:-link}"
shift || true

SIGNAL_ACCOUNT="${SIGNAL_ACCOUNT:-}"
SIGNAL_CLI_PATH="${SIGNAL_CLI_PATH:-signal-cli}"

sudo systemctl stop signal-oracle-bridge.service || true

case "${MODE}" in
  link)
    sudo -iu oracle "${SIGNAL_CLI_PATH}" link -n "oracle"
    ;;
  register)
    if [[ -z "${SIGNAL_ACCOUNT}" ]]; then
      echo "SIGNAL_ACCOUNT is required in ${ENV_FILE} for register mode" >&2
      exit 1
    fi
    sudo -iu oracle "${SIGNAL_CLI_PATH}" -a "${SIGNAL_ACCOUNT}" register "$@"
    ;;
  verify)
    if [[ -z "${SIGNAL_ACCOUNT}" ]]; then
      echo "SIGNAL_ACCOUNT is required in ${ENV_FILE} for verify mode" >&2
      exit 1
    fi
    if [[ $# -lt 1 ]]; then
      echo "Usage: $0 verify <CODE>" >&2
      exit 1
    fi
    sudo -iu oracle "${SIGNAL_CLI_PATH}" -a "${SIGNAL_ACCOUNT}" verify "$1"
    ;;
  *)
    echo "Usage: $0 [link|register|verify <CODE>]" >&2
    exit 1
    ;;
esac
