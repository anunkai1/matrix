# Managed by matrix repo: codex full-access launchers (aster-trader profile).
codex() {
  command codex -s danger-full-access -a never "$@"
}

astertrader() {
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

  local shared_conversation_key="${ASTERTRADER_SHARED_CONVERSATION_KEY:-tg:211761499}"

  CLI_LAUNCHER_NAME=astertrader \
  CLI_ASSISTANT_NAME=AsterTrader \
  CLI_MEMORY_NAMESPACE=aster-trader \
  CLI_CONVERSATION_KEY="${shared_conversation_key}" \
  TELEGRAM_BRIDGE_STATE_DIR=/home/aster-trader/.local/state/telegram-aster-trader-bridge \
  TELEGRAM_MEMORY_SQLITE_PATH=/home/aster-trader/.local/state/telegram-aster-trader-bridge/memory.sqlite3 \
  command python3 /home/architect/matrix/src/architect_cli/main.py "$@"
}
