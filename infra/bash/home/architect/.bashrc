# Managed by matrix repo: codex full-access launchers.
codex() {
  command codex -s danger-full-access -a never "$@"
}

architect() {
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

  CLI_LAUNCHER_NAME=architect \
  CLI_ASSISTANT_NAME=Architect \
  CLI_CONVERSATION_KEY=shared:architect:main \
  TELEGRAM_BRIDGE_STATE_DIR=/home/architect/.local/state/telegram-architect-bridge \
  TELEGRAM_MEMORY_SQLITE_PATH=/home/architect/.local/state/telegram-architect-bridge/memory.sqlite3 \
  command python3 /home/architect/matrix/src/architect_cli/main.py "$@"
}
