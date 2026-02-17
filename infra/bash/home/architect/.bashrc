# Managed by matrix repo: codex full-access launchers.
codex() {
  command codex -s danger-full-access -a never "$@"
}

architect() {
  codex "$@"
}
