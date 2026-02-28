# Change Log - WhatsApp Auth Hardening From Reference Review

- Timestamp (AEST): 2026-02-28T18:23:58+10:00
- Scope: Harden local WhatsApp bridge auth/session handling based on OpenClaw/NanoClaw implementation patterns.

## What Changed
- Updated `ops/whatsapp_govorun/bridge/src/common.mjs`:
  - added `createQueuedCredsSaver(authDir, saveCreds, logger)` helper
  - saves `creds.json` through a serialized queue
  - best-effort backup to `creds.backup.json` before writes
  - best-effort `0600` permission tightening on creds/backup files
- Updated `ops/whatsapp_govorun/bridge/src/auth.mjs`:
  - switched `creds.update` to queued saver
  - added websocket error logging hook
  - added one-time reconnect path for close code `515` during auth
  - added delayed exit (`1s`) on successful auth open to allow final creds flush
  - improved close handling with explicit `loggedOut` branch
- Updated `ops/whatsapp_govorun/bridge/src/index.mjs`:
  - switched `creds.update` to queued saver
  - added websocket error logging hook

## Validation
- Syntax checks passed:
  - `node --check ops/whatsapp_govorun/bridge/src/common.mjs`
  - `node --check ops/whatsapp_govorun/bridge/src/auth.mjs`
  - `node --check ops/whatsapp_govorun/bridge/src/index.mjs`

## Notes
- This change improves auth/session resilience but does not guarantee bypass of WA-side temporary lockouts (`401` post-login handshake).
- No secrets/auth artifacts were committed.
