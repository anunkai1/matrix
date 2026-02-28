# WhatsApp + Codex Rollout Plan (Server3)

Status: planned (not started)
Owner: anunakii
Last updated: 2026-02-28 (AEST)

## Goal (Plain English)
Set up a WhatsApp-connected assistant on Server3 that routes approved messages to Codex and returns replies safely.

## How it works (simple)
1. Your WhatsApp account is linked once (QR or pairing code), similar to WhatsApp Web.
2. A local service on Server3 watches for new messages.
3. Trigger rules decide which messages should run the assistant.
4. The service sends approved prompts to Codex.
5. The service posts the assistant reply back to WhatsApp.

## Server3 preflight snapshot (current)
- Host: `server3`
- Existing bot services: `telegram-architect-bridge.service`, `telegram-tank-bridge.service`
- Docker: installed
- Node.js: currently `v18.x` (must be upgraded to `v20+` before rollout)

## Scope for this rollout
- In scope:
  - Isolated runtime user and workspace
  - Runtime/tooling install and validation
  - WhatsApp link/auth
  - Trigger and chat registration
  - systemd user service + restart policy
  - Backup and rollback baseline
- Out of scope:
  - Major feature development
  - Multi-channel expansion beyond WhatsApp

## Phase-by-phase execution plan

### Phase 0: Decisions and guardrails
- Decide identity model:
  - Option A: existing WhatsApp number (linked-device mode)
  - Option B: dedicated WhatsApp number
- Decide strict trigger format for group chats (recommended: require prefix in groups).
- Decide first rollout targets: 1 DM + 1 low-risk group only.

Exit criteria:
- Identity model, trigger policy, and first target chats confirmed.

### Phase 1: Isolated runtime on Server3
- Create dedicated runtime user (example: `wa-codex`).
- Create workspace (example: `/home/wa-codex/whatsapp-codex`).
- Ensure runtime is isolated from existing Telegram runtimes and files.

Exit criteria:
- Dedicated user and isolated workspace exist.

### Phase 2: Runtime prerequisites
- Install/upgrade Node.js to `v20+` (recommended: Node 22 LTS).
- Confirm `npm` works under runtime user.
- Confirm Docker access under runtime user.
- Confirm Codex runner access for runtime user.

Exit criteria:
- `node`, `npm`, `docker`, and codex runner are functional for runtime user.

### Phase 3: Deploy WhatsApp bridge code
- Clone the WhatsApp bridge project into the isolated workspace.
- Install dependencies.
- Build once and run a local dry start.

Exit criteria:
- Build succeeds and process can start without immediate crash.

### Phase 4: WhatsApp link/auth
- Run auth flow (QR browser, pairing code, or terminal QR as needed).
- Link from your phone.
- Confirm auth state persists and reconnect works without relinking.

Exit criteria:
- Service reconnects cleanly with saved auth state.

### Phase 5: Trigger and chat registration
- Register only approved chats/groups for initial rollout.
- Use strict trigger requirement for groups (default secure posture).
- Keep DM behavior explicit (decide prefix-required or always-on in DM).

Exit criteria:
- Unregistered chats are ignored; registered chats behave exactly as intended.

### Phase 6: Service and persistence
- Create/enable user-level systemd service for the runtime user.
- Set restart policy (`always` or equivalent).
- Verify service survives reboot and reconnects WhatsApp.

Exit criteria:
- Service starts automatically and stays healthy after reboot.

### Phase 7: Validation tests
- DM test: send prompt -> receive reply.
- Group test (with trigger): send prefixed prompt -> receive reply.
- Group test (without trigger): send non-prefixed text -> no reply.
- Recovery test: restart service -> reconnect -> continue replying.

Exit criteria:
- All tests pass with expected trigger behavior.

### Phase 8: Backup and operations baseline
- Back up critical runtime data:
  - `store/auth/`
  - `store/messages.db`
  - `groups/`
  - `data/`
  - user config under `~/.config/` for this runtime
- Document restore drill once.
- Add routine log review checklist.

Exit criteria:
- Backup + restore path is documented and tested once.

## Safety rules
- Keep this runtime isolated from existing bot users and services.
- Never commit secrets/tokens/auth artifacts into this repo.
- Roll out to one safe chat first, then expand gradually.
- Keep rollback path ready before enabling broad chat access.

## Rollback (if needed)
1. Stop and disable the WhatsApp service.
2. Unlink the linked device from WhatsApp.
3. Restore last known-good backup if required.

## Resume checklist (quick start later)
1. Re-read this file.
2. Confirm Phase 0 decisions still apply.
3. Start from the first incomplete phase.
4. Record completed phases in `logs/changes/` during execution.

## Notes
- This file is a deployment plan only; no rollout is completed yet.
