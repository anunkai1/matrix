# Live Change Record - 2026-03-03T19:36:43+10:00

## Objective
Update Server3 Codex CLI to the latest npm release and remove the active runtime mismatch where `/usr/local/bin/codex` still resolved to `0.106.0`.

## Repo State
- Branch: `main`
- Repo: `/home/architect/matrix`

## Live Changes Applied
1. Verified registry latest:
   - `npm view @openai/codex version` -> `0.107.0`
2. Updated Codex CLI in `/usr/local`:
   - `sudo npm install -g --prefix /usr/local @openai/codex@latest`

## Verification Outcomes
1. Active CLI version:
   - `codex --version` -> `codex-cli 0.107.0`
2. Path resolution:
   - `type -a codex` -> `/usr/local/bin/codex`, `/usr/bin/codex`, `/bin/codex`
3. Installed package versions:
   - `node -p "require('/usr/local/lib/node_modules/@openai/codex/package.json').version"` -> `0.107.0`
   - `node -p "require('/usr/lib/node_modules/@openai/codex/package.json').version"` -> `0.107.0`

## Repo Mirrors Updated
- `infra/system/codex/server3.codex-cli.target-state.md`
- `logs/changes/20260303-193640-server3-codex-cli-update-latest.md`
- `SERVER3_SUMMARY.md`
