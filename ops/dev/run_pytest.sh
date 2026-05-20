#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "${script_dir}/../.." && pwd)"
venv_path="${repo_root}/.venv/server3-qa"

bootstrap_output="$(bash "${script_dir}/bootstrap_python_checks.sh" --venv "${venv_path}")"
resolved_venv="$(printf '%s\n' "${bootstrap_output}" | tail -n 1)"
python_bin="${resolved_venv}/bin/python3"

cd "${repo_root}"

exec "${python_bin}" -m pytest "$@"
