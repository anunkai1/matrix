#!/usr/bin/env bash
set -euo pipefail

ENV_FILE="${SERVER3_STATE_BACKUP_ENV_FILE:-/etc/default/server3-state-backup}"
BACKUP_ROOT_DEFAULT="/srv/external/server3-backups/state"
RETENTION_COUNT_DEFAULT="12"
HOST_NAME_DEFAULT="$(hostnamectl --static 2>/dev/null || hostname)"
REPO_PATH_DEFAULT="/home/architect/matrix"

usage() {
  cat <<'EOF'
Usage: backup_state.sh [--dry-run]

Creates a rebuild-grade Server3 state snapshot using the profile in
/etc/default/server3-state-backup by default.
EOF
}

dry_run="no"
while (($# > 0)); do
  case "$1" in
    --dry-run)
      dry_run="yes"
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

if [[ -f "${ENV_FILE}" ]]; then
  set -f
  # shellcheck source=/dev/null
  source "${ENV_FILE}"
  set +f
fi

BACKUP_ROOT="${SERVER3_STATE_BACKUP_ROOT:-${BACKUP_ROOT_DEFAULT}}"
RETENTION_COUNT="${SERVER3_STATE_BACKUP_RETENTION_COUNT:-${RETENTION_COUNT_DEFAULT}}"
HOST_NAME="${SERVER3_STATE_BACKUP_HOSTNAME:-${HOST_NAME_DEFAULT}}"
REPO_PATH="${SERVER3_STATE_BACKUP_REPO_PATH:-${REPO_PATH_DEFAULT}}"
FAIL_ON_MISSING="${SERVER3_STATE_BACKUP_FAIL_ON_MISSING:-yes}"
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
SNAPSHOT_DIR="${BACKUP_ROOT}/${TIMESTAMP}"
ARCHIVE_NAME="${HOST_NAME}-state.tar.gz"
ARCHIVE_PATH="${SNAPSHOT_DIR}/${ARCHIVE_NAME}"
MANIFEST_PATH="${SNAPSHOT_DIR}/MANIFEST.txt"
SHA_PATH="${SNAPSHOT_DIR}/SHA256SUMS.txt"
BUNDLE_PATH="${SNAPSHOT_DIR}/${HOST_NAME}-matrix.bundle"

declare -a configured_sources=("${SERVER3_STATE_BACKUP_INCLUDE_PATHS[@]:-}")
declare -a configured_stop_units=("${SERVER3_STATE_BACKUP_STOP_UNITS[@]:-}")
declare -a configured_excludes=("${SERVER3_STATE_BACKUP_EXCLUDE_PATTERNS[@]:-}")

if [[ ${#configured_sources[@]} -eq 0 ]]; then
  echo "SERVER3_STATE_BACKUP_INCLUDE_PATHS is not configured in ${ENV_FILE}" >&2
  exit 1
fi

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

if [[ ${#missing_sources[@]} -gt 0 && "${FAIL_ON_MISSING}" == "yes" ]]; then
  printf 'Configured backup paths missing:\n' >&2
  printf '  %s\n' "${missing_sources[@]}" >&2
  exit 1
fi

declare -a relative_sources=()
for source_path in "${existing_sources[@]}"; do
  relative_sources+=("${source_path#/}")
done

declare -a normalized_excludes=()
for exclude_pattern in "${configured_excludes[@]}"; do
  normalized_excludes+=("${exclude_pattern#/}")
done

declare -a stop_status_lines=()
declare -a started_unit_lines=()
declare -a stopped_units=()
restore_needed="no"
backup_success="no"

print_plan() {
  echo "Backup root: ${BACKUP_ROOT}"
  echo "Retention count: ${RETENTION_COUNT}"
  echo "Host name: ${HOST_NAME}"
  echo "Repo path: ${REPO_PATH}"
  echo "Stop units:"
  if [[ ${#configured_stop_units[@]} -eq 0 ]]; then
    echo "  (none)"
  else
    printf '  %s\n' "${configured_stop_units[@]}"
  fi
  echo "Include paths:"
  printf '  %s\n' "${existing_sources[@]}"
  if [[ ${#missing_sources[@]} -gt 0 ]]; then
    echo "Missing paths:"
    printf '  %s\n' "${missing_sources[@]}"
  fi
  echo "Exclude patterns:"
  if [[ ${#normalized_excludes[@]} -eq 0 ]]; then
    echo "  (none)"
  else
    printf '  %s\n' "${normalized_excludes[@]}"
  fi
}

cleanup_on_exit() {
  local exit_code=$?

  if [[ "${restore_needed}" == "yes" ]]; then
    for ((idx=${#stopped_units[@]}-1; idx>=0; idx--)); do
      local unit="${stopped_units[idx]}"
      if systemctl start "${unit}"; then
        started_unit_lines+=("${unit}=started")
      else
        started_unit_lines+=("${unit}=failed_start")
      fi
    done
  fi

  if [[ ${exit_code} -ne 0 && "${dry_run}" != "yes" && "${backup_success}" != "yes" && -d "${SNAPSHOT_DIR}" ]]; then
    rm -rf "${SNAPSHOT_DIR}"
  fi

  exit "${exit_code}"
}
trap cleanup_on_exit EXIT

stop_units_for_snapshot() {
  for unit in "${configured_stop_units[@]}"; do
    if ! systemctl list-unit-files --type=service --type=timer --no-legend "${unit}" >/dev/null 2>&1; then
      stop_status_lines+=("${unit}=not_installed")
      continue
    fi

    local active_state
    active_state="$(systemctl is-active "${unit}" 2>/dev/null || true)"
    if [[ "${active_state}" == "active" || "${active_state}" == "activating" || "${active_state}" == "reloading" ]]; then
      systemctl stop "${unit}"
      stopped_units+=("${unit}")
      stop_status_lines+=("${unit}=stopped")
    else
      stop_status_lines+=("${unit}=already_${active_state:-inactive}")
    fi
  done
}

create_snapshot() {
  mkdir -p "${SNAPSHOT_DIR}"

  local -a tar_cmd=(
    tar
    --ignore-failed-read
    --warning=no-file-changed
    --warning=no-file-removed
    -C /
  )
  for exclude_pattern in "${normalized_excludes[@]}"; do
    tar_cmd+=(--exclude="${exclude_pattern}")
  done
  tar_cmd+=(-czf "${ARCHIVE_PATH}")
  tar_cmd+=("${relative_sources[@]}")
  "${tar_cmd[@]}"
}

start_units_after_snapshot() {
  if [[ "${restore_needed}" != "yes" ]]; then
    return
  fi

  for ((idx=${#stopped_units[@]}-1; idx>=0; idx--)); do
    local unit="${stopped_units[idx]}"
    if systemctl start --no-block "${unit}"; then
      started_unit_lines+=("${unit}=start_dispatched")
    else
      started_unit_lines+=("${unit}=failed_start")
    fi
  done
  restore_needed="no"
}

repo_commit="unavailable"
repo_remote="unavailable"
bundle_created="no"
codex_version="$(codex --version 2>/dev/null || printf 'unavailable')"
node_version="$(node --version 2>/dev/null || printf 'unavailable')"
npm_version="$(npm --version 2>/dev/null || printf 'unavailable')"

capture_repo_bundle() {
  if [[ ! -d "${REPO_PATH}/.git" ]]; then
    return
  fi

  local -a git_cmd=(git -c "safe.directory=${REPO_PATH}" -C "${REPO_PATH}")
  repo_commit="$("${git_cmd[@]}" rev-parse HEAD)"
  repo_remote="$("${git_cmd[@]}" remote get-url origin)"
  "${git_cmd[@]}" bundle create "${BUNDLE_PATH}" --all >/dev/null
  bundle_created="yes"
}

write_manifest() {
  local archive_size_bytes="0"
  if [[ -f "${ARCHIVE_PATH}" ]]; then
    archive_size_bytes="$(stat -c '%s' "${ARCHIVE_PATH}")"
  fi

  {
    echo "server3_state_backup"
    echo "timestamp=${TIMESTAMP}"
    echo "host=${HOST_NAME}"
    echo "backup_root=${BACKUP_ROOT}"
    echo "archive=${ARCHIVE_NAME}"
    echo "archive_size_bytes=${archive_size_bytes}"
    echo "repo_path=${REPO_PATH}"
    echo "repo_commit=${repo_commit}"
    echo "repo_remote=${repo_remote}"
    echo "repo_bundle_created=${bundle_created}"
    echo "retention_count=${RETENTION_COUNT}"
    echo "include_count=${#existing_sources[@]}"
    echo "exclude_count=${#normalized_excludes[@]}"
    echo "codex_version=${codex_version}"
    echo "node_version=${node_version}"
    echo "npm_version=${npm_version}"
    echo
    echo "[stop_units]"
    if [[ ${#stop_status_lines[@]} -eq 0 ]]; then
      echo "(none)"
    else
      printf '%s\n' "${stop_status_lines[@]}"
    fi
    echo
    echo "[start_units]"
    if [[ ${#started_unit_lines[@]} -eq 0 ]]; then
      echo "(none)"
    else
      printf '%s\n' "${started_unit_lines[@]}"
    fi
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
    echo
    echo "[exclude_patterns]"
    if [[ ${#normalized_excludes[@]} -eq 0 ]]; then
      echo "(none)"
    else
      printf '%s\n' "${normalized_excludes[@]}"
    fi
  } > "${MANIFEST_PATH}"
}

write_checksums() {
  (
    cd "${SNAPSHOT_DIR}"
    sha256sum "$(basename "${ARCHIVE_PATH}")" "$(basename "${BUNDLE_PATH}")" "$(basename "${MANIFEST_PATH}")" > "${SHA_PATH}"
  )
}

prune_old_snapshots() {
  mapfile -t snapshot_dirs < <(find "${BACKUP_ROOT}" -mindepth 1 -maxdepth 1 -type d -printf '%P\n' | sort -r)
  if (( ${#snapshot_dirs[@]} > RETENTION_COUNT )); then
    for old_dir in "${snapshot_dirs[@]:RETENTION_COUNT}"; do
      rm -rf "${BACKUP_ROOT}/${old_dir}"
    done
  fi
}

if [[ "${dry_run}" == "yes" ]]; then
  print_plan
  exit 0
fi

restore_needed="yes"
stop_units_for_snapshot
create_snapshot
capture_repo_bundle
start_units_after_snapshot
write_manifest
write_checksums
backup_success="yes"
prune_old_snapshots

echo "Backup created: ${SNAPSHOT_DIR}"
echo "Archive: ${ARCHIVE_PATH}"
echo "Repo bundle: ${BUNDLE_PATH}"
echo "Manifest: ${MANIFEST_PATH}"
echo "Checksums: ${SHA_PATH}"
