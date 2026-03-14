# Server3 Codex CLI Target State

- Timestamp (Australia/Brisbane ISO-8601): 2026-03-15T08:52:39+10:00
- Scope: system-wide Codex CLI runtime paths for Server3

## Runtime Components
- Node.js: `v22.22.0`
- npm: `11.11.0`
- Global npm prefix (system): `/usr`
- Active Codex binary path: `/usr/bin/codex`

## Target Version
- `@openai/codex`: `0.114.0`
- `codex --version`: `codex-cli 0.114.0`

## Apply / Rollback
- Apply target version:
  - `sudo npm install -g @openai/codex@0.114.0`
- Roll back to previous known version:
  - `sudo npm install -g @openai/codex@0.112.0`
