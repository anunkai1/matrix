# Server3 Codex CLI Target State

- Timestamp (Australia/Brisbane ISO-8601): 2026-04-24T12:05:11+10:00
- Scope: system-wide Codex CLI runtime paths for Server3

## Runtime Components
- Node.js: `v22.22.2`
- npm: `10.9.7`
- Global npm prefix (system): `/usr`
- Active Codex binary path: `/usr/bin/codex`

## Target Version
- `@openai/codex`: `0.124.0`
- `codex --version`: `codex-cli 0.124.0`

## Apply / Rollback
- Apply target version:
  - `sudo npm install -g @openai/codex@0.124.0`
- Roll back to previous known version:
  - `sudo npm install -g @openai/codex@0.121.0`
