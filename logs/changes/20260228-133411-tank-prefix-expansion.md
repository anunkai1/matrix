# Server3 Change Record - Tank Prefix Expansion

Timestamp: 2026-02-28T13:34:11+10:00
Timezone: Australia/Brisbane

## Objective
- Expand Tank trigger prefixes to include `hey tank` and `t-a-n-k`.

## Scope
- In scope:
  - live env file `/etc/default/telegram-tank-bridge`
  - repo mirror `infra/env/telegram-tank-bridge.server3.redacted.env`
  - `SERVER3_SUMMARY.md`
  - this `logs/changes` record
- Out of scope:
  - no code-path changes
  - no allowlist/service unit changes

## Changes Made
1. Updated live Tank prefix list:
   - `TELEGRAM_REQUIRED_PREFIXES=@tankhas_bot,tank,hey tank,t-a-n-k`
2. Synced same value into repo mirror env file.
3. Restarted Tank bridge service to apply env change.

## Validation
- Service status:
  - `telegram-tank-bridge.service` active/running
  - start time: `Sat 2026-02-28 13:34:04 AEST`
  - main pid: `109572`
- Prefix parser checks (ignore-case enabled) now pass:
  - `TANK do this`
  - `hey tank do this`
  - `t-a-n-k do this`
- Non-prefix phrase still rejected:
  - `please tank do this`

## Notes
- Voice requests using transcript-gated prefix checks inherit the same expanded prefix list.
