#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=ops/nextcloud/nextcloud-common.sh
source "$SCRIPT_DIR/nextcloud-common.sh"

require_cmd curl
require_cmd python3
load_nextcloud_ops_env

DAV_URL="${NEXTCLOUD_BASE_URL}/remote.php/dav/calendars/${NEXTCLOUD_USERNAME}/"
TMP_XML="$(mktemp)"
trap 'rm -f "$TMP_XML"' EXIT

HTTP_CODE="$(
  nextcloud_auth_curl \
    -o "$TMP_XML" \
    -w '%{http_code}' \
    -X PROPFIND \
    -H 'Depth: 1' \
    -H 'Content-Type: application/xml' \
    --data '<?xml version="1.0"?><d:propfind xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav"><d:prop><d:displayname/><d:resourcetype/><c:supported-calendar-component-set/></d:prop></d:propfind>' \
    "$DAV_URL"
)"

if [[ "$HTTP_CODE" != "207" ]]; then
  echo "Nextcloud calendar PROPFIND failed (HTTP $HTTP_CODE)." >&2
  exit 5
fi

python3 - "$TMP_XML" <<'PY'
import sys
import xml.etree.ElementTree as ET
from urllib.parse import urlparse, unquote

ns = {'d': 'DAV:', 'c': 'urn:ietf:params:xml:ns:caldav'}
root = ET.parse(sys.argv[1]).getroot()
responses = root.findall('d:response', ns)
items = []
for response in responses[1:]:
    href = response.findtext('d:href', default='', namespaces=ns) or ''
    prop = response.find('d:propstat/d:prop', ns)
    if prop is None:
        continue
    resource = prop.find('d:resourcetype', ns)
    if resource is None or resource.find('c:calendar', ns) is None:
        continue
    display = prop.findtext('d:displayname', default='', namespaces=ns) or ''
    slug = unquote(urlparse(href).path.rstrip('/').split('/')[-1])
    name = display or slug
    items.append((name, slug, unquote(href)))

print(f"calendars={len(items)}")
for name, slug, href in sorted(items):
    print(f"{name}\tslug={slug}\thref={href}")
PY
