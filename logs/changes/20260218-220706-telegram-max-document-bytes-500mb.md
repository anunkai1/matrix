# Change Record: Telegram bridge max document size set to 500MB

- Timestamp (UTC): 2026-02-18 22:07:06 UTC
- Operator: Codex (architect)
- Live path changed: `/etc/default/telegram-architect-bridge`
- Mirror file updated: `infra/env/telegram-architect-bridge.server3.redacted.env`

## Applied Change

- Set `TELEGRAM_MAX_DOCUMENT_BYTES=524288000` (500MB) in live env.
- Verified live value with:
  - `sudo grep '^TELEGRAM_MAX_DOCUMENT_BYTES=' /etc/default/telegram-architect-bridge`
- Verified service restart already occurred at:
  - `ExecMainStartTimestamp=Wed 2026-02-18 22:00:02 UTC`
  - `MainPID=10872`

## Verification

- Service state: `active (running)`
- Unit: `telegram-architect-bridge.service`
- Runtime check commands:
  - `bash ops/telegram-bridge/status_service.sh`
  - `systemctl show telegram-architect-bridge.service -p ActiveState -p SubState -p ExecMainPID -p ExecMainStartTimestamp`

## Notes

- Secrets were not committed.
- This record captures repo traceability for an already-applied live `/etc` change and restart.
