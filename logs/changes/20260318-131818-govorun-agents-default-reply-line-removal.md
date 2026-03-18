# 2026-03-18 13:18:18 AEST - Govorun AGENTS default reply-length line removal

## Request
- Remove this line from Govorun's live `AGENTS.md`:
  - `Keep replies short by default: usually 1-5 short sentences unless the user clearly asks for more detail.`

## Current State Inspected
- Verified the live policy file at `/home/govorun/govorunbot/AGENTS.md` contained the requested line under `Primary Mode`.
- Verified `/home/govorun/govorunbot` is not a git checkout, so repo audit was recorded here in `matrix`.

## Change Applied
- Removed only the explicit default reply-length line from `/home/govorun/govorunbot/AGENTS.md`.
- Left all other Govorun policy content unchanged.

## Verification
- Confirmed the line no longer exists in `/home/govorun/govorunbot/AGENTS.md`.
- Captured a minimal unified diff against the pre-change copy to verify the edit scope was one-line removal.

## Notes
- Govorun policy watch is configured on `/home/govorun/govorunbot/AGENTS.md`, so the runtime can observe this policy-file change without any manual content rewrite elsewhere.
