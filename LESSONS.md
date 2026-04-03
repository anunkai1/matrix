# Lessons Log

Purpose: capture recurring mistake patterns and prevention rules after user corrections.

## Entry Template (Minimal Schema)

Use one section per lesson:

### YYYY-MM-DDTHH:MM:SS+10:00 - Short Lesson Title
- Mistake pattern: what went wrong
- Prevention rule: the concrete rule to avoid repeat
- Where/when applied: exact workflow step, file area, or decision point where rule must be used

## Lessons

<!-- Add new lessons below this line using the template above. -->

### 2026-04-03T14:02:00+10:00 - Verify Telegram Attachment Capability Before Saying It Is Unavailable
- Mistake pattern: I told the owner I could not directly attach a generated image into Telegram from this session, even though the live Architect bridge already exposes outbound `send_photo`/`send_document` support and the current chat target could be resolved from runtime state.
- Prevention rule: When a user asks for Telegram image/file delivery, check the bridge transport/runtime state first, resolve the active chat/thread, and attempt the supported Telegram attachment path before claiming the capability is unavailable.
- Where/when applied: Any Architect request involving Telegram delivery of generated images, files, or other media from the Server3 workspace.

### 2026-03-03T19:18:12+10:00 - Clarify File Delivery Target Before Sending
- Mistake pattern: I assumed "send file here" meant Codex chat delivery and did not immediately confirm whether the owner wanted Telegram attachment delivery.
- Prevention rule: When a request mentions sending/sharing a file and destination is ambiguous, ask one explicit routing question first: "Codex chat link/content or Telegram document attachment?"
- Where/when applied: Before executing any file-delivery request in chat operations and Telegram bridge actions.

### 2026-03-02T17:46:39+10:00 - Approval-Turn Protocol: Scope, Pause, Then Execute
- Mistake pattern: I repeated approval-turn failures by either pausing without clear scope/approval phrasing, sending an empty response, or not executing immediately after approval.
- Prevention rule: At approval gates, always output `Status`, `Approval for` (objective + exact scope/files), `Next action` with exact approval phrase, and `No commands will run`; once approved, execute immediately with visible progress until done or blocked.
- Where/when applied: Any approval boundary turn for non-exempt repo changes.

### 2026-02-28T11:41:46+10:00 - Regenerate Existing Data After Summary-Format Changes
- Mistake pattern: Improving summarization logic alone leaves legacy summary rows in old/noisy format, so runtime behavior remains mixed and confusing.
- Prevention rule: When summary format changes materially, provide and run a controlled regeneration path for existing `chat_summaries` rows in the same rollout.
- Where/when applied: Memory-engine summarization upgrades and post-deploy validation against live SQLite memory state.

### 2026-02-28T11:04:38+10:00 - Prefer User-Clear Naming Over Internal Terms
- Mistake pattern: I used the memory mode label `full`, which users can reasonably read as capacity-full instead of context-scope-full.
- Prevention rule: For user-facing command labels, choose plain-language names first (for example `all_context`), keep old labels only as compatibility aliases, and update help/docs in the same change.
- Where/when applied: Any command/config naming surfaced in Telegram help, CLI help, and docs before rollout.

### 2026-02-28T09:25:38+10:00 - Respect Owner-Accepted Risk Decisions in Future Plans
- Mistake pattern: I kept re-proposing fixes for risks the owner had explicitly accepted as-designed (notably H5, later H6/H7/H9).
- Prevention rule: When owner marks an item as accepted risk/as-designed, record it in repo context and treat it as deferred by default; do not propose or implement unless owner explicitly asks to revisit.
- Where/when applied: Audit follow-up planning and priority lists before drafting any new AI Prompt for Action.

### 2026-02-23T07:24:07+10:00 - One-Shot Timer Verification
- Mistake pattern: I initially reported no scheduled action existed because I checked active timers/repo notes but not unit journal history.
- Prevention rule: For any schedule verification, check both current units and historical evidence (`systemctl status <unit>` and `journalctl -u <timer> -u <service>` in the target time window).
- Where/when applied: Incident/ops checks when user asks whether a timed HA action was planned or executed.

### 2026-02-27T08:08:01+10:00 - HA Ops Reliability Baseline
- Mistake pattern: HA requests failed or misrouted because of unstable env wiring, ad-hoc transient shell payloads, and ambiguous free-form routing.
- Prevention rule: Use explicit `HA` / `Home Assistant` routing, keep HA ops on stable env paths, run API preflight before scheduling, use dedicated versioned scripts (not inline `systemd-run` shell payloads), and for urgent safe requests apply direct action first then refine.
- Where/when applied: Every HA request path, including Telegram routing and scheduled climate/mode execution.

### 2026-02-27T12:03:38+10:00 - Prefix Gating Robustness and Recovery
- Mistake pattern: Prefix parsing ignored valid mobile Unicode whitespace, and I kept tightening parser logic while users remained blocked.
- Prevention rule: Accept Unicode whitespace in prefix parsing with regression tests, and if production flow is blocked by `prefix_required`, apply immediate fallback (`TELEGRAM_REQUIRED_PREFIXES=`) to restore service first, then refine parser logic.
- Where/when applied: Telegram routing/prefix handling in `src/telegram_bridge/handlers.py` and incident response for ignored allowlisted messages.

### 2026-02-27T13:46:59+10:00 - Bot Scope and Identity Must Be Decided Together
- Mistake pattern: I assumed narrow HA-only scope without confirmation and also reused Architect workspace context for a separate bot identity.
- Prevention rule: Before rollout, confirm capability scope (general assistant vs single-domain ops), then isolate identity fully when required (runtime user + dedicated workspace root with own `AGENTS.md`/instructions and systemd working directory).
- Where/when applied: Initial design and deployment setup for new Telegram bot/services on Server3.
