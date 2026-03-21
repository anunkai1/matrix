#!/usr/bin/env bash
set -euo pipefail

mappings=(
  "/home/agentsmith/agentsmithbot/AGENTS.md|/home/architect/matrix/infra/runtime_personas/agentsmith.AGENTS.md"
  "/home/agentsmith/agentsmithbot/AGENTSMITH_INSTRUCTION.md|/home/architect/matrix/docs/runtime_docs/agentsmith/AGENTSMITH_INSTRUCTION.md"
  "/home/agentsmith/agentsmithbot/AGENTSMITH_SUMMARY.md|/home/architect/matrix/docs/runtime_docs/agentsmith/AGENTSMITH_SUMMARY.md"
  "/home/agentsmith/agentsmithbot/CAPABILITIES.md|/home/architect/matrix/docs/runtime_docs/agentsmith/CAPABILITIES.md"
  "/home/agentsmith/agentsmithbot/LESSONS.md|/home/architect/matrix/docs/runtime_docs/agentsmith/LESSONS.md"
  "/home/agentsmith/agentsmithbot/private/SOUL.md|/home/architect/matrix/docs/runtime_docs/agentsmith/private/SOUL.md"
  "/home/tank/tankbot/AGENTS.md|/home/architect/matrix/infra/runtime_personas/tank.AGENTS.md"
  "/home/tank/tankbot/ARCHITECT_HANDOVER_PROMPT.md|/home/architect/matrix/docs/runtime_docs/tank/ARCHITECT_HANDOVER_PROMPT.md"
  "/home/tank/tankbot/THINKING_TO_NOW_TRANSCRIPT.md|/home/architect/matrix/docs/runtime_docs/tank/THINKING_TO_NOW_TRANSCRIPT.md"
  "/home/govorun/govorunbot/AGENTS.md|/home/architect/matrix/infra/runtime_personas/govorun.AGENTS.md"
  "/home/govorun/govorunbot/README.md|/home/architect/matrix/docs/runtime_docs/govorun/README.md"
  "/home/trinity/trinitybot/AGENTS.md|/home/architect/matrix/infra/runtime_personas/trinity.AGENTS.md"
  "/home/oracle/oraclebot/AGENTS.md|/home/architect/matrix/infra/runtime_personas/oracle.AGENTS.md"
  "/home/mavali_eth/mavali_ethbot/AGENTS.md|/home/architect/matrix/infra/runtime_personas/mavali_eth.AGENTS.md"
  "/home/macrorayd/macroraydbot/AGENTS.md|/home/architect/matrix/infra/runtime_personas/macrorayd.AGENTS.md"
)

failures=0
for entry in "${mappings[@]}"; do
  runtime_path="${entry%%|*}"
  repo_path="${entry#*|}"

  if ! sudo test -e "${runtime_path}"; then
    echo "[missing-runtime] ${runtime_path}" >&2
    failures=$((failures + 1))
    continue
  fi

  if ! sudo test -L "${runtime_path}"; then
    echo "[not-symlink] ${runtime_path}" >&2
    failures=$((failures + 1))
    continue
  fi

  actual_target="$(sudo readlink -f "${runtime_path}")"
  expected_target="$(readlink -f "${repo_path}")"
  if [[ "${actual_target}" != "${expected_target}" ]]; then
    echo "[mismatch] ${runtime_path}" >&2
    echo "  expected: ${expected_target}" >&2
    echo "  actual:   ${actual_target}" >&2
    failures=$((failures + 1))
    continue
  fi

  echo "[ok] ${runtime_path} -> ${actual_target}"
done

if (( failures > 0 )); then
  echo "[fail] ${failures} runtime doc link issue(s) detected" >&2
  exit 1
fi

echo "[ok] All tracked runtime docs are repo-backed as expected"
