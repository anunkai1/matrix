# Server3 Summary

Last updated: 2026-03-27 (AEST, +10:00)

## Purpose
- Fast restart context optimized for execution speed, clarity, and recovery value.
- Keep this file compact and operator-first; move deep history to `SERVER3_ARCHIVE.md`.

## Summary Policy (Operator-First)
- Keep only items that materially improve execution speed, correctness, or recovery.
- Structure limits:
  - `Operational Memory (Pinned)`: 6-10 items
  - `Recent Changes (Rolling Max 8)`: newest high-value deltas only
  - `Current Risks/Watchouts (Max 5)`: active operational caveats only
- Do not trim by age alone; trim by reuse and operational impact.

## Current Snapshot
- Primary active component: `telegram-architect-bridge.service`
- Runtime pattern: Telegram long polling + local `codex exec`
- Core capabilities: text/photo/voice/document handling, per-chat memory persistence, optional persistent workers, optional Architect-side worker-executor orchestration, optional canonical session model, safe queued `/restart`
- Browser Brain live mode is now `existing_session` on local CDP port `9223`; the visible `tv` Brave helper is the intended on-screen login path for sites like `x.com`.
- Telegram reply-context wrappers now use English labels (`Reply Context`, `Original Message Author`, `Message User Replied To`, `Current User Message`) while downstream parsers remain backward-compatible with older Russian wrappers.
- Canonical runtime inventory now lives in `infra/server3-runtime-manifest.json`, with shared live inspection via `python3 ops/server3_runtime_status.py`
- Shared runtime core now lives in `/home/architect/matrix/src/telegram_bridge`; Tank/Govorun/Oracle run as per-runtime overlays, while Trinity now runs from its own dedicated code tree under `/home/trinity/trinitybot`.
- AgentSmith now runs as an isolated shared-core Telegram sibling runtime under `/home/agentsmith/agentsmithbot` with its own service/env/state.
- Diary now runs as an isolated shared-core Telegram sibling runtime under `/home/diary/diarybot` with its own service/env/state.
- Runtime personas now live canonically in `infra/runtime_personas`, companion runtime docs now live canonically in `docs/runtime_docs`, and the live runtime roots consume those tracked files through repo-backed symlinks verified by `bash ops/runtime_personas/check_runtime_repo_links.sh`.
- Repo workflow: direct-to-`main` with mandatory commit/push proof for non-exempt changes
- Runtime observer daily Telegram summary now appends a plain-English operator line indicating whether attention is needed.
- Runtime observer daily health delivery is centralized through `staker_alerts_bot` to chat `211761499` (single destination).

## Runtime Inventory
- Canonical manifest: `infra/server3-runtime-manifest.json`
- Shared live status command: `python3 ops/server3_runtime_status.py`
- Covered runtime groups: Architect, AgentSmith, Diary, Tank, Trinity, Govorun transport/bridge, Oracle transport/bridge, network layer, guardrail timers, optional UI.

## Operational Memory (Pinned)
- Routing keywords:
  - `HA ...` / `Home Assistant ...` for stateless HA operation mode
  - bare YouTube links for transcript-first YouTube analysis mode with `yt-dlp` captions first and local transcription fallback
  - `Server3 TV ...` for desktop/browser control mode
  - `Nextcloud ...` for Nextcloud file/calendar operation mode
- Primary channel: `telegram`; WhatsApp runtime exists in parallel (`whatsapp-govorun-bridge.service` + `govorun-whatsapp-bridge.service`).
- Runtime observer is enabled on timer (`server3-runtime-observer.timer`) with Telegram daily summary mode (`RUNTIME_OBSERVER_MODE=telegram_daily_summary`) scheduled for `08:05` AEST.
- Govorun cross-channel routing contract guard is enforced by `ops/chat-routing/validate_chat_routing_contract.py` with canonical policy in `infra/contracts/server3-chat-routing.contract.env`; daily drift timer is `server3-chat-routing-contract-check.timer`.
- TV desktop/browser reliability is hardened with deterministic helpers, existing-window reuse, and autoplay fallback tooling (`wmctrl`, `xdotool`, `yt-dlp`).
- Browser Brain `x.com`/manual-login recovery path is: keep Browser Brain in `existing_session` mode, start the visible TV-side Brave helper, let the user log in manually there if needed, then attach Browser Brain over local CDP; do not try to run Browser Brain itself headed on Server3.
- Tank defaults are hardened: DM prefix bypass in private chats, isolated Joplin profile/path, reasoning effort `low`.
- Runtime policy/doc drift should now be checked with `bash /home/architect/matrix/ops/runtime_personas/check_runtime_repo_links.sh` before assuming a live root has diverged from Git.
- Architect memory now uses `shared:architect:main` as a shared archive identity while active Telegram chats write to per-chat live session keys under that namespace; live keys are merged back into the archive only on idle expiry, and CLI can still point directly at the shared archive.
- Local media services now use one canonical internal namespace: `/data/downloads` and `/data/media/...`; avoid reintroducing alternate path aliases like `/downloads`, `/tv`, `/movies`, or `/media`.
- Server3 state resilience now uses a monthly quiesced backup path (`server3-state-backup.service` / `server3-state-backup.timer`) that snapshots rebuild-critical host/app/runtime state to `/srv/external/server3-backups/state`; the Arr media payload stays on the external data disk and is intentionally excluded.
- Server time standard for operations is Brisbane (`Australia/Brisbane`, AEST/UTC+10).

## Recent Changes (Rolling Max 8)
- 2026-03-27: cleaned up shared-bridge scope-key compatibility after the conversational-bypass follow-up by normalizing canonical session persistence and worker/session helper boundaries to the string scope model, restoring backward-compatible defaults on bridge helper entry points, fixing non-Telegram memory conversation-key resolution from wrapped Telegram scopes, and updating the focused bridge regression suite back to green (`python3 -m unittest tests/telegram_bridge/test_bridge_core.py tests/telegram_bridge/test_runtime_config.py`).
- 2026-03-27: trimmed Architect split-planner latency for obvious explanation/status/chatty turns by extracting the actual current-user focus text from wrapped prompts, bypassing the planner before any extra `codex exec` when the turn is clearly conversational, aligning progress wording to "evaluate whether worker executors would help", and adding regression coverage so reply-context keywords do not trigger unnecessary planner runs.
- 2026-03-27: refined Architect spawned-executor orchestration so planner failures now fail closed to the single-agent path instead of spawning fallback full-rights workers, worker/planner subprocesses refresh shared Codex auth through the same pre-exec sync hook used by the main bridge path, and the old separate orchestrator worker-timeout knob was removed so both planner and workers now derive their bound from the main executor timeout; added focused regression coverage for the new fail-closed planner behavior, auth-sync hook invocation, and config simplification.
- 2026-03-27: tied shared-bridge Codex session continuity to a stable auth fingerprint so a new `codex login` account now clears persisted Codex thread resumes and memory-engine session thread IDs on the next request instead of letting sibling bots keep talking on stale old-account threads; added `src/telegram_bridge/auth_state.py`, regression coverage, and restarted the shared-core sibling bridge services (`AgentSmith`, `Diary`, `Tank`, `Govorun`, `Oracle`, `Mavali ETH`, `Macrorayd`) while Architect's self-restart remains safely queued until its in-flight work drains.
- 2026-03-27: hardened shared Codex auth propagation so sibling runtimes automatically realign to Architect's current CLI account on the next executor run even if `codex login` replaces `/home/architect/.codex/auth.json` with a standalone file again; added `ops/codex/sync_shared_auth.sh` and wired the shared `src/telegram_bridge/executor.sh` to refresh `/etc/server3-codex/auth.json` plus relink Codex-enabled runtime users before each `codex exec`.
- 2026-03-27: added deterministic Architect planner preflight tooling (`python3 ops/telegram-bridge/planner_preflight.py`), tightened worker-lane keyword matching to avoid accidental substring-triggered docs/verification lanes, added machine-readable planner reason codes and candidate/selected-role logging, and hardened the drain-aware restart helper so it persists one durable pass/fail/timeout status marker per unit under `/run/restart-and-verify/restart_and_verify.<unit>.status.json` and hands off to a transient `systemd-run` unit when it is asked to restart its own caller service, avoiding cgroup self-termination during post-restart verification.
- 2026-03-27: promoted Architect spawned workers from read-only scouts to full-rights subordinate Architect executors, so worker lanes now inherit the same Codex approval/sandbox posture as the main executor while the main agent still owns final integration and the user-facing answer; remaining operator/runtime wording is aligned to the executor model.
- 2026-03-27: added shared-core orchestrator refinement hooks: explicit planner prompt/schema versioning, config-driven disabled worker-role filtering (`TELEGRAM_AGENT_ORCHESTRATOR_DISABLED_ROLES`) for capability-aware routing, and `python3 ops/telegram-bridge/orchestrator_health_report.py` to summarize recent planner metrics plus the latest restart-marker status in one operator-facing self-check.

## Current Risks/Watchouts (Max 5)
- The external USB HDD at `/srv/external/server3-arr` is now the live Arr data disk for both `downloads` and `media`; avoid unplugging it while Server3 is running, and treat any future disk replacement as a full data-plane migration rather than a casual hot-swap.
- The monitoring stack binds Grafana specifically to `192.168.0.148:3000`; if Server3's LAN IP changes, update `/etc/default/server3-monitoring` and restart `server3-monitoring.service`.
- The new Server3 backup path is local-only on the attached USB backup disk at `/srv/external/server3-backups`; if the host and that backup disk are lost together, the rebuild path is gone.
- Tank keeps `/home/tank/tankbot/src` linked to the shared repo source tree; preserve `TELEGRAM_RUNTIME_ROOT=/home/tank/tankbot` in its unit/env so runtime identity does not collapse back to the shared repo root.
- `Mavali ETH` is live on a temporary public Ethereum RPC (`https://mainnet.gateway.tenderly.co`); replace it with a dedicated authenticated provider before treating the wallet runtime as durable production infrastructure.

## Archive Pointer
- `SERVER3_ARCHIVE.md` is the canonical long-term detailed history.
- For per-change rollout evidence, use `logs/changes/*.md`.
