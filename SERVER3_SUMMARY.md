# Server3 Summary

Last updated: 2026-02-28 (AEST, +10:00)

## Current Snapshot
- Primary active component: `telegram-architect-bridge.service`
- Runtime pattern: Telegram long polling + local `codex exec`
- Major enabled capabilities: text/photo/voice/document handling, per-chat memory persistence, optional persistent workers, optional canonical session model, safe queued `/restart`
- On-demand TV desktop capability: `server3-tv-start` / `server3-tv-stop` with Brave opened in maximized mode
- Repo workflow: direct-to-`main` with mandatory commit/push proof for non-exempt changes

## Recent Change Sets (Rolling)
- 2026-02-28: added controlled voice-alias self-learning with explicit approval workflow (`/voice-alias list|approve|reject|add`), using repeated low-confidence confirmations to suggest (not auto-apply) new corrections.
- 2026-02-28: saved NanoClaw WhatsApp Server3 rollout handoff plan at `docs/handoffs/nanoclaw-whatsapp-server3-rollout-plan.md` for future resume.
- 2026-02-28: applied voice-accuracy env keys live to `/etc/default/telegram-architect-bridge` (model `small`, language/decode tuning, low-confidence gate), restarted `telegram-architect-bridge.service`, and synced the redacted env mirror.
- 2026-02-28: improved voice transcription accuracy and safety by adding decode tuning defaults (`small`, `en`, `beam_size=5`, `best_of=5`, `temperature=0.0`), transcript alias correction, and low-confidence confirmation gating before execution; updated env/docs/test coverage accordingly.
- 2026-02-28: expanded Tank required prefixes to `@tankhas_bot,tank,hey tank,t-a-n-k`, synced live env mirror, and restarted `telegram-tank-bridge.service` to apply.
- 2026-02-28: fixed required-prefix handling for voice-only requests by enforcing prefix after transcription (transcript gate), added regression tests, and restarted `telegram-tank-bridge.service` to load the updated handler.
- 2026-02-28: completed voice rollout traceability by syncing missing live voice env mirror keys (idle-timeout/socket/log path) and verifying live Telegram voice requests after restart with warm transcriber process/socket active.
- 2026-02-28: verified Tank memory parity with Architect; ran Tank summary regeneration (0 summary rows present to rewrite) and confirmed canonical mode rows are `all_context`.
- 2026-02-28: upgraded voice transcription runtime with a warm persistent service (`voice_transcribe_service.py`) that loads on first voice request, reuses the model, auto-unloads after idle timeout (default 1 hour), uses GPU-first with CPU fallback, and applies fixed ffmpeg preprocessing when available.
- 2026-02-28: improved high-level policy clarity in `ARCHITECT_INSTRUCTION.md` (added `LESSONS.md` to session-start checklist, referenced canonical Git section to avoid duplicate workflow drift, relaxed paused-state next-action wording to accept explicit approval with a recommended phrase, and updated sudo-boundary wording to present tense).
- 2026-02-28: upgraded chat summarization to structured sections (objective/decisions/state/open items/preferences/risks), added summary-regeneration helper, and regenerated all 6 existing live summaries in `/home/architect/.local/state/telegram-architect-bridge/memory.sqlite3`.
- 2026-02-28: renamed memory mode label from `full` to `all_context` across runtime/help/docs, while keeping `full` as a backward-compatible alias.
- 2026-02-28: removed `docs/instructions/lessons.md` redirect stub; `LESSONS.md` is now the only active lessons path.
- 2026-02-28: cleaned doc inconsistencies by removing obsolete helper-bot instructions from bridge docs, aligning voucher handoff summary/archive wording with rolling policy, and removing contradictory lessons-path history line.
- 2026-02-28: moved lessons to root-level `LESSONS.md` (with `docs/instructions/lessons.md` redirect stub) so it sits with main repo docs.

## Archive Pointer
- `SERVER3_ARCHIVE.md` is the canonical long-term detailed history.
- Older detailed entries were migrated from summary to archive on 2026-02-28 to keep this summary bounded.
- For per-change rollout evidence, use `logs/changes/*.md`.
