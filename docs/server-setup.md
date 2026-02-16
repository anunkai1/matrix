# Server Setup Operations

## Architect Launcher (`architect`)

Source of truth:
- `infra/bash/home/architect/.bashrc`

Deploy to live shell profile:
```bash
bash ops/bash/deploy-bashrc.sh apply
source ~/.bashrc
```

Verify:
```bash
type architect
```

Rollback:
```bash
bash ops/bash/deploy-bashrc.sh rollback
source ~/.bashrc
```
