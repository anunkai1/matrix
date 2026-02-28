# Server3 Summary

Last updated: 2026-02-28 (AEST, +10:00)

## Current Snapshot
- Primary active component: `telegram-architect-bridge.service`
- Runtime pattern: Telegram long polling + local `codex exec`
- Major enabled capabilities: text/photo/voice/document handling, per-chat memory persistence, optional persistent workers, optional canonical session model, safe queued `/restart`
- On-demand TV desktop capability: `server3-tv-start` / `server3-tv-stop` with Brave opened in maximized mode
- Repo workflow: direct-to-`main` with mandatory commit/push proof for non-exempt changes

## Recent Change Sets (Rolling)
- 2026-02-28: corrected Server3 Joplin WebDAV path to `https://mavali.top/remote.php/dav/files/admin/VladsPhoneMoto/Joplin` per owner-provided endpoint, synced successfully, and verified current remote dataset still reports empty (`0/0`, no notebooks).
- 2026-02-28: installed Joplin CLI on Server3 (`joplin 3.5.1`), configured Nextcloud sync target (`sync.target=5`) for `https://mavali.top/remote.php/dav/files/admin/Joplin`, resolved initial WebDAV bootstrap `409` by creating remote `Joplin` folder, and verified sync completion from Nextcloud.
- 2026-02-28: applied WhatsApp auth-flow hardening inspired by OpenClaw/NanoClaw patterns: queued credential saves with backup, websocket error hooks, one-time `515` reconnect during auth, and delayed success exit to allow creds flush; bridge wiring updated to use queued creds save handler.
- 2026-02-28: refreshed WhatsApp Server3 handoff with incident-backed auth blocker status (`logging in...` -> `401`), detailed next-day recovery runbook, and a copy/paste restart prompt for Codex; also captured scheduled 24h retry reminder context.
- 2026-02-28: implemented WhatsApp Govorun runtime rollout phase-1 on Server3 (`wa-govorun` user, Node 22, bridge deploy, user systemd service, ops/runbook/infra mirrors), validated codex/no-sudo/backup/service lifecycle, and fixed auth handshake by fetching latest WA web version; auth now generates QR (`/home/wa-govorun/whatsapp-govorun/state/qr-auth.html`) and awaits phone scan for final live chat tests.
- 2026-02-28: removed obsolete handoff file `docs/handoffs/voucher-automation-resume-handoff.md` per owner request.
- 2026-02-28: renamed the WhatsApp rollout handoff file from `docs/handoffs/nanoclaw-whatsapp-server3-rollout-plan.md` to `docs/handoffs/whatsapp-server3-rollout-plan.md`.
- 2026-02-28: rewrote the WhatsApp Server3 rollout handoff into a Codex-first, Server3-specific execution plan with explicit preflight gap closure (Node 20+), phased checks, and trigger/validation/rollback steps; removed legacy product/model references from the plan content.
- 2026-02-28: removed the `mansplain:` shortcut from active policy files (`ARCHITECT_INSTRUCTION.md` and local `private/SOUL.md`); no shortcut is currently configured.
- 2026-02-28: added default voice alias correction `clode code -> claude code` for transcription reliability, plus test coverage and env/docs example updates.
- 2026-02-28: wired private local `private/SOUL.md` into session-start guidance (`read if present, never commit`) and simplified shortcut policy to the single current shortcut `mansplain:`.
- 2026-02-28: aligned TV desktop target-state wording with current behavior by changing fullscreen wording to maximized and updated the TV autostart desktop-entry comment to match.
- 2026-02-28: applied voice-improvement stack on Tank live (`/etc/default/telegram-tank-bridge`): model `small`, decode tuning, low-confidence gate, and alias-learning keys; restarted `telegram-tank-bridge.service` and synced Tank env mirror/template.
- 2026-02-28: added persistent `mansplain:` shortcut rule in `ARCHITECT_INSTRUCTION.md` so that requests with this trigger get beginner-friendly, low-jargon, logical explanations.
- 2026-02-28: added controlled voice-alias self-learning with explicit approval workflow (`/voice-alias list|approve|reject|add`), using repeated low-confidence confirmations to suggest (not auto-apply) new corrections.
- 2026-02-28: saved NanoClaw WhatsApp Server3 rollout handoff plan at `docs/handoffs/nanoclaw-whatsapp-server3-rollout-plan.md` for future resume.
- 2026-02-28: applied voice-accuracy env keys live to `/etc/default/telegram-architect-bridge` (model `small`, language/decode tuning, low-confidence gate), restarted `telegram-architect-bridge.service`, and synced the redacted env mirror.
- 2026-02-28: improved voice transcription accuracy and safety by adding decode tuning defaults (`small`, `en`, `beam_size=5`, `best_of=5`, `temperature=0.0`), transcript alias correction, and low-confidence confirmation gating before execution; updated env/docs/test coverage accordingly.
- 2026-02-28: expanded Tank required prefixes to `@tankhas_bot,tank,hey tank,t-a-n-k`, synced live env mirror, and restarted `telegram-tank-bridge.service` to apply.
- 2026-02-28: fixed required-prefix handling for voice-only requests by enforcing prefix after transcription (transcript gate), added regression tests, and restarted `telegram-tank-bridge.service` to load the updated handler.

## Archive Pointer
- `SERVER3_ARCHIVE.md` is the canonical long-term detailed history.
- Older detailed entries were migrated from summary to archive on 2026-02-28 to keep this summary bounded.
- For per-change rollout evidence, use `logs/changes/*.md`.
