# Server Setup Operations

## Codex Launcher (`codex`, `architect`, `tank`)

Source-of-truth snippets:
- `infra/bash/home/architect/.bashrc`
- `infra/bash/home/tank/.bashrc`

Deploy to live shell profile:
```bash
# architect profile (default)
bash ops/bash/deploy-bashrc.sh apply
source ~/.bashrc

# tank profile
sudo BASHRC_PROFILE=tank TARGET_BASHRC=/home/tank/.bashrc bash ops/bash/deploy-bashrc.sh apply
sudo -u tank bash -ic 'type tank'
```

Verify:
```bash
type codex
type architect
type tank
```

Default behavior:
- `codex ...` runs as `codex -s danger-full-access -a never ...`
- `architect ...` calls the same default launcher
- `tank ...` (for user `tank`) calls the same default launcher with tank-specific shared memory paths

Bypass wrapper (use raw binary flags manually):
```bash
command codex --help
```

Rollback:
```bash
bash ops/bash/deploy-bashrc.sh rollback
source ~/.bashrc
```
