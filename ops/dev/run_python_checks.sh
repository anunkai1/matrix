#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "${script_dir}/../.." && pwd)"
venv_path="${repo_root}/.venv/server3-qa"
run_smoke="yes"

usage() {
  cat <<'EOF'
Usage: run_python_checks.sh [--venv /path/to/venv] [--skip-smoke]

Run the repo's local Python QA checks using the shared QA virtualenv.
EOF
}

while (($# > 0)); do
  case "$1" in
    --venv)
      venv_path="${2:?missing venv path}"
      shift
      ;;
    --skip-smoke)
      run_smoke="no"
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

bootstrap_output="$(bash "${script_dir}/bootstrap_python_checks.sh" --venv "${venv_path}")"
resolved_venv="$(printf '%s\n' "${bootstrap_output}" | tail -n 1)"
python_bin="${resolved_venv}/bin/python3"
ruff_bin="${resolved_venv}/bin/ruff"

cd "${repo_root}"

"${ruff_bin}" check src/telegram_bridge tests/telegram_bridge
"${ruff_bin}" check \
  ops/server3_runtime_status.py \
  ops/runtime_overlays/sync_server3_runtime_overlays.py \
  tests/test_server3_runtime_status.py \
  tests/test_sync_server3_runtime_overlays.py \
  --select E4,E7,E9,F,I
"${python_bin}" -m py_compile \
  src/telegram_bridge/main.py \
  src/telegram_bridge/executor.py \
  src/telegram_bridge/handlers.py \
  src/telegram_bridge/media.py \
  src/telegram_bridge/session_manager.py \
  src/telegram_bridge/state_store.py \
  src/telegram_bridge/structured_logging.py \
  src/telegram_bridge/stream_buffer.py \
  src/telegram_bridge/transport.py \
  ops/server3_runtime_status.py \
  ops/runtime_overlays/sync_server3_runtime_overlays.py
"${python_bin}" -m coverage run -m unittest discover -s tests/telegram_bridge -p 'test_*.py'
"${python_bin}" -m coverage report -m
"${python_bin}" -m unittest tests.test_server3_runtime_status tests.test_sync_server3_runtime_overlays
"${python_bin}" src/telegram_bridge/main.py --self-test
if [[ "${run_smoke}" == "yes" ]]; then
  PYTHON_BIN="${python_bin}" bash src/telegram_bridge/smoke_test.sh
fi
