# Runtime Doc Source Of Truth

## Rule
- `matrix` is the canonical source of truth for tracked runtime persona and companion documentation.
- Live runtime roots under `/home/<user>/...` are deployment paths that should point back to the repo copies.

## Tracked Areas
- Persona files: `/home/architect/matrix/infra/runtime_personas`
- Companion runtime docs: `/home/architect/matrix/docs/runtime_docs`

## Live Runtime Model
- Services still run from their own Unix users and runtime roots.
- The runtime root can contain symlinks to the canonical repo files.
- This keeps identity separation without creating multiple policy sources.

## What Stays Local
- `/etc/default/*` secrets and tokens
- `.local/state/*` runtime databases and state
- attachments, caches, transient logs
- any emergency local rollback artifacts kept temporarily during migration

## Verification
Run:

```bash
bash /home/architect/matrix/ops/runtime_personas/check_runtime_repo_links.sh
```

Expected result:
- every tracked runtime doc reports `[ok]`
- final line reports: `All tracked runtime docs are repo-backed as expected`

## Editing Rule
- Edit the repo copy in `matrix`.
- Do not hand-edit a live symlink target through the runtime root unless you are intentionally editing the same repo file.
- If a runtime doc stops being repo-backed, fix the link first instead of creating a second local source of truth.
