#!/usr/bin/env bash
set -euo pipefail

mode="${1:-new}"
thread_id="${2:-}"
if [[ "${mode}" != "new" && "${mode}" != "resume" ]]; then
  echo "Usage: $0 [new|resume] [thread_id]" >&2
  exit 2
fi
if [[ "${mode}" == "resume" && -z "${thread_id}" ]]; then
  echo "thread_id is required in resume mode" >&2
  exit 2
fi

prompt="$(cat)"
if [[ -z "${prompt}" ]]; then
  echo "Prompt is empty" >&2
  exit 2
fi

CODEX_BIN="${CODEX_BIN:-codex}"
if ! command -v "${CODEX_BIN}" >/dev/null 2>&1; then
  echo "codex binary not found: ${CODEX_BIN}" >&2
  exit 127
fi

if [[ -n "${ARCHITECT_EXEC_ARGS:-}" ]]; then
  # Optional override for operators, applied to new sessions only.
  read -r -a EXEC_ARGS <<<"${ARCHITECT_EXEC_ARGS}"
else
  EXEC_ARGS=(-s danger-full-access --color never)
fi

log_file="$(mktemp)"
cleanup() {
  rm -f "${log_file}"
}
trap cleanup EXIT

if [[ "${mode}" == "resume" ]]; then
  CMD=("${CODEX_BIN}" exec resume --dangerously-bypass-approvals-and-sandbox --json "${thread_id}" -)
else
  CMD=("${CODEX_BIN}" exec "${EXEC_ARGS[@]}" --json -)
fi

if ! printf '%s\n' "${prompt}" | "${CMD[@]}" >"${log_file}" 2>&1; then
  tail -n 80 "${log_file}" >&2 || true
  exit 1
fi

python3 - "${mode}" "${log_file}" <<'PY'
import json
import sys

mode = sys.argv[1]
path = sys.argv[2]
thread_id = None
message = None

with open(path, "r", encoding="utf-8", errors="replace") as f:
    for raw in f:
        line = raw.strip()
        if not line or line[0] != "{":
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue

        if not isinstance(obj, dict):
            continue

        if obj.get("type") == "thread.started" and isinstance(obj.get("thread_id"), str):
            thread_id = obj["thread_id"]
            continue

        if obj.get("type") != "item.completed":
            continue

        item = obj.get("item")
        if not isinstance(item, dict):
            continue

        if item.get("type") == "agent_message" and isinstance(item.get("text"), str):
            message = item["text"]

if mode == "new":
    if not thread_id:
        print("Failed to parse thread_id from codex json output", file=sys.stderr)
        raise SystemExit(1)
    print(f"THREAD_ID={thread_id}")

print("OUTPUT_BEGIN")
if message:
    print(message, end="")
PY
