# Live Change Record - 2026-04-24T12:05:11+10:00

## Objective
Update the host-global Server3 Codex CLI from `0.121.0` to `0.124.0`.

## Repo State
- Branch: `main`
- Repo: `/home/architect/matrix`
- Pre-existing unrelated modified files were left untouched:
  - `docs/server3-control-plane-data.js`
  - `docs/server3-control-plane-data.json`
  - `src/telegram_bridge/handlers.py`
  - `src/telegram_bridge/memory_engine.py`
  - `tests/telegram_bridge/test_bridge_core.py`

## Live Changes Applied
1. Verified the npm registry target:
   - `npm view @openai/codex version` -> `0.124.0`
2. Updated the system-global Codex CLI in `/usr`:
   - `sudo npm install -g @openai/codex@0.124.0`

## Verification Outcomes
1. Active CLI version:
   - `codex --version` -> `codex-cli 0.124.0`
2. Path resolution:
   - `type -a codex` -> `/usr/bin/codex`, `/bin/codex`
3. Installed package version:
   - `node -p "require('/usr/lib/node_modules/@openai/codex/package.json').version"` -> `0.124.0`

## Repo Mirrors Updated
- `infra/system/codex/server3.codex-cli.target-state.md`
- `logs/changes/20260424-120511-server3-codex-cli-update-0.124.0-live.md`
- `SERVER3_SUMMARY.md`
- `SERVER3_ARCHIVE.md`
