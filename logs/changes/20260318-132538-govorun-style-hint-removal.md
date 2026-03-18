# 2026-03-18 13:25:38 AEST - Govorun WhatsApp style hint removal

## Request
- Remove Govorun's remaining default reply-length prompt hint from the live WhatsApp bridge config.

## Current State Inspected
- Verified the live file `/etc/default/govorun-whatsapp-bridge` still contained:
  - `TELEGRAM_RESPONSE_STYLE_HINT="Provide useful information first. Keep replies short by default, usually 1-3 short sentences unless the user clearly asks for more detail. ..."`
- Verified the repo example at `infra/env/govorun-whatsapp-bridge.env.example` already treats `TELEGRAM_RESPONSE_STYLE_HINT` as optional rather than required.
- Confirmed `govorun-whatsapp-bridge.service` was active before the change.

## Change Applied
- Removed only the `TELEGRAM_RESPONSE_STYLE_HINT` assignment from `/etc/default/govorun-whatsapp-bridge`.
- Left all other Govorun WhatsApp bridge env settings unchanged.

## Verification
- Compared the edited temp copy against the live file before install and confirmed the scope was a single-line removal.
- Restarted `govorun-whatsapp-bridge.service` via `ops/telegram-bridge/restart_and_verify.sh --unit govorun-whatsapp-bridge.service`.
- Verified the restart script reported `verification=pass`.
- Confirmed the live env file no longer contains `TELEGRAM_RESPONSE_STYLE_HINT`.

## Notes
- This complements the earlier removal of the explicit reply-length line from `/home/govorun/govorunbot/AGENTS.md`; both the live policy file and the active bridge env now avoid pinning Govorun to a default short-answer length.
