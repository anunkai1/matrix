# WhatsApp + Codex Rollout Plan (Server3)

Status: blocked on WhatsApp auth handshake (`logging in...` -> `401`), cooldown pending
Owner: anunakii
Last updated: 2026-02-28 18:24 AEST

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
- Node.js: `v22.22.0` (upgraded and validated)

## Execution progress (2026-02-28)
- Completed:
  - Dedicated runtime user created: `wa-govorun`
  - Isolated runtime root prepared: `/home/wa-govorun/whatsapp-govorun`
  - Bridge app deployed with runtime deps installed
  - User-level service installed/enabled: `whatsapp-govorun-bridge.service`
  - Codex runtime auth synced for `wa-govorun` and verified (`codex exec` works)
  - Backup flow validated (`ops/whatsapp_govorun/backup_state.sh`)
  - Auth/session hardening pass applied (queued creds saves + one-time `515` reconnect + delayed auth success exit)
- In progress:
  - WhatsApp auth/link recovery after repeated rejection
- Pending:
  - Post-auth live DM/group trigger tests
  - Final service start and reboot persistence check

## Auth incident summary (latest)
- Verified facts:
  - Phone number used in link flow is correct: `61488817223`.
  - Bridge and auth runtimes can connect to WA edge, but final auth fails.
  - Repeated runtime pattern during link attempts:
    - `logging in...`
    - connection closes with `statusCode: 401`
  - QR and pairing-code flows were both attempted multiple times.
- Operational state at pause:
  - `whatsapp-govorun-bridge.service` is intentionally stopped.
  - A 24-hour reminder timer was scheduled on Server3:
    - `remind-wa-retry-20260228-181307.timer`
    - due: `2026-03-01 18:13:07 AEST`
- Working assumption:
  - Most likely WA-side temporary risk/abuse lock from repeated attempts, not a local number-format bug.

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

### Phase 4B: Recovery runbook for next attempt window (detailed)
Use this exact sequence on the next retry window (recommended after at least 24 hours of no attempts).

1. Pre-check on phone:
   - Update WhatsApp app to latest version.
   - Turn off phone VPN/proxy.
   - In `Linked Devices`, remove stale/pending/unknown sessions if present.
2. Pre-check on Server3:
   - Keep service stopped before auth:
     - `sudo -iu wa-govorun systemctl --user stop whatsapp-govorun-bridge.service`
   - Keep auth attempts single-threaded (one at a time only).
   - Recommended: temporarily disconnect VPN during the single link attempt:
     - `nordvpn disconnect`
3. Start one clean auth attempt:
   - Remove only auth creds, keep backups:
     - `mv /home/wa-govorun/whatsapp-govorun/state/auth/creds.json /home/wa-govorun/whatsapp-govorun/state/auth.bak-<timestamp>-creds.json` (if file exists)
   - Run:
     - `cd /home/wa-govorun/whatsapp-govorun/app`
     - `WA_PAIRING_PHONE=61488817223 WA_PAIRING_CODE= npm run auth`
4. Execute exactly one link attempt:
   - Prefer QR (other device screen) for the first attempt.
   - If QR is not practical, use one fresh pairing code only.
5. Decision gate:
   - If auth succeeds (`creds.json` shows `registered=true`):
     - Start bridge service:
       - `sudo -iu wa-govorun systemctl --user start whatsapp-govorun-bridge.service`
     - Run live tests (DM, group with trigger, group without trigger).
   - If auth fails with same `401` pattern:
     - Stop immediately (no rapid retries).
     - Record logs and pivot to official WhatsApp Cloud API fallback plan.
6. Post-attempt:
   - Re-enable VPN if desired:
     - `nordvpn connect`
   - Update `logs/changes/*`, `SERVER3_SUMMARY.md`, and this handoff file.

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

## Copy/Paste Prompt For Tomorrow Restart
Use this prompt directly with Codex when restarting this task:

```text
Resume WhatsApp Govorun auth recovery on Server3 from docs/handoffs/whatsapp-server3-rollout-plan.md.

Requirements:
- Read ARCHITECT_INSTRUCTION.md, SERVER3_SUMMARY.md, LESSONS.md first.
- Do not run parallel auth attempts.
- Keep whatsapp-govorun-bridge.service stopped until auth success is verified.
- Use a single clean auth attempt only (prefer QR first, then one pairing-code fallback if needed).
- During the single attempt, keep VPN off on phone and server.
- If same pattern repeats (logging in -> 401), stop retries and prepare WhatsApp Cloud API fallback plan instead of spamming new codes.

Execution steps:
1) Verify current auth/service state.
2) Backup and clear only auth creds file.
3) Start auth and guide one link attempt.
4) Verify registered=true in creds.json.
5) If success, start service and run DM/group trigger tests.
6) Update docs/handoffs, logs/changes, and SERVER3_SUMMARY; commit + push with proof.

Output format:
- Keep updates short and concrete.
- Always show exact commands run and key log lines for go/no-go decisions.
```

## Notes
- This file is a deployment plan only; no rollout is completed yet.
