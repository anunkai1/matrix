#!/usr/bin/env bash
set -euo pipefail

ACTION="${1:-}"
LOCAL_DB="${SIGNALTUBE_LAB_DB_PATH:-/home/architect/matrix/private/signaltube/signaltube.sqlite}"
REMOTE_HOST="${SIGNALTUBE_SERVER2_HOST:-server2}"
REMOTE_DB="${SIGNALTUBE_SERVER2_DB_PATH:-/home/lepton/signaltube-api/data/signaltube.sqlite}"
REMOTE_HTML="${SIGNALTUBE_SERVER2_HTML_PATH:-/var/www/mavali.top/projects/SignalTube/index.html}"
REMOTE_APP_DIR="${SIGNALTUBE_SERVER2_APP_DIR:-/home/lepton/signaltube-api}"
REMOTE_TITLE="${SIGNALTUBE_SERVER2_TITLE:-SignalTube}"
REMOTE_API_BASE_PATH="${SIGNALTUBE_SERVER2_API_BASE_PATH:-/signaltube/api}"

if [[ -z "$ACTION" ]]; then
  echo "Usage: $0 [pull|push]" >&2
  exit 2
fi

mkdir -p "$(dirname "$LOCAL_DB")"

remote_has_db() {
  ssh "$REMOTE_HOST" "sudo test -f '$REMOTE_DB'"
}

pull_db() {
  if ! remote_has_db; then
    echo "remote SignalTube DB missing on ${REMOTE_HOST}; skipping pull"
    return 0
  fi
  rsync -a --rsync-path="sudo rsync" "${REMOTE_HOST}:${REMOTE_DB}" "$LOCAL_DB"
  echo "pulled SignalTube DB from ${REMOTE_HOST}:${REMOTE_DB}"
}

push_db() {
  if [[ ! -f "$LOCAL_DB" ]]; then
    echo "local SignalTube DB missing: $LOCAL_DB" >&2
    exit 1
  fi
  rsync -a --rsync-path="sudo rsync" "$LOCAL_DB" "${REMOTE_HOST}:${REMOTE_DB}"
  ssh "$REMOTE_HOST" "sudo env REMOTE_DB='$REMOTE_DB' REMOTE_HTML='$REMOTE_HTML' REMOTE_APP_DIR='$REMOTE_APP_DIR' REMOTE_TITLE='$REMOTE_TITLE' REMOTE_API_BASE_PATH='$REMOTE_API_BASE_PATH' python3 - <<'PY'
from pathlib import Path
import os
import sys

app_dir = Path(os.environ['REMOTE_APP_DIR'])
sys.path.insert(0, str(app_dir))

from signaltube.render import render_feed
from signaltube.store import SignalTubeStore

db_path = Path(os.environ['REMOTE_DB'])
html_path = Path(os.environ['REMOTE_HTML'])

store = SignalTubeStore(db_path)
store.init()
render_feed(
    html_path,
    store.load_ranked(limit=200),
    title=os.environ['REMOTE_TITLE'],
    db_path=db_path,
    command_path=app_dir / 'server.py',
    api_base_path=os.environ['REMOTE_API_BASE_PATH'],
)
PY"
  ssh "$REMOTE_HOST" "sudo chown lepton:www-data '$REMOTE_DB' '$REMOTE_HTML'"
  echo "pushed SignalTube DB and rerendered frontend on ${REMOTE_HOST}"
}

case "$ACTION" in
  pull)
    pull_db
    ;;
  push)
    push_db
    ;;
  *)
    echo "Usage: $0 [pull|push]" >&2
    exit 2
    ;;
esac
