#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=ops/nextcloud/nextcloud-common.sh
source "$SCRIPT_DIR/nextcloud-common.sh"

usage() {
  cat <<'USAGE'
Usage:
  nextcloud-file-upload.sh <local_file> <remote_path>

Examples:
  nextcloud-file-upload.sh /tmp/report.pdf /Documents/report.pdf
USAGE
}

if [[ $# -lt 2 ]]; then
  usage >&2
  exit 2
fi

LOCAL_FILE="$1"
REMOTE_PATH_RAW="$2"

if [[ ! -f "$LOCAL_FILE" ]]; then
  echo "Local file not found: $LOCAL_FILE" >&2
  exit 2
fi

require_cmd curl
load_nextcloud_ops_env

REMOTE_PATH="$(normalize_remote_path "$REMOTE_PATH_RAW")"
DAV_URL="${NEXTCLOUD_BASE_URL}/remote.php/dav/files/${NEXTCLOUD_USERNAME}$(encode_remote_path "$REMOTE_PATH")"
UPLOAD_HEADERS=()

if [[ -n "${NEXTCLOUD_UPLOAD_MTIME:-}" ]]; then
  UPLOAD_HEADERS+=(-H "X-OC-MTime: ${NEXTCLOUD_UPLOAD_MTIME}")
fi

HTTP_CODE="$(
  nextcloud_auth_curl \
    -o /dev/null \
    -w '%{http_code}' \
    -X PUT \
    "${UPLOAD_HEADERS[@]}" \
    --data-binary "@$LOCAL_FILE" \
    "$DAV_URL"
)"

if [[ "$HTTP_CODE" != "201" && "$HTTP_CODE" != "204" ]]; then
  echo "Nextcloud upload failed for $REMOTE_PATH (HTTP $HTTP_CODE)." >&2
  exit 5
fi

echo "[nextcloud-file-upload] remote_path=${REMOTE_PATH} status=${HTTP_CODE}"
