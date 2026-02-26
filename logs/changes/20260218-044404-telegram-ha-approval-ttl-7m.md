# Change Record: Telegram HA Approval TTL Reduced to 7 Minutes

## Timestamp
- 2026-02-18 04:44:04 UTC

## Scope
- Live path edited: `/etc/default/telegram-architect-bridge`
- Repo mirror updated: `infra/env/telegram-architect-bridge.server3.redacted.env`

## Applied Change
- `TELEGRAM_HA_APPROVAL_TTL_SECONDS=3600` -> `TELEGRAM_HA_APPROVAL_TTL_SECONDS=420`

## Service Apply
- `telegram-architect-bridge.service` restarted.

## Verification
- Live env file contains `TELEGRAM_HA_APPROVAL_TTL_SECONDS=420`.
- Running bridge process environment contains `TELEGRAM_HA_APPROVAL_TTL_SECONDS=420`.
- Service status is `active (running)` after apply.
