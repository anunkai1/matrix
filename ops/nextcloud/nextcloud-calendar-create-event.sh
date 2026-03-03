#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=ops/nextcloud/nextcloud-common.sh
source "$SCRIPT_DIR/nextcloud-common.sh"

usage() {
  cat <<'USAGE'
Usage:
  nextcloud-calendar-create-event.sh \
    --calendar <slug_or_display_name> \
    --title <text> \
    --start "<date/time>" \
    --end "<date/time>" \
    [--description <text>]

Examples:
  nextcloud-calendar-create-event.sh \
    --calendar personal \
    --title "Dentist" \
    --start "2026-03-03 15:00" \
    --end "2026-03-03 16:00"
USAGE
}

CALENDAR=""
TITLE=""
START_INPUT=""
END_INPUT=""
DESCRIPTION=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --calendar)
      CALENDAR="${2:-}"
      shift 2
      ;;
    --title)
      TITLE="${2:-}"
      shift 2
      ;;
    --start)
      START_INPUT="${2:-}"
      shift 2
      ;;
    --end)
      END_INPUT="${2:-}"
      shift 2
      ;;
    --description)
      DESCRIPTION="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ -z "$CALENDAR" || -z "$TITLE" || -z "$START_INPUT" || -z "$END_INPUT" ]]; then
  usage >&2
  exit 2
fi

require_cmd curl
require_cmd python3
require_cmd date
load_nextcloud_ops_env

START_UTC="$(date -u -d "$START_INPUT" +%Y%m%dT%H%M%SZ 2>/dev/null || true)"
END_UTC="$(date -u -d "$END_INPUT" +%Y%m%dT%H%M%SZ 2>/dev/null || true)"
if [[ -z "$START_UTC" || -z "$END_UTC" ]]; then
  echo "Invalid --start or --end datetime." >&2
  exit 2
fi

DAV_URL="${NEXTCLOUD_BASE_URL}/remote.php/dav/calendars/${NEXTCLOUD_USERNAME}/"
TMP_XML="$(mktemp)"
TMP_ICS="$(mktemp)"
trap 'rm -f "$TMP_XML" "$TMP_ICS"' EXIT

HTTP_CODE="$(
  nextcloud_auth_curl \
    -o "$TMP_XML" \
    -w '%{http_code}' \
    -X PROPFIND \
    -H 'Depth: 1' \
    -H 'Content-Type: application/xml' \
    --data '<?xml version="1.0"?><d:propfind xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav"><d:prop><d:displayname/><d:resourcetype/></d:prop></d:propfind>' \
    "$DAV_URL"
)"
if [[ "$HTTP_CODE" != "207" ]]; then
  echo "Failed to list calendars (HTTP $HTTP_CODE)." >&2
  exit 5
fi

CALENDAR_HREF="$(python3 - "$TMP_XML" "$CALENDAR" <<'PY'
import sys
import xml.etree.ElementTree as ET
from urllib.parse import urlparse, unquote

xml_path = sys.argv[1]
needle = sys.argv[2].strip().casefold()
ns = {'d': 'DAV:', 'c': 'urn:ietf:params:xml:ns:caldav'}
root = ET.parse(xml_path).getroot()
for response in root.findall('d:response', ns)[1:]:
    href = response.findtext('d:href', default='', namespaces=ns) or ''
    prop = response.find('d:propstat/d:prop', ns)
    if prop is None:
        continue
    resource = prop.find('d:resourcetype', ns)
    if resource is None or resource.find('c:calendar', ns) is None:
        continue
    display = (prop.findtext('d:displayname', default='', namespaces=ns) or '').strip()
    slug = unquote(urlparse(href).path.rstrip('/').split('/')[-1])
    if display.casefold() == needle or slug.casefold() == needle:
        print(unquote(href))
        sys.exit(0)
sys.exit(1)
PY
)" || {
  echo "Calendar not found: $CALENDAR" >&2
  exit 2
}

if [[ "$CALENDAR_HREF" != */ ]]; then
  CALENDAR_HREF="${CALENDAR_HREF}/"
fi

EVENT_UID="nc-$(date +%s)-$RANDOM@server3"
EVENT_FILE="${EVENT_UID}.ics"
DTSTAMP="$(date -u +%Y%m%dT%H%M%SZ)"

{
  printf 'BEGIN:VCALENDAR\n'
  printf 'VERSION:2.0\n'
  printf 'PRODID:-//Architect//NextcloudOps//EN\n'
  printf 'BEGIN:VEVENT\n'
  printf 'UID:%s\n' "$EVENT_UID"
  printf 'DTSTAMP:%s\n' "$DTSTAMP"
  printf 'DTSTART:%s\n' "$START_UTC"
  printf 'DTEND:%s\n' "$END_UTC"
  printf 'SUMMARY:%s\n' "$TITLE"
  if [[ -n "$DESCRIPTION" ]]; then
    printf 'DESCRIPTION:%s\n' "$DESCRIPTION"
  fi
  printf 'END:VEVENT\n'
  printf 'END:VCALENDAR\n'
} > "$TMP_ICS"

EVENT_URL="${NEXTCLOUD_BASE_URL}${CALENDAR_HREF}${EVENT_FILE}"
PUT_CODE="$(
  nextcloud_auth_curl \
    -o /dev/null \
    -w '%{http_code}' \
    -X PUT \
    -H 'Content-Type: text/calendar; charset=utf-8' \
    --data-binary "@$TMP_ICS" \
    "$EVENT_URL"
)"

if [[ "$PUT_CODE" != "201" && "$PUT_CODE" != "204" ]]; then
  echo "Failed to create calendar event (HTTP $PUT_CODE)." >&2
  exit 5
fi

echo "[nextcloud-calendar-create-event] calendar=${CALENDAR} uid=${EVENT_UID} status=${PUT_CODE}"
