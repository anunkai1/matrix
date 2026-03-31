#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

exec python3 "${REPO_ROOT}/ops/server3_control_plane/serve.py" "$@"
