## Runtime Personas

This directory stores tracked persona and policy files for Server3 runtimes.

Purpose:
- keep runtime identity/policy under version control
- provide a canonical repo copy for review and history
- avoid leaving important persona files only in local runtime roots

Important:
- a file here is not automatically live
- the active runtime may still read its local `AGENTS.md` from its runtime root
- a runtime becomes repo-backed only after an explicit link or sync step

Safe rollout model:
1. track the current runtime persona here
2. verify the tracked copy matches the live local file
3. later, if desired, link or sync the runtime root to this repo copy

Keep secrets, tokens, local state, caches, and attachments out of this directory.
