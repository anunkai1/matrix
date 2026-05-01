#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=ops/nextcloud/nextcloud-common.sh
source "$SCRIPT_DIR/nextcloud-common.sh"

usage() {
  cat <<'USAGE'
Usage:
  nextcloud-file-delete.sh <remote_path>

Examples:
  nextcloud-file-delete.sh /Documents/report.pdf
USAGE
}

if [[ $# -lt 1 ]]; then
  usage >&2
  exit 2
fi

require_cmd curl
load_nextcloud_ops_env

REMOTE_PATH="$(normalize_remote_path "$1")"
DAV_URL="${NEXTCLOUD_BASE_URL}/remote.php/dav/files/${NEXTCLOUD_USERNAME}$(encode_remote_path "$REMOTE_PATH")"

HTTP_CODE="$(
  nextcloud_auth_curl \
    -o /dev/null \
    -w '%{http_code}' \
    -X DELETE \
    "$DAV_URL"
)"

if [[ "$HTTP_CODE" != "204" ]]; then
  echo "Nextcloud delete failed for $REMOTE_PATH (HTTP $HTTP_CODE)." >&2
  exit 5
fi

echo "[nextcloud-file-delete] remote_path=${REMOTE_PATH} status=${HTTP_CODE}"
