#!/usr/bin/env bash
set -euo pipefail

now_ms() {
  local epoch="${EPOCHREALTIME/./}"
  printf '%s\n' "${epoch::-3}"
}

emit_phase_timing() {
  local phase="$1"
  local duration_ms="$2"
  printf '{"type":"executor.phase_timing","phase":"%s","duration_ms":%s,"mode":"%s"}\n' \
    "${phase}" "${duration_ms}" "${mode}" >&2
}

mode="${1:-new}"
if [[ "${mode}" != "new" && "${mode}" != "resume" ]]; then
  echo "Usage: $0 [new|resume] [thread_id] [--image FILE]..." >&2
  exit 2
fi
if (($# > 0)); then
  shift
fi

if [[ "${mode}" == "resume" ]]; then
  thread_id="${1:-}"
  if [[ -z "${thread_id}" ]]; then
    echo "thread_id is required in resume mode" >&2
    exit 2
  fi
  shift
else
  thread_id=""
fi

IMAGE_ARGS=()
while (($#)); do
  case "$1" in
    --image)
      if (($# < 2)); then
        echo "--image requires a file path" >&2
        exit 2
      fi
      image_path="$2"
      if [[ ! -f "${image_path}" ]]; then
        echo "image file not found: ${image_path}" >&2
        exit 2
      fi
      IMAGE_ARGS+=(-i "${image_path}")
      shift 2
      ;;
    *)
      echo "Unknown argument: $1" >&2
      echo "Usage: $0 [new|resume] [thread_id] [--image FILE]..." >&2
      exit 2
      ;;
  esac
done

bootstrap_started_ms="$(now_ms)"

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
shared_core_root="${TELEGRAM_SHARED_CORE_ROOT:-$(cd "${script_dir}/../.." && pwd)}"
if [[ "${shared_core_root}" != /* ]]; then
  shared_core_root="${script_dir}/../../${shared_core_root}"
fi
shared_core_root="$(cd "${shared_core_root}" && pwd)"

runtime_root="${TELEGRAM_RUNTIME_ROOT:-${shared_core_root}}"
if [[ "${runtime_root}" != /* ]]; then
  runtime_root="${shared_core_root}/${runtime_root}"
fi
runtime_root="$(cd "${runtime_root}" && pwd)"

codex_workdir="${TELEGRAM_CODEX_WORKDIR:-${runtime_root}}"
if [[ "${codex_workdir}" != /* ]]; then
  codex_workdir="${runtime_root}/${codex_workdir}"
fi
codex_workdir="$(cd "${codex_workdir}" && pwd)"

auth_sync_script="${shared_core_root}/ops/codex/sync_shared_auth.sh"
auth_sync_mode="${TELEGRAM_CODEX_AUTH_SYNC_MODE:-watcher}"
if [[ -x "${auth_sync_script}" && "${auth_sync_mode}" == "always" ]]; then
  auth_sync_started_ms="$(now_ms)"
  # Shared auth drift is normally handled by the dedicated watcher service.
  # Keep a legacy opt-in path for runtimes that still need sync-on-every-exec.
  "${auth_sync_script}" >/dev/null 2>&1 || true
  auth_sync_finished_ms="$(now_ms)"
  emit_phase_timing "auth_sync" "$((auth_sync_finished_ms - auth_sync_started_ms))"
fi

cd "${codex_workdir}"

style_hint="${TELEGRAM_RESPONSE_STYLE_HINT:-}"
first_prompt_line=""

stream_assembled_prompt() {
  # Stream the formatted prompt directly into Codex so large requests do not
  # pay an extra full-buffer copy inside the bash wrapper before exec starts.
  if [[ -n "${style_hint//[[:space:]]/}" ]]; then
    printf 'Response style guidance:\n%s\n\n' "${style_hint}"
  fi
  printf 'User request:\n%s\n' "${first_prompt_line}"
  cat <&3
}

CODEX_BIN="${CODEX_BIN:-codex}"
if ! command -v "${CODEX_BIN}" >/dev/null 2>&1; then
  echo "codex binary not found: ${CODEX_BIN}" >&2
  exit 127
fi

EXEC_COMMON_ARGS=()
if [[ -n "${ARCHITECT_EXEC_ARGS:-}" ]]; then
  # Optional override for operators, applied to both new and resumed sessions.
  read -r -a EXEC_COMMON_ARGS <<<"${ARCHITECT_EXEC_ARGS}"
fi
if [[ -n "${CODEX_MODEL:-}" ]]; then
  EXEC_COMMON_ARGS+=(-m "${CODEX_MODEL}")
fi
if [[ -n "${CODEX_REASONING_EFFORT:-}" ]]; then
  EXEC_COMMON_ARGS+=(-c "model_reasoning_effort=\"${CODEX_REASONING_EFFORT}\"")
fi
EXEC_NEW_ARGS=(--color never)

if [[ "${mode}" == "resume" ]]; then
  CMD=("${CODEX_BIN}" exec resume --dangerously-bypass-approvals-and-sandbox "${EXEC_COMMON_ARGS[@]}" --json "${IMAGE_ARGS[@]}" "${thread_id}" -)
else
  CMD=("${CODEX_BIN}" exec --dangerously-bypass-approvals-and-sandbox "${EXEC_NEW_ARGS[@]}" "${EXEC_COMMON_ARGS[@]}" --json "${IMAGE_ARGS[@]}" -)
fi

bootstrap_finished_ms="$(now_ms)"
emit_phase_timing "wrapper_bootstrap" "$((bootstrap_finished_ms - bootstrap_started_ms))"

codex_started_ms="$(now_ms)"
set +e
exec 3<&0
if ! IFS= read -r first_prompt_line <&3; then
  exec 3<&-
  set -e
  echo "Prompt is empty" >&2
  exit 2
fi
stream_assembled_prompt | "${CMD[@]}"
pipeline_status=("${PIPESTATUS[@]}")
exec 3<&-
set -e
codex_finished_ms="$(now_ms)"
emit_phase_timing "codex_exec" "$((codex_finished_ms - codex_started_ms))"
prompt_rc="${pipeline_status[0]}"
codex_rc="${pipeline_status[1]}"
if [[ "${prompt_rc}" -ne 0 ]]; then
  exit "${prompt_rc}"
fi
exit "${codex_rc}"
