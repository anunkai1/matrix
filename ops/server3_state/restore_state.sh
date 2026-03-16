#!/usr/bin/env bash
set -euo pipefail

TARGET_ROOT="/"
RUN_BOOTSTRAP="no"
START_SERVICES="no"

usage() {
  cat <<'EOF'
Usage: restore_state.sh <snapshot_dir> [--target /] [--bootstrap] [--start-services]

Extracts a Server3 state snapshot and optionally bootstraps the host and starts
the restored services.
EOF
}

if (($# == 0)); then
  usage >&2
  exit 1
fi

SNAPSHOT_DIR="$1"
shift

while (($# > 0)); do
  case "$1" in
    --target)
      TARGET_ROOT="${2:?missing target root}"
      shift
      ;;
    --bootstrap)
      RUN_BOOTSTRAP="yes"
      ;;
    --start-services)
      START_SERVICES="yes"
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
  shift
done

if [[ "$(id -u)" -ne 0 ]]; then
  echo "restore_state.sh must run as root." >&2
  exit 1
fi

ARCHIVE_PATH="${SNAPSHOT_DIR}/server3-state.tar.gz"
MANIFEST_PATH="${SNAPSHOT_DIR}/MANIFEST.txt"
BUNDLE_PATH="${SNAPSHOT_DIR}/server3-matrix.bundle"

for required_file in "${ARCHIVE_PATH}" "${MANIFEST_PATH}"; do
  if [[ ! -f "${required_file}" ]]; then
    echo "Missing required restore artifact: ${required_file}" >&2
    exit 1
  fi
done

mkdir -p "${TARGET_ROOT}"
tar -C "${TARGET_ROOT}" -xzf "${ARCHIVE_PATH}"

repo_path="$(awk -F= '$1 == "repo_path" {print $2}' "${MANIFEST_PATH}")"
if [[ -z "${repo_path}" ]]; then
  repo_path="/home/architect/matrix"
fi

target_repo_path="${TARGET_ROOT%/}/${repo_path#/}"
if [[ -f "${BUNDLE_PATH}" ]]; then
  mkdir -p "$(dirname "${target_repo_path}")"
  if [[ ! -d "${target_repo_path}/.git" ]]; then
    rm -rf "${target_repo_path}"
    git clone "${BUNDLE_PATH}" "${target_repo_path}" >/dev/null
  fi
fi

if [[ "${RUN_BOOTSTRAP}" == "yes" ]]; then
  if [[ "${TARGET_ROOT}" != "/" ]]; then
    echo "--bootstrap is only supported with --target /" >&2
    exit 1
  fi
  /home/architect/matrix/ops/server3_state/bootstrap_host.sh --target /
fi

if [[ "${START_SERVICES}" == "yes" ]]; then
  if [[ "${TARGET_ROOT}" != "/" ]]; then
    echo "--start-services is only supported with --target /" >&2
    exit 1
  fi

  systemctl daemon-reload
  systemctl enable \
    server3-state-backup.timer \
    server3-monitoring.service \
    media-stack.service \
    telegram-architect-bridge.service \
    telegram-tank-bridge.service \
    telegram-trinity-bridge.service \
    telegram-macrorayd-bridge.service \
    whatsapp-govorun-bridge.service \
    govorun-whatsapp-bridge.service \
    signal-oracle-bridge.service \
    oracle-signal-bridge.service \
    server3-runtime-observer.timer \
    server3-chat-routing-contract-check.timer \
    server3-monthly-apt-upgrade.timer \
    telegram-architect-memory-health.timer \
    telegram-architect-memory-maintenance.timer \
    telegram-architect-memory-restore-drill.timer \
    govorun-whatsapp-daily-uplift.timer

  systemctl start \
    whatsapp-govorun-bridge.service \
    govorun-whatsapp-bridge.service \
    signal-oracle-bridge.service \
    oracle-signal-bridge.service \
    telegram-architect-bridge.service \
    telegram-tank-bridge.service \
    telegram-trinity-bridge.service \
    telegram-macrorayd-bridge.service \
    media-stack.service \
    server3-monitoring.service \
    server3-state-backup.timer \
    server3-runtime-observer.timer \
    server3-chat-routing-contract-check.timer \
    server3-monthly-apt-upgrade.timer \
    telegram-architect-memory-health.timer \
    telegram-architect-memory-maintenance.timer \
    telegram-architect-memory-restore-drill.timer \
    govorun-whatsapp-daily-uplift.timer
fi

echo "State restore extraction completed into ${TARGET_ROOT}."
echo "Next step: run /home/architect/matrix/ops/server3_state/verify_restore.sh"
