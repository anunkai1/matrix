#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "${script_dir}/../.." && pwd)"
venv_path="${repo_root}/.venv/server3-qa"
recreate="no"

usage() {
  cat <<'EOF'
Usage: bootstrap_python_checks.sh [--venv /path/to/venv] [--recreate]

Create or refresh the local QA virtualenv used for repo Python checks.
EOF
}

while (($# > 0)); do
  case "$1" in
    --venv)
      venv_path="${2:?missing venv path}"
      shift
      ;;
    --recreate)
      recreate="yes"
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

if [[ "${recreate}" == "yes" ]]; then
  rm -rf "${venv_path}"
fi

if [[ ! -x "${venv_path}/bin/python3" ]]; then
  python3 -m venv "${venv_path}"
fi

"${venv_path}/bin/python3" -m pip install --upgrade pip
"${venv_path}/bin/python3" -m pip install -r "${repo_root}/requirements-dev.txt"

echo "${venv_path}"
