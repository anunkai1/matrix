#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=ops/nextcloud/nextcloud-common.sh
source "$SCRIPT_DIR/nextcloud-common.sh"

usage() {
  cat <<'USAGE'
Usage:
  nextcloud-files-list.sh [remote_path]

Examples:
  nextcloud-files-list.sh
  nextcloud-files-list.sh /Documents
USAGE
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

require_cmd curl
require_cmd python3
load_nextcloud_ops_env

REMOTE_PATH="$(normalize_remote_path "${1:-/}")"
DAV_URL="${NEXTCLOUD_BASE_URL}/remote.php/dav/files/${NEXTCLOUD_USERNAME}$(encode_remote_path "$REMOTE_PATH")"
TMP_XML="$(mktemp)"
trap 'rm -f "$TMP_XML"' EXIT

HTTP_CODE="$(
  nextcloud_auth_curl \
    -o "$TMP_XML" \
    -w '%{http_code}' \
    -X PROPFIND \
    -H 'Depth: 1' \
    -H 'Content-Type: application/xml' \
    --data '<?xml version="1.0"?><d:propfind xmlns:d="DAV:"><d:prop><d:displayname/><d:resourcetype/><d:getcontentlength/><d:getlastmodified/></d:prop></d:propfind>' \
    "$DAV_URL"
)"

if [[ "$HTTP_CODE" != "207" ]]; then
  echo "Nextcloud PROPFIND failed at $REMOTE_PATH (HTTP $HTTP_CODE)." >&2
  exit 5
fi

python3 - "$TMP_XML" <<'PY'
import sys
import xml.etree.ElementTree as ET
from urllib.parse import urlparse, unquote

ns = {'d': 'DAV:'}
xml_path = sys.argv[1]
root = ET.parse(xml_path).getroot()
responses = root.findall('d:response', ns)
items = []
for response in responses[1:]:
    href = response.findtext('d:href', default='', namespaces=ns) or ''
    prop = response.find('d:propstat/d:prop', ns)
    if prop is None:
        continue
    display = prop.findtext('d:displayname', default='', namespaces=ns) or ''
    resourcetype = prop.find('d:resourcetype', ns)
    is_dir = resourcetype is not None and resourcetype.find('d:collection', ns) is not None
    size = prop.findtext('d:getcontentlength', default='', namespaces=ns) or '-'
    path = unquote(urlparse(href).path)
    name = display or path.rstrip('/').split('/')[-1]
    lastmod = prop.findtext('d:getlastmodified', default='', namespaces=ns) or '-'
    items.append((name, 'dir' if is_dir else 'file', size, lastmod))

print(f"items={len(items)}")
for name, kind, size, lastmod in sorted(items):
    print(f"{kind}\t{size}\t{lastmod}\t{name}")
PY
