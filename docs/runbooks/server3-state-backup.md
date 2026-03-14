# Server3 State Backup

## Purpose

Capture rebuild-critical Server3 state without backing up the media library itself.

This backup path is for:

- host rebuild continuity
- app/config recovery
- restore-runbook clarity

This backup path is not for:

- movies/shows/media payload backup

## Live Model

- backup service: `server3-state-backup.service`
- backup timer: `server3-state-backup.timer`
- live config file: `/etc/default/server3-state-backup`
- default backup root: `/srv/external/server3-backups/state`

## Configuration

`/etc/default/server3-state-backup` is a sourced bash file.

Expected fields:

- `SERVER3_STATE_BACKUP_ROOT`
- `SERVER3_STATE_BACKUP_RETENTION_COUNT`
- `SERVER3_STATE_BACKUP_HOSTNAME`
- `SERVER3_STATE_BACKUP_REPO_PATH`
- `SERVER3_STATE_BACKUP_SOURCES=( ... )`

The source list should contain rebuild-critical state only, such as:

- compose roots
- app state/config directories
- env files
- mount config
- systemd units
- operational cron files

Do not include the media payload tree in the source list.

## Snapshot Contents

Each snapshot directory contains:

- state archive tarball
- repo git bundle (when available)
- manifest file
- sha256 checksum file

## Manual Run

```bash
sudo systemctl start server3-state-backup.service
sudo systemctl status server3-state-backup.service --no-pager
```

## Verification

```bash
sudo systemctl status server3-state-backup.timer --no-pager
ls -lah /srv/external/server3-backups/state
```

Check latest snapshot for:

- `MANIFEST.txt`
- `SHA256SUMS.txt`
- `*-state.tar.gz`
- `*-matrix.bundle`

## Restore Shape

High-level restore flow:

1. Reinstall base OS.
2. Restore mount configuration and attach the backup disk.
3. Extract the latest state archive at `/`.
4. Restore or reclone the repo.
5. Restore env/unit files from the archive if needed.
6. Re-enable/start the relevant services.
7. Reattach the media disk at its expected mountpoint.
8. Verify service health and app paths.

Use the manifest to confirm the exact snapshot contents and repo commit.
