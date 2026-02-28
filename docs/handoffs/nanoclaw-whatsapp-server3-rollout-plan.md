# NanoClaw WhatsApp Rollout Plan (Server3)

Status: planned (not started)
Owner: anunakii
Created: 2026-02-28 (AEST)

## Goal (Plain English)
Set up NanoClaw on Server3 so WhatsApp messages can trigger AI replies, safely and reliably.

## How it works (simple)
1. Your WhatsApp account is linked to NanoClaw once (QR or pairing code), like WhatsApp Web.
2. NanoClaw listens for new messages.
3. Trigger words decide when NanoClaw should respond.
4. NanoClaw sends the request to the AI runner.
5. NanoClaw sends the AI reply back into WhatsApp.

## Scope for this rollout
- In scope:
  - Dedicated Linux runtime user and isolated workspace.
  - NanoClaw install and first auth.
  - Background service setup.
  - Basic safety and backup checks.
- Out of scope:
  - Major custom feature development.
  - Multi-channel expansion beyond initial WhatsApp setup.

## Phase-by-phase plan

### Phase 1: Design choices (before touching server)
- Choose identity model:
  - Option A: use your existing WhatsApp number (same account, linked device model).
  - Option B: dedicated WhatsApp number for bot-only identity.
- Choose trigger format for groups (example: `@Andy` or custom).
- Decide initial groups/DMs to enable first.

Exit criteria:
- Identity model and trigger style are confirmed.

### Phase 2: Prepare isolated runtime on Server3
- Create isolated runtime user (example `nanoclaw`).
- Create isolated workspace (example `/home/nanoclaw/nanoclaw`).
- Ensure this does not overlap `architect`/`tank` Telegram services.

Exit criteria:
- Separate user and workspace exist.

### Phase 3: Install prerequisites
- Install Node.js 20+.
- Install Docker runtime.
- Log in Claude Code as runtime user.

Exit criteria:
- `node`, `npm`, `docker`, and `claude` commands work under runtime user.

### Phase 4: Deploy NanoClaw code
- Clone NanoClaw repo in runtime workspace.
- Install dependencies.
- Build once.

Exit criteria:
- Build completes and app can start locally.

### Phase 5: First-time WhatsApp auth
- Run NanoClaw setup flow.
- Complete QR/pairing auth from phone.
- Confirm auth state saved for reconnects.

Exit criteria:
- NanoClaw connects without repeated auth prompts.

### Phase 6: Configure triggers and group registration
- Register only intended chats/groups.
- Set strict trigger behavior first.
- Test one DM and one group path.

Exit criteria:
- Messages only trigger where expected.

### Phase 7: Service + persistence
- Create systemd service for NanoClaw.
- Enable auto-start on reboot.
- Set restart on failure.

Exit criteria:
- Service is stable after restart/reboot.

### Phase 8: Validation tests
- DM test: prompt -> reply.
- Group trigger test: trigger required -> reply.
- Recovery test: service restart -> reconnect -> continue.

Exit criteria:
- All three tests pass.

### Phase 9: Backup and operations baseline
- Back up:
  - `store/auth`
  - `store/messages.db`
  - `groups/`
  - `data/`
- Add log review checklist and retention policy.

Exit criteria:
- Backup + restore process documented and tested once.

## Safety rules for rollout
- Keep NanoClaw isolated from existing Telegram bot runtime users.
- Do not store secrets in this repo.
- Test in one safe chat first before adding more groups.
- Keep rollback path ready (service stop + unlink device).

## Rollback (if needed)
1. Stop and disable NanoClaw service.
2. Unlink NanoClaw device from WhatsApp Linked Devices.
3. Restore last known-good backup if required.

## Resume checklist (quick start later)
1. Re-read this file.
2. Confirm identity model decision (same number vs dedicated number).
3. Start at Phase 2 if no server work was done.
4. Record each phase completion in `logs/changes/` as it happens.

## Notes
- This file is a plan only; it does not represent completed deployment.
