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

  command python3 /home/architect/matrix/src/architect_cli/main.py "$@"
}
