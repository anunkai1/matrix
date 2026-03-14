# Server3 State Backup

## Purpose

Keep Server3 rebuildable from the attached USB backup disk without trying to
duplicate the Arr media payload itself.

This backup path is for:

- host rebuild continuity
- assistant/runtime recovery
- media-stack config and database recovery
- monitoring and systemd/env recovery
- restore-runbook clarity

This backup path is not for:

- `/srv/external/server3-arr/media`
- `/srv/external/server3-arr/downloads`
- long-term off-host replication

## What Exists Today

`server3-state-backup` is the canonical backup path for Server3.

- live config file: `/etc/default/server3-state-backup`
- live service: `server3-state-backup.service`
- live timer: `server3-state-backup.timer`
- backup root: `/srv/external/server3-backups/state`

The backup is now designed as a monthly, quiesced snapshot. It briefly stops the
configured runtime services, archives rebuild-critical state, writes a manifest
plus checksums plus git bundle, then starts the services again.

## Backup Scope

The live profile in `/etc/default/server3-state-backup` should cover:

- host config: `/etc/default`, `/etc/systemd/system`, `/etc/fstab`, `/etc/cron.d`, `/etc/sudoers.d`, relevant apt source files
- runtime identity/state: `/home/*/.codex`, `/home/*/.local/state`, runtime overlay roots, transport state directories
- media stack: `/srv/media-stack/config`, `/srv/media-stack/docker-compose.yml`
- monitoring stack: `/srv/server3-monitoring` excluding Prometheus TSDB churn
- network continuity: `/var/lib/tailscale`, `/var/lib/nordvpn`
- repo continuity: git bundle for `/home/architect/matrix`

The profile must exclude the Arr payload paths and obvious transient files such
as sockets, pid files, and shell snapshots.

## Schedule

- cadence: monthly
- time: `05:00` AEST on day `1`
- retention: `12` snapshots by default

`05:00` is used intentionally to avoid colliding with:

- `telegram-architect-memory-restore-drill.timer`
- `server3-monthly-apt-upgrade.timer`

## Backup Configuration

`/etc/default/server3-state-backup` is a sourced bash file.

Expected fields:

- `SERVER3_STATE_BACKUP_ROOT`
- `SERVER3_STATE_BACKUP_RETENTION_COUNT`
- `SERVER3_STATE_BACKUP_HOSTNAME`
- `SERVER3_STATE_BACKUP_REPO_PATH`
- `SERVER3_STATE_BACKUP_FAIL_ON_MISSING`
- `SERVER3_STATE_BACKUP_STOP_UNITS=( ... )`
- `SERVER3_STATE_BACKUP_INCLUDE_PATHS=( ... )`
- `SERVER3_STATE_BACKUP_EXCLUDE_PATTERNS=( ... )`

Tracked example: `infra/env/server3-state-backup.env.example`

## Snapshot Contents

Each snapshot directory contains:

- `server3-state.tar.gz`
- `server3-matrix.bundle`
- `MANIFEST.txt`
- `SHA256SUMS.txt`

The manifest records:

- timestamp and host
- archive size
- repo path, commit, remote, bundle status
- Codex/Node/npm versions
- stop outcomes and restart dispatch outcomes
- include/missing/exclude lists

## Manual Backup Commands

Dry-run the backup plan:

```bash
sudo /home/architect/matrix/ops/server3_state/backup_state.sh --dry-run
```

Run the backup:

```bash
sudo systemctl start server3-state-backup.service
sudo systemctl status server3-state-backup.service --no-pager
```

## Backup Verification

```bash
sudo systemctl status server3-state-backup.timer --no-pager
ls -lah /srv/external/server3-backups/state
sudo sed -n '1,220p' /srv/external/server3-backups/state/<timestamp>/MANIFEST.txt
sudo cat /srv/external/server3-backups/state/<timestamp>/SHA256SUMS.txt
```

The backup is considered valid when:

- the archive exists
- the git bundle exists
- `repo_bundle_created=yes`
- the manifest shows no unexpected missing paths
- checksums verify cleanly

## Fresh-Host Restore Procedure

1. Reinstall the base OS.
2. Restore the backup disk mount and mount `/srv/external/server3-backups`.
3. Reattach the Arr disk if available and mount `/srv/external/server3-arr`.
4. Copy or clone the `matrix` repo to `/home/architect/matrix` if it is not already present.
5. Extract the chosen snapshot:

```bash
sudo /home/architect/matrix/ops/server3_state/restore_state.sh \
  /srv/external/server3-backups/state/<timestamp> \
  --target / \
  --bootstrap \
  --start-services
```

6. Run the restore verifier:

```bash
sudo /home/architect/matrix/ops/server3_state/verify_restore.sh
```

7. If the Arr disk is unavailable because of disk failure, re-run verification without requiring the media mount and treat media content as intentionally absent.

## What `bootstrap_host.sh` Does

`bootstrap_host.sh` is for a fresh host after the state archive has been laid
down on `/`.

It:

- installs baseline packages (`docker`, `git`, `python3`, `npm`, `sqlite3`, etc.)
- installs `tailscale` and `nordvpn` if their apt sources are present
- recreates required service users/groups with the live Server3 UID/GID map
- ensures key mountpoint/data directories exist
- ensures Docker is enabled/running
- installs the target Codex CLI version if needed

## What `verify_restore.sh` Checks

- backup disk mount is present
- media disk mount is present or warned about
- key Server3 services are active
- key timers are enabled and waiting
- media-stack and monitoring containers are running
- Jellyfin, Sonarr, Radarr, qBittorrent, Jellyseerr, Prowlarr, Prometheus, and Grafana are reachable
- `codex --version` is available on the restored host

## Operational Notes

- This backup path is local-only. If the whole machine and both attached disks are lost together, this backup does not help.
- The backup intentionally prefers completeness of Server3 runtime state over a tiny archive.
- If a configured include path disappears unexpectedly, the backup fails instead of silently producing an incomplete snapshot.
