# Live Change Record — Bashrc Codex Default Launcher Apply

- Timestamp (UTC): 2026-02-17 02:46:31 UTC
- Host: Server3
- Live target path: `/home/architect/.bashrc`
- Repo source-of-truth snippet: `infra/bash/home/architect/.bashrc`
- Apply method: `bash ops/bash/deploy-bashrc.sh apply` (executed in operator shell)

## Observed Live State

- Managed block markers exist in `/home/architect/.bashrc`:
  - `# >>> matrix-managed architect launcher >>>`
  - `# <<< matrix-managed architect launcher <<<`
- Launcher functions present in active shell resolution:
  - `codex()` -> `command codex -s danger-full-access -a never "$@"`
  - `architect()` -> `codex "$@"`

## Verification Evidence

Command run:

```bash
bash -ic 'type codex; type architect'
```

Result summary:
- `codex is a function`
- `architect is a function`

## Notes

- This record captures the live apply state after managed launcher rollout.
- No additional live paths were modified for this change record.
