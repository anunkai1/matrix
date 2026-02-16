# Codex Agent Instructions — Server3 (matrix)

AUTHORITATIVE RULES:
- ./ARCHITECT_INSTRUCTION.md

INSTRUCTIONS:
1) Read `ARCHITECT_INSTRUCTION.md` first and follow it exactly.
2) If anything conflicts, `ARCHITECT_INSTRUCTION.md` wins.
3) All server changes must be GitHub-traceable via this repo:
   - inside `/home/architect/matrix`: commit + push required.
   - outside `/home/architect/matrix` (for example `~/.bashrc`, `/etc`, `/var/www`): follow `ARCHITECT_INSTRUCTION.md` mandatory `infra/` + `ops/` + `docs/` + `logs/` structure, then commit + push in the same session.
4) No session may end with undocumented or unpushed server-side changes.
5) After each completed task/change set, update `SERVER3_PROGRESS.md` with a high-level “what happened overall” summary, then commit + push in the same session.

## Assistant Profile (Persistent for matrix)
- Assistant name: Architect
