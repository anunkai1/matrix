# Server3 Change Record - Voice Alias Default for Claude Code

Timestamp: 2026-02-28T15:13:42+10:00 (Australia/Brisbane)
Type: repo-only voice alias reliability update

## Objective
Improve voice transcription command reliability by adding a default alias correction for the common misspelling `clode code` to `claude code`.

## Files Updated
- `src/telegram_bridge/main.py`
- `tests/telegram_bridge/test_bridge_core.py`
- `infra/env/telegram-architect-bridge.env.example`
- `infra/env/telegram-tank-bridge.env.example`
- `docs/telegram-architect-bridge.md`
- `SERVER3_SUMMARY.md`
- `SERVER3_ARCHIVE.md`

## Changes Applied
1. Added new built-in default alias pair:
- `clode code => claude code`

2. Added regression coverage:
- New unit test asserts the default alias list includes the Claude spelling fix.

3. Synced operator examples:
- Updated Architect/Tank env example lines for `TELEGRAM_VOICE_ALIAS_REPLACEMENTS`.
- Updated bridge runbook alias defaults text and sample env block.

4. Updated rolling summary/archive:
- Added this change set to summary.
- Migrated two oldest summary entries to archive to keep rolling bounds.

## Validation
- `python3 -m unittest tests/telegram_bridge/test_bridge_core.py -v`
