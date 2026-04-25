# Server3 Shared Codex Auth

## Goal
- Use one canonical Codex login across trusted Server3 runtime users.
- Share only the credential file.
- Keep each runtime user's own `.codex` history, SQLite state, sessions, and config separate.

## Canonical Path
- Shared group: `codexauth`
- Shared auth file: `/etc/server3-codex/auth.json`
- Permissions:
  - `/etc/server3-codex`: `root:codexauth` `750`
  - `/etc/server3-codex/auth.json`: `root:codexauth` `640`

## Why This Model
- Safe enough for trusted service users on the same host.
- Avoids drift where one runtime has stale or different login credentials.
- Prevents accidental sharing of `.codex` history, session DBs, and per-user config.

## Risks
- Any user who can read the shared auth file can act as the same Codex identity and consume the same quota.
- If the shared auth file is rotated or broken, every linked runtime is affected at once.
- Do not use this model for untrusted human shell accounts.

## Install / Refresh
Use the shared-auth installer from the repo root:

```bash
ops/codex/install_shared_auth.sh architect govorun macrorayd oracle agentsmith tank trinity sentinel diary mavali_eth
```

Refresh the canonical shared auth file from `architect` and relink the same users:

```bash
ops/codex/install_shared_auth.sh --refresh-shared architect govorun macrorayd oracle agentsmith tank trinity sentinel diary mavali_eth
```

## Automatic Refresh
- `server3-codex-auth-sync.service` runs `ops/codex/watch_shared_auth.py`.
- The watcher checks for drift every 2 seconds by default.
- When `codex logout`, `codex login`, or the Codex CLI replaces Architect's auth file, the watcher runs `ops/codex/sync_shared_auth.sh`.
- The sync refreshes `/etc/server3-codex/auth.json` from Architect when needed, and relinks all manifest runtimes that depend on an authenticated Codex executor, including Sentinel.
- The Telegram executor still runs the same sync hook before Codex exec as a fallback, so a missed path event is corrected on the next bridge turn.

## Future Runtime Users
When you create a new trusted runtime user:
1. create the Linux user/home/runtime as usual
2. run `ops/codex/install_shared_auth.sh <new-user>`
3. restart that runtime's service so the new `codexauth` group membership is applied

The installer will:
- create the `codexauth` group if missing
- seed `/etc/server3-codex/auth.json` from `/home/architect/.codex/auth.json` if the shared file is missing
- keep the user's existing `config.toml` and other `.codex` files untouched
- replace only `~/.codex/auth.json` with a symlink to the canonical shared auth file

## Verification
- `sudo -u <user> test -L /home/<user>/.codex/auth.json`
- `sudo -u <user> readlink -f /home/<user>/.codex/auth.json`
- `sudo -u <user> codex --version`
- `systemctl status server3-codex-auth-sync.service --no-pager`
- restart the runtime service and check `systemctl status`
