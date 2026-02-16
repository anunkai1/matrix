# Codex Agent Instructions — Server3 (matrix)

AUTHORITATIVE RULES:
- ./ARCHITECT_INSTRUCTION.md

INSTRUCTIONS:
1) Read `ARCHITECT_INSTRUCTION.md` first and follow it exactly.
2) If anything conflicts, `ARCHITECT_INSTRUCTION.md` wins.
3) All server changes must be GitHub-traceable via this repo:
   - inside `/home/architect/matrix`: commit + push required.
   - outside `/home/architect/matrix` (for example `~/.bashrc`, `/etc`, `/var/www`): mirror under `infra/`, use `ops/` for apply/rollback scripts, use `docs/` for runbooks, record execution in `logs/`, then commit + push in the same session.
4) No session may end with undocumented or unpushed server-side changes.

## Assistant Profile (Persistent for matrix)
- Assistant name: Architect
