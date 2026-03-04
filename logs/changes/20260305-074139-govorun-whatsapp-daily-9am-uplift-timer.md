# Govorun WhatsApp daily 09:00 uplift message (live + repo mirror)

## Objective
Schedule a daily 09:00 AEST Russian good-morning message with one uplifting fact for the Путиловы group and send a 1:1 preview now.

## Changes Applied
1. Added daily sender script:
   - `ops/whatsapp_govorun/send_daily_uplift.py`
   - Sends Russian morning greeting + one rotating uplifting fact.
   - Supports destination override (`--chat-id` / `--chat-jid`) and `--test` preview wrapper.
2. Added systemd units:
   - `infra/systemd/govorun-whatsapp-daily-uplift.service`
   - `infra/systemd/govorun-whatsapp-daily-uplift.timer`
   - Timer schedule: `OnCalendar=*-*-* 09:00:00`, `Persistent=true`.
3. Added installer:
   - `ops/whatsapp_govorun/install_daily_uplift_timer.sh`
   - Modes: `apply|status|run-now|rollback`.
4. Added env templates/mirrors:
   - `infra/env/govorun-whatsapp-daily-uplift.env.example`
   - `infra/env/govorun-whatsapp-daily-uplift.server3.redacted.env`
5. Updated docs/summary:
   - `docs/runbooks/whatsapp-govorun-operations.md`
   - `SERVER3_SUMMARY.md`

## Live Apply
- Installed units to `/etc/systemd/system/` and enabled timer.
- Configured `/etc/default/govorun-whatsapp-daily-uplift`:
  - `WA_DAILY_UPLIFT_API_BASE=http://127.0.0.1:8787`
  - `WA_DAILY_UPLIFT_TZ=Australia/Brisbane`
  - `WA_DAILY_UPLIFT_GROUP_NAME=Путиловы`
  - `WA_DAILY_UPLIFT_CHAT_JID=61423665514-1534056215@g.us`
- Timer status after apply:
  - Active waiting
  - Next trigger at `09:00:00` AEST.

## 1:1 Preview Send (Requested)
- Sent now via script:
  - `python3 ops/whatsapp_govorun/send_daily_uplift.py --test --chat-id 909530421`
- Bridge response:
  - `ok=true`
  - `message_id=13`
  - `wa_message_id=3EB033F907ECCF519D1083`

## Notes
- Group target JID can be changed without code changes in `/etc/default/govorun-whatsapp-daily-uplift` (`WA_DAILY_UPLIFT_CHAT_JID`).
