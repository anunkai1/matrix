#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 '<free-form trade request>'" >&2
  exit 1
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
CHAT_KEY="cli:${USER}"
python3 "${REPO_ROOT}/ops/trading/aster/assistant_entry.py" --chat-id "${CHAT_KEY}" --request "$*"
