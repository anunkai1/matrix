# Server3 Nextcloud Ops Target State

## Intent
Provide deterministic Nextcloud file/calendar operations for Architect bridge keyword routing.

## Live Secrets Path (not in git)
- `/home/architect/.config/nextcloud/ops.env`
- Loaded by `ops/nextcloud/nextcloud-common.sh`

## Mirrored Redacted State
- `infra/env/nextcloud-ops.server3.redacted.env`
- `infra/env/nextcloud-ops.env.example`

## Runtime Scripts
- `ops/nextcloud/nextcloud-files-list.sh`
- `ops/nextcloud/nextcloud-file-upload.sh`
- `ops/nextcloud/nextcloud-file-delete.sh`
- `ops/nextcloud/nextcloud-calendars-list.sh`
- `ops/nextcloud/nextcloud-calendar-create-event.sh`

## Bridge Routing
- Telegram keyword trigger: `Nextcloud ...`
- Execution mode: stateless priority routing
