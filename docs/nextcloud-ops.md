# Nextcloud Ops (Server3)

## Purpose
Deterministic scripts for Nextcloud file and calendar operations used by `Nextcloud ...` Telegram keyword routing.

## Credential Setup
1. Create local secret file:
```bash
mkdir -p /home/architect/.config/nextcloud
chmod 700 /home/architect/.config/nextcloud
cp /home/architect/matrix/infra/env/nextcloud-ops.env.example /home/architect/.config/nextcloud/ops.env
chmod 600 /home/architect/.config/nextcloud/ops.env
```
2. Fill real values in `/home/architect/.config/nextcloud/ops.env`.

## Scripts
- List files:
```bash
bash ops/nextcloud/nextcloud-files-list.sh /Documents
```
- Upload file:
```bash
bash ops/nextcloud/nextcloud-file-upload.sh /tmp/report.pdf /Documents/report.pdf
```
- Delete file:
```bash
bash ops/nextcloud/nextcloud-file-delete.sh /Documents/report.pdf
```
- List calendars:
```bash
bash ops/nextcloud/nextcloud-calendars-list.sh
```
- Create event:
```bash
bash ops/nextcloud/nextcloud-calendar-create-event.sh \
  --calendar personal \
  --title "Dentist" \
  --start "2026-03-03 15:00" \
  --end "2026-03-03 16:00" \
  --description "Checkup"
```
