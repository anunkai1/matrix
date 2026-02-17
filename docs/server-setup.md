# Server Setup Operations

## Codex Launcher (`codex`, `architect`)

Source of truth:
- `infra/bash/home/architect/.bashrc`

Deploy to live shell profile:
```bash
bash ops/bash/deploy-bashrc.sh apply
source ~/.bashrc
```

Verify:
```bash
type codex
type architect
```

Default behavior:
- `codex ...` runs as `codex -s danger-full-access -a never ...`
- `architect ...` calls the same default launcher

Bypass wrapper (use raw binary flags manually):
```bash
command codex --help
```

Rollback:
```bash
bash ops/bash/deploy-bashrc.sh rollback
source ~/.bashrc
```
