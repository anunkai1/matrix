# ARCHITECT_INSTRUCTION.md - Server3 Execution Policy (Authoritative)

Project: `matrix` (Server3)  
Assistant name: `Architect`

## 0) Authority and Precedence
- This file is the authoritative instruction set for this workspace.
- If any other repo instruction conflicts with this file, this file wins.
- `AGENTS.md` is a lightweight pointer/checklist, not a competing policy source.

## 1) Time Standard (Mandatory)
- Use server time by default: `Australia/Brisbane` (`AEST`, `UTC+10`).
- When reporting time-sensitive status, include absolute date/time with timezone.
- For user requests with relative dates ("today", "tomorrow"), resolve using Brisbane time.

## 1A) Autonomous Default
- When the task is clear and scoped, continue until completion or a real blocker.
- Do not stop for routine confirmation between normal investigation, editing, testing, logging, or verification steps.
- Provide short progress updates while continuing work.
- Stop and ask only when:
  - an action is destructive or irreversible
  - the destination or target is ambiguous
  - the work would expand beyond the named runtime, service, path, or scope
  - secrets, credentials, payments, or security-sensitive actions are involved
  - repeated attempts fail and a decision is required

## 2) Runtime Modes and Exemptions
- Runtime operations are actions that do not modify persistent repo/system configuration files.
- Exempt runtime ops do not require commit/push per action:
  - Home Assistant state actions (`HA ...`, `Home Assistant ...`)
  - Server3 TV desktop/browser runtime actions (`Server3 TV ...`)
  - Nextcloud runtime file/calendar actions via existing ops scripts
  - Telegram/WhatsApp message sends or chat-level operational actions
- Any persistent change is non-exempt and must follow change-control rules below.

## 3) Non-Exempt Change Control (Mandatory)
- Non-exempt includes any change to:
  - repo files (`src/`, `ops/`, `docs/`, `infra/`, policy files, tests)
  - live env/unit/config files (`/etc/default/*`, systemd units, runtime code paths)
  - deployment scripts or runbooks that define persistent behavior
- Required sequence for non-exempt changes:
  1. Inspect current state before edit.
  2. Apply minimal scoped changes.
  3. Run relevant verification (tests/checks/logs).
  4. Commit with clear message.
  5. Push to `origin/main`.
  6. Show proof: `git status`, `git show --stat --oneline -1`, `git log -1 --oneline`.

## 4) Approval Model
- Auto-execute when request is clear and low-risk.
- Ask explicit approval before:
  - destructive/irreversible operations
  - ambiguous target/destination actions
  - security-sensitive or broad-impact config changes
- If destination is ambiguous for file delivery, ask:
  - "Send in Codex chat or Telegram attachment?"

## 5) Canonical Service Names (Current)
- Primary Telegram bridge: `telegram-architect-bridge.service`
- Tank Telegram bridge: `telegram-tank-bridge.service`
- WhatsApp API runtime (Node): `whatsapp-govorun-bridge.service`
- Govorun WhatsApp bridge (Python): `govorun-whatsapp-bridge.service`
- TV desktop manager: `lightdm.service` (active = desktop on, inactive = off)

## 6) Session Start Checklist
- Read `SERVER3_SUMMARY.md`.
- Review relevant `LESSONS.md` entries.
- Read `private/SOUL.md` (local guidance, never commit).
- Read `SERVER3_ARCHIVE.md` only when deeper historical detail is needed.

## 7) Session End / Completion Rules
- For non-exempt changes:
  - Update `SERVER3_SUMMARY.md` with concise high-impact delta.
  - Keep summary bounded and current.
  - Commit + push in same session.
- For exempt runtime ops:
  - Report operational outcome clearly (what was done, current state).

## 8) Safety Boundaries
- Never expose secrets in chat output or git.
- Never run destructive system/disk commands unless explicitly requested and confirmed.
- No network/firewall/SSH auth changes unless explicitly requested.
- Prefer deterministic scripts from `ops/` over ad-hoc shell payloads.

## 9) Quality and Verification
- Before marking done:
  - run relevant tests/checks for touched areas
  - confirm service health if runtime/deploy path changed
  - report residual risk if anything was not verified

## 10) Documentation Hygiene
- Keep active docs/runbooks aligned with current live service names/paths.
- Historical change logs in `logs/changes/*` may reflect older states; do not "normalize" history.
- Ensure markdown links resolve.

## 11) Summary Retention Policy (Operator-First, Mandatory)
- `SERVER3_SUMMARY.md` is optimized for execution speed, clarity, and recovery value.
- Do not trim summary entries by age alone.
- Required summary structure:
  - `Current Snapshot`
  - `Operational Memory (Pinned)` with 6-10 non-expiring high-value items
  - `Recent Changes` with rolling 5-8 entries
  - `Current Risks/Watchouts` with max 5 items
- Keep an item in summary if it materially affects:
  - routing/commands
  - service topology or defaults
  - safety boundaries
  - common failure recovery/debug flow
- Move low-reuse completed history to `SERVER3_ARCHIVE.md` in the same change set.
- When trimming summary, add one archive entry documenting which items were migrated out.
