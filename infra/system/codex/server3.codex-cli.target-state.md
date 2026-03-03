# Server3 Codex CLI Target State

- Timestamp (Australia/Brisbane ISO-8601): 2026-03-03T19:36:43+10:00
- Scope: system-wide Codex CLI runtime paths for Server3 (`/usr/local` preferred)

## Runtime Components
- Node.js: `v22.22.0`
- npm: `10.9.4`
- Global npm prefix (system): `/usr`
- Preferred Codex binary path: `/usr/local/bin/codex`
- Additional Codex paths in `PATH`: `/usr/bin/codex`, `/bin/codex`

## Target Version
- npm latest at apply time: `@openai/codex@0.107.0`
- `/usr/local/lib/node_modules/@openai/codex/package.json` version: `0.107.0`
- `/usr/lib/node_modules/@openai/codex/package.json` version: `0.107.0`
- `codex --version`: `codex-cli 0.107.0`

## Apply / Rollback
- Apply latest to `/usr/local`:
  - `sudo npm install -g --prefix /usr/local @openai/codex@latest`
- Roll back to previous known version if needed:
  - `sudo npm install -g --prefix /usr/local @openai/codex@0.106.0`
