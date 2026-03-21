## Runtime Personas

This directory stores the canonical `AGENTS.md` persona files for Server3 runtimes.

Purpose:
- keep runtime identity and policy under version control
- make `matrix` the source of truth for persona files
- avoid leaving important persona files only in local runtime roots

Current state:
- the main runtime `AGENTS.md` files are now repo-backed from this directory via live symlinks
- verify that wiring with:
  - `bash ops/runtime_personas/check_runtime_repo_links.sh`

Notes:
- keep secrets, tokens, local state, caches, attachments, and runtime databases out of this directory
- runtime roots under `/home/<user>/...` remain the live deployment paths, not the canonical source
