# Lessons Archive

Purpose: preserve older, narrower, or less frequently used lessons that were moved out of `LESSONS.md` so the active file stays short and operational.

## Archived Lessons

### 2026-05-03T20:00:00+10:00 - Document Design Rationale When Removing Thresholds
- Mistake pattern: We removed the SUMMARY_TRIGGER_TOKENS=12000 gate from `_maybe_summarize` because the new LLM summarizer (local gemma3:4b) doesn't need a token threshold. Another LLM later re-added both the constants and the gate, undoing the architecture change, because the removal had no explanation in the code.
- Prevention rule: When removing a historically important mechanism (threshold, gate, fallback), leave a comment block in the code explaining WHY the mechanism was designed that way and WHY the current architecture no longer needs it. Without that context, future contributors will treat the removal as a bug.
- Where/when applied: Any architectural change that removes a gate, threshold, or fallback that was previously meaningful.

### 2026-05-03T19:00:00+10:00 - Verify Data Access Patterns Against Actual Object Types
- Mistake pattern: `llm_summarizer.py` used `getattr(row, "text", "")` to read message text from database rows. sqlite3.Row objects support key access (`row["text"]`) but NOT attribute access (`row.text`). `getattr` with a default silently returned empty strings. Every summary generated since the summarizer was written ran on empty input — zero useful summaries for weeks.
- Prevention rule: When writing functions that receive data from external sources (database rows, API responses, config dicts), verify the access pattern against the actual type at the call site. sqlite3.Row is dict-style, not attribute-style. Add a type-assertion or explicit key/index access pattern when the source type is ambiguous.
- Where/when applied: Any function in `llm_summarizer.py`, `memory_engine.py`, or similar modules that accept `Sequence[sqlite3.Row]` as input.

### 2026-04-25T09:10:02+10:00 - Verify Lovelace Frontend Rendering After Dashboard Card Changes
- Mistake pattern: I reported a Home Assistant dashboard chart change as verified after checking only the saved Lovelace config and entity references, but the HA frontend still rendered a card-level `Configuration error`.
- Prevention rule: After adding or changing custom Lovelace cards, card schema, chart config, resources, or `card_mod` styling, perform a real frontend render check in HA and scan for visible configuration/card errors before reporting success.
- Where/when applied: Any Home Assistant dashboard/resource/theme work, especially HACS/custom cards such as `apexcharts-card`, `mini-graph-card`, Mushroom cards, layout-card, and card-mod.

### 2026-04-13T13:20:00+10:00 - Do Not Inject Source-Analysis Notes Into Default YouTube Summaries
- Mistake pattern: I added a default source-analysis preamble to a plain YouTube summary because of local guidance, even though the owner wanted just the summary and the shared bridge prompt path already omitted that framing.
- Prevention rule: For pasted YouTube links and similar summary requests, provide the content summary directly unless the owner explicitly asks for source vetting, bias review, or fact-checking.
- Where/when applied: Any default link-summary workflow in Architect, especially bare-link YouTube requests and Telegram summary replies.

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

### 2026-02-27T08:08:01+10:00 - HA Ops Reliability Baseline
- Mistake pattern: HA requests failed or misrouted because of unstable env wiring, ad-hoc transient shell payloads, and ambiguous free-form routing.
- Prevention rule: Use explicit `HA` / `Home Assistant` routing, keep HA ops on stable env paths, run API preflight before scheduling, use dedicated versioned scripts (not inline `systemd-run` shell payloads), and for urgent safe requests apply direct action first then refine.
- Where/when applied: Every HA request path, including Telegram routing and scheduled climate/mode execution.

### 2026-02-27T12:03:38+10:00 - Prefix Gating Robustness And Recovery
- Mistake pattern: Prefix parsing ignored valid mobile Unicode whitespace, and I kept tightening parser logic while users remained blocked.
- Prevention rule: Accept Unicode whitespace in prefix parsing with regression tests, and if production flow is blocked by `prefix_required`, apply immediate fallback (`TELEGRAM_REQUIRED_PREFIXES=`) to restore service first, then refine parser logic.
- Where/when applied: Telegram routing/prefix handling in `src/telegram_bridge/handlers.py` and incident response for ignored allowlisted messages.

### 2026-02-27T13:46:59+10:00 - Bot Scope And Identity Must Be Decided Together
- Mistake pattern: I assumed narrow HA-only scope without confirmation and also reused Architect workspace context for a separate bot identity.
- Prevention rule: Before rollout, confirm capability scope (general assistant vs single-domain ops), then isolate identity fully when required (runtime user + dedicated workspace root with own `AGENTS.md`/instructions and systemd working directory).
- Where/when applied: Initial design and deployment setup for new Telegram bot/services on Server3.
