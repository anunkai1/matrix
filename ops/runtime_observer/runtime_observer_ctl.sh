#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "${SCRIPT_DIR}/../_lib/exec_python_from_dir.sh" "runtime_observer/runtime_observer.py" "$@"
