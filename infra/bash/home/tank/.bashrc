# Managed by matrix repo: codex full-access launchers (tank profile).
codex() {
  command codex -s danger-full-access -a never "$@"
}

tank() {
  if (($# == 0)); then
    codex
    return
  fi

  case "$1" in
    exec|chat|auth|login|logout|mcp|sandbox|config|completion|help|update|whoami)
      codex "$@"
      return
      ;;
  esac

  CLI_LAUNCHER_NAME=tank \
  CLI_ASSISTANT_NAME=TANK \
  CLI_MEMORY_NAMESPACE=tank \
  TELEGRAM_BRIDGE_STATE_DIR=/home/tank/.local/state/telegram-tank-bridge \
  TELEGRAM_MEMORY_SQLITE_PATH=/home/tank/.local/state/telegram-tank-bridge/memory.sqlite3 \
  command python3 /home/architect/matrix/src/architect_cli/main.py "$@"
}
