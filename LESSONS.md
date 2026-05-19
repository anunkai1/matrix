# Lessons Log

Purpose: capture the highest-value recurring mistake patterns and prevention rules after user corrections.

Use this file for active operational lessons only:
- keep entries short
- keep only lessons that still prevent realistic repeat failures
- move older, narrower, or less frequently used lessons into `LESSONS_ARCHIVE.md`

## Entry Template (Minimal Schema)

Use one section per lesson:

### YYYY-MM-DDTHH:MM:SS+10:00 - Short Lesson Title
- Mistake pattern: what went wrong
- Prevention rule: the concrete rule to avoid repeat
- Where/when applied: exact workflow step, file area, or decision point where rule must be used

## Active Lessons

### 2026-05-19T16:30:00+10:00 - Verify And Use Outbound Voice Replies When Explicitly Requested
- Mistake pattern: The owner explicitly asked for a voice reply, but I answered in plain text because I treated the turn like a normal text response instead of verifying and using the outbound Telegram voice-note path.
- Prevention rule: When the owner explicitly asks for "reply in voice", "send as voice", or similar, verify outbound voice-note delivery support in the active runtime first and use that path when it exists instead of defaulting to text.
- Where/when applied: Any Architect Telegram turn involving requested voice-format replies, especially before sending the final response for bridge-originated turns.

### 2026-05-19T14:04:30+10:00 - Make Architect Sandbox Policy Explicit In Runtime Config
- Mistake pattern: Architect's unrestricted Codex execution policy existed as tribal knowledge and partially duplicated launcher flags, but not as one explicit runtime config value.
- Prevention rule: For Architect runtime capabilities that must never drift, encode them as explicit runtime config with startup logging and targeted tests, then make every execution path consume that single source of truth.
- Where/when applied: Any future changes to Architect Codex runtime config, executor paths, or operator docs.

### 2026-05-12T14:53:59+10:00 - Never Double-Send Telegram Replies For Bridge-Originated Turns
- Mistake pattern: I manually sent Telegram replies for turns that the bridge was already going to answer, producing duplicate bot messages.
- Prevention rule: For bridge-originated Telegram turns, use the bridge's normal final response as the default outbound path and only send a separate Telegram message when the user explicitly asks for an additional out-of-band delivery.
- Where/when applied: Any Architect turn whose prompt includes `Current Telegram Context`.

### 2026-05-05T09:30:00+10:00 - Engine-Native Sessions Make SQLite Memory Redundant
- Mistake pattern: A separate SQLite memory layer duplicated conversation continuity that Pi and Codex already preserved in their own session files.
- Prevention rule: Before adding a new memory, state, or caching layer, verify whether the active engine already provides equivalent or better persistence.
- Where/when applied: Any proposed memory or continuity change for the Telegram bridge.

### 2026-05-05T01:00:00+10:00 - Never Overwrite Systemd EnvironmentFile With Single-Line Edits
- Mistake pattern: A programmatic env-file edit overwrote the whole service config with a single line and caused a crash loop.
- Prevention rule: For `EnvironmentFile` edits, use append for additive changes; otherwise back up first, make a line-targeted edit, then verify line count and critical keys afterward.
- Where/when applied: Any programmatic edit to `/etc/default/*` env files or other systemd `EnvironmentFile` paths.

### 2026-05-04T11:30:00+10:00 - Update Operator Docs In The Same Rollout As Runtime-Behavior Changes
- Mistake pattern: Live behavior changed while operator-facing docs such as `SERVER3_SUMMARY.md` and bridge docs stayed stale.
- Prevention rule: When changing runtime behavior, update the affected operator docs in the same rollout.
- Where/when applied: Any change that alters live bridge behavior, runtime behavior, memory behavior, or documented limits.

### 2026-04-03T14:02:00+10:00 - Verify Telegram Attachment Capability Before Saying It Is Unavailable
- Mistake pattern: I claimed Telegram attachment delivery was unavailable without checking the live transport/runtime path that already supported it.
- Prevention rule: When a user asks for Telegram image or file delivery, check the live bridge transport/runtime state first and attempt the supported outbound path before claiming the capability is unavailable.
- Where/when applied: Any Architect request involving Telegram delivery of images, files, or other media.

### 2026-03-03T19:18:12+10:00 - Clarify File Delivery Target Before Sending
- Mistake pattern: I assumed a file-delivery destination instead of confirming whether the owner wanted in-chat content or a Telegram attachment.
- Prevention rule: When a request mentions sending or sharing a file and the destination is ambiguous, ask one explicit routing question first.
- Where/when applied: Before executing any file-delivery request in chat operations or Telegram bridge actions.

### 2026-02-23T07:24:07+10:00 - One-Shot Timer Verification
- Mistake pattern: I checked active timers and repo notes but missed unit journal history, so I gave the wrong answer about whether a scheduled action existed.
- Prevention rule: For schedule verification, check both current unit state and historical evidence in `systemctl` and `journalctl`.
- Where/when applied: Any incident or ops check where the user asks whether a timed action was planned or executed.

## Archive

Older or narrower lessons live in [LESSONS_ARCHIVE.md](/home/architect/matrix/LESSONS_ARCHIVE.md).
