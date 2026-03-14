#!/usr/bin/env bash
set -euo pipefail

ENV_FILE="${SERVER3_STATE_BACKUP_ENV_FILE:-/etc/default/server3-state-backup}"
if [[ -f "${ENV_FILE}" ]]; then
  # shellcheck source=/dev/null
  source "${ENV_FILE}"
fi

BACKUP_ROOT="${SERVER3_STATE_BACKUP_ROOT:-/srv/external/server3-backups/state}"
RETENTION_COUNT="${SERVER3_STATE_BACKUP_RETENTION_COUNT:-14}"
HOST_NAME="${SERVER3_STATE_BACKUP_HOSTNAME:-$(hostnamectl --static 2>/dev/null || hostname)}"
REPO_PATH="${SERVER3_STATE_BACKUP_REPO_PATH:-/home/architect/matrix}"
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
SNAPSHOT_DIR="${BACKUP_ROOT}/${TIMESTAMP}"
ARCHIVE_NAME="${HOST_NAME}-state.tar.gz"
ARCHIVE_PATH="${SNAPSHOT_DIR}/${ARCHIVE_NAME}"
MANIFEST_PATH="${SNAPSHOT_DIR}/MANIFEST.txt"
SHA_PATH="${SNAPSHOT_DIR}/SHA256SUMS.txt"
BUNDLE_PATH="${SNAPSHOT_DIR}/${HOST_NAME}-matrix.bundle"

declare -a configured_sources=("${SERVER3_STATE_BACKUP_SOURCES[@]:-}")
if [[ ${#configured_sources[@]} -eq 0 ]]; then
  echo "SERVER3_STATE_BACKUP_SOURCES is not configured in ${ENV_FILE}" >&2
  exit 1
fi

mkdir -p "${SNAPSHOT_DIR}"

declare -a existing_sources=()
declare -a missing_sources=()
for source_path in "${configured_sources[@]}"; do
  if [[ -e "${source_path}" ]]; then
    existing_sources+=("${source_path}")
  else
    missing_sources+=("${source_path}")
  fi
done

if [[ -f "${ENV_FILE}" ]]; then
  existing_sources+=("${ENV_FILE}")
fi

if [[ ${#existing_sources[@]} -eq 0 ]]; then
  echo "No configured backup sources exist." >&2
  exit 1
fi

declare -a relative_sources=()
for source_path in "${existing_sources[@]}"; do
  relative_sources+=("${source_path#/}")
done

tar \
  --ignore-failed-read \
  --warning=no-file-changed \
  --warning=no-file-removed \
  -C / \
  -czf "${ARCHIVE_PATH}" \
  "${relative_sources[@]}"

repo_commit="unavailable"
repo_remote="unavailable"
bundle_created="no"
if [[ -d "${REPO_PATH}/.git" ]]; then
  git_cmd=(git -c "safe.directory=${REPO_PATH}" -C "${REPO_PATH}")
  repo_commit="$("${git_cmd[@]}" rev-parse HEAD 2>/dev/null || printf 'unavailable')"
  repo_remote="$("${git_cmd[@]}" remote get-url origin 2>/dev/null || printf 'unavailable')"
  if "${git_cmd[@]}" bundle create "${BUNDLE_PATH}" --all >/dev/null 2>&1; then
    bundle_created="yes"
  fi
fi

{
  echo "server3_state_backup"
  echo "timestamp=${TIMESTAMP}"
  echo "host=${HOST_NAME}"
  echo "backup_root=${BACKUP_ROOT}"
  echo "archive=${ARCHIVE_NAME}"
  echo "repo_path=${REPO_PATH}"
  echo "repo_commit=${repo_commit}"
  echo "repo_remote=${repo_remote}"
  echo "repo_bundle_created=${bundle_created}"
  echo "retention_count=${RETENTION_COUNT}"
  echo "source_count=${#existing_sources[@]}"
  echo
  echo "[sources]"
  printf '%s\n' "${existing_sources[@]}"
  echo
  echo "[missing_sources]"
  if [[ ${#missing_sources[@]} -eq 0 ]]; then
    echo "(none)"
  else
    printf '%s\n' "${missing_sources[@]}"
  fi
} > "${MANIFEST_PATH}"

(
  cd "${SNAPSHOT_DIR}"
  if [[ -f "${BUNDLE_PATH}" ]]; then
    sha256sum "$(basename "${ARCHIVE_PATH}")" "$(basename "${BUNDLE_PATH}")" "$(basename "${MANIFEST_PATH}")" > "${SHA_PATH}"
  else
    sha256sum "$(basename "${ARCHIVE_PATH}")" "$(basename "${MANIFEST_PATH}")" > "${SHA_PATH}"
  fi
)

mapfile -t snapshot_dirs < <(find "${BACKUP_ROOT}" -mindepth 1 -maxdepth 1 -type d -printf '%P\n' | sort -r)
if (( ${#snapshot_dirs[@]} > RETENTION_COUNT )); then
  for old_dir in "${snapshot_dirs[@]:RETENTION_COUNT}"; do
    rm -rf "${BACKUP_ROOT}/${old_dir}"
  done
fi

echo "Backup created: ${SNAPSHOT_DIR}"
echo "Archive: ${ARCHIVE_PATH}"
if [[ -f "${BUNDLE_PATH}" ]]; then
  echo "Repo bundle: ${BUNDLE_PATH}"
fi
echo "Manifest: ${MANIFEST_PATH}"
echo "Checksums: ${SHA_PATH}"
