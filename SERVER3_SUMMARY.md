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
- Core capabilities: text/photo/voice/document handling, per-chat memory persistence, optional persistent workers, optional Architect-side worker-scout orchestration, optional canonical session model, safe queued `/restart`
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
- 2026-03-27: added deterministic Architect planner preflight tooling (`python3 ops/telegram-bridge/planner_preflight.py`), tightened worker-lane keyword matching to avoid accidental substring-triggered docs/verification lanes, added machine-readable planner reason codes and candidate/selected-role logging, and hardened the drain-aware restart helper so it persists one durable pass/fail/timeout status marker per unit under `/run/restart-and-verify/restart_and_verify.<unit>.status.json` and hands off to a transient `systemd-run` unit when it is asked to restart its own caller service, avoiding cgroup self-termination during post-restart verification.
- 2026-03-27: promoted Architect spawned workers from read-only scouts to full-rights subordinate Architect executors, so worker lanes now inherit the same Codex approval/sandbox posture as the main executor while the main agent still owns final integration and the user-facing answer.
- 2026-03-27: added shared-core orchestrator refinement hooks: explicit planner prompt/schema versioning, config-driven disabled worker-role filtering (`TELEGRAM_AGENT_ORCHESTRATOR_DISABLED_ROLES`) for capability-aware routing, and `python3 ops/telegram-bridge/orchestrator_health_report.py` to summarize recent planner metrics plus the latest restart-marker status in one operator-facing self-check.
- 2026-03-27: tuned Architect orchestration policy so the worker split stays conservative in code as well as prompt guidance: default no split, normal split size `2`, hard max `3`, and the optional third lane is only admitted when runtime and code are already both present and an explicitly separate docs/verification lane is also signaled; clamped the runtime config accordingly and documented the behavior.
- 2026-03-27: fixed the Architect split-planner JSON schema to remove the unsupported `uniqueItems` response-format keyword, kept role dedupe in local parsing, added regression coverage, and verified the live restart completed with worker-scout orchestration still active on the fresh runtime.
- 2026-03-27: hardened the shared Telegram bridge restart helper to wait for persisted in-flight work to clear before service restart, using canonical session state when enabled, and fixed the Architect split-planner worker helper so temporary planner runs no longer fail on closed-stdin subprocess handling.
- 2026-03-27: added a feature-gated Architect task orchestrator to the shared Telegram bridge core, allowing Architect to detect when a request cleanly splits into multiple worker roles, spawn bounded Codex worker lanes in parallel for runtime/docs/code/verification reconnaissance, fold those findings into one final Architect prompt, and keep a single final writer path; enabled the feature only for Architect with a conservative live worker cap.
- 2026-03-26: refreshed the canonical shared Codex auth from the current `architect` CLI login and relinked `architect`, `govorun`, `macrorayd`, `oracle`, `agentsmith`, `tank`, and `trinity` back to `/etc/server3-codex/auth.json`, so future Architect-side Codex logins propagate automatically to the trusted runtime users; restarted `govorun-whatsapp-bridge.service` and verified a live Govorun-side `codex exec` succeeds under the same shared account id.
- 2026-03-24: added the first deterministic Diary save pipeline to the shared Telegram bridge core, with Diary-mode quiet-window batching, FIFO queueing of closed diary batches, per-day structured state under `/home/diary/.local/share/diary`, generated daily `.docx` exports, and Nextcloud upload/verification support for `/Diary/YYYY/MM/`.
- 2026-03-24: rolled out the live `Diary` Telegram runtime on Server3 by adding the isolated shared-core overlay/runtime inventory wiring, creating user `diary` at UID/GID `1013`, installing the owner-DM allowlisted env at `/etc/default/telegram-diary-bridge`, wiring shared Codex auth and repo-backed runtime docs under `/home/diary/diarybot`, fixing the initial readonly-state-path startup failure with `TELEGRAM_BRIDGE_STATE_DIR=/home/diary/.local/state/telegram-diary-bridge`, then moving voice transcription onto a Diary-local whisper runtime under `/home/diary/.local/share/telegram-voice/venv` with the medium-class English model `medium.en`, and verifying both `telegram-diary-bridge.service` and an outbound Bot API smoke to chat `211761499`.

## Current Risks/Watchouts (Max 5)
- The external USB HDD at `/srv/external/server3-arr` is now the live Arr data disk for both `downloads` and `media`; avoid unplugging it while Server3 is running, and treat any future disk replacement as a full data-plane migration rather than a casual hot-swap.
- The monitoring stack binds Grafana specifically to `192.168.0.148:3000`; if Server3's LAN IP changes, update `/etc/default/server3-monitoring` and restart `server3-monitoring.service`.
- The new Server3 backup path is local-only on the attached USB backup disk at `/srv/external/server3-backups`; if the host and that backup disk are lost together, the rebuild path is gone.
- Tank keeps `/home/tank/tankbot/src` linked to the shared repo source tree; preserve `TELEGRAM_RUNTIME_ROOT=/home/tank/tankbot` in its unit/env so runtime identity does not collapse back to the shared repo root.
- `Mavali ETH` is live on a temporary public Ethereum RPC (`https://mainnet.gateway.tenderly.co`); replace it with a dedicated authenticated provider before treating the wallet runtime as durable production infrastructure.

## Archive Pointer
- `SERVER3_ARCHIVE.md` is the canonical long-term detailed history.
- For per-change rollout evidence, use `logs/changes/*.md`.
