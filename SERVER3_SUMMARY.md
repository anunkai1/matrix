# Server3 Summary

Last updated: 2026-05-05 (AEST, +10:00)

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
- Server4 Beast (`192.168.0.124`) now hosts Ollama models `gemma4:26b` and `qwen3-coder:30b`; Server3 Telegram bridge chats can select `gemma` directly through Ollama or `pi` through local Server3 Pi using Server4 as the model backend; default engine remains `codex`.
- Core capabilities: text/photo/voice/document handling, optional persistent workers, optional canonical session model, safe queued `/restart`. Conversation continuity is handled by engine-native sessions (Pi JSONL files per chat/topic, Codex JSONL files per exec session).
- Browser Brain live mode is now `existing_session` on local CDP port `9223`; the visible `tv` Brave helper is the intended on-screen login path for sites like `x.com`, while the Browser Brain API now keeps snapshot refs locator-friendly with ARIA snapshots and supports guarded hover/select/dialog/console/network actions.
- Telegram reply-context wrappers now use English labels (`Reply Context`, `Original Message Author`, `Message User Replied To`, `Current User Message`) while downstream parsers remain backward-compatible with older Russian wrappers.
- Canonical runtime inventory now lives in `infra/server3-runtime-manifest.json`, with shared live inspection via `python3 ops/server3_runtime_status.py`
- Shared runtime core now lives in `/home/architect/matrix/src/telegram_bridge`; Tank/Govorun/Oracle run as per-runtime overlays, while Trinity now runs from its own dedicated code tree under `/home/trinity/trinitybot`.
- AgentSmith now runs as an isolated shared-core Telegram sibling runtime under `/home/agentsmith/agentsmithbot` with its own service/env/state.
- AgentSmith Pi uses local Server3 Pi in `/home/agentsmith/agentsmithbot`, Server4 Ollama through SSH tunnel port `11436`, and its own Server4 SSH key/config plus Pi model config under `/home/agentsmith/.pi/agent/models.json`.
- Sentinel now has an admin-capable HA API path for automation-definition work via `/etc/default/ha-ops-admin`, `/usr/local/bin/ha-admin-token`, and `/usr/local/bin/ha-admin-api`; the refresh token stays root-owned and access tokens are minted on demand.
- Diary now runs as an isolated shared-core Telegram sibling runtime under `/home/diary/diarybot` with its own service/env/state.
- Macrorayd now runs as an isolated shared-core Telegram sibling runtime under `/home/macrorayd/macroraydbot` with its own service/env/state.
- SRO keyword routing (`SRO ...` / `server3 runtime observer ...`) is available for stateless runtime observer queries.
- Runtime personas now live canonically in `infra/runtime_personas`, companion runtime docs now live canonically in `docs/runtime_docs`, and the live runtime roots consume those tracked files through repo-backed symlinks verified by `bash ops/runtime_personas/check_runtime_repo_links.sh`.
- Repo workflow: direct-to-`main` with mandatory commit/push proof for non-exempt changes
- Runtime observer daily Telegram summary now appends a plain-English operator line indicating whether attention is needed.
- Runtime observer daily health delivery is centralized through `staker_alerts_bot` to chat `211761499` (single destination).

## Runtime Inventory
- Canonical manifest: `infra/server3-runtime-manifest.json`
- Shared live status command: `python3 ops/server3_runtime_status.py`
- Covered runtime groups: Architect, AgentSmith, Diary, Tank, Trinity, Macrorayd, Govorun transport/bridge, Oracle transport/bridge, Mavali ETH, Sentinel, network layer, guardrail timers, Browser Brain, optional UI/SignalTube.

## Operational Memory (Pinned)
- Routing keywords:
  - `HA ...` / `Home Assistant ...` for stateless HA operation mode
  - bare YouTube links for transcript-first YouTube analysis mode with `yt-dlp` captions first and local transcription fallback
  - `Server3 TV ...` for desktop/browser control mode
  - `Nextcloud ...` for Nextcloud file/calendar operation mode
  - `SRO ...` / `server3 runtime observer ...` for stateless runtime observer queries
- Primary channel: `telegram`; WhatsApp runtime exists in parallel (`whatsapp-govorun-bridge.service` + `govorun-whatsapp-bridge.service`).
- Runtime observer is enabled on timer (`server3-runtime-observer.timer`) with Telegram daily summary mode (`RUNTIME_OBSERVER_MODE=telegram_daily_summary`) scheduled for `08:05` AEST.
- Govorun cross-channel routing contract guard is enforced by `ops/chat-routing/validate_chat_routing_contract.py` with canonical policy in `infra/contracts/server3-chat-routing.contract.env`; daily drift timer is `server3-chat-routing-contract-check.timer`.
- TV desktop/browser reliability is hardened with deterministic helpers, existing-window reuse, and autoplay fallback tooling (`wmctrl`, `xdotool`, `yt-dlp`).
- Browser Brain `x.com`/manual-login recovery path is: keep Browser Brain in `existing_session` mode, start the visible TV-side Brave helper, let the user log in manually there if needed, then attach Browser Brain over local CDP; do not try to run Browser Brain itself headed on Server3.
- Tank defaults are hardened: DM prefix bypass in private chats, isolated Joplin profile/path, reasoning effort `low`.
- Server2 access is a general-purpose Server2 operations path, not a SignalTube-only path: mention `server2` or `staker2` to target the LAN-connected Server2 host over SSH; SignalTube is only one current automation using that route.
- Runtime policy/doc drift should now be checked with `bash /home/architect/matrix/ops/runtime_personas/check_runtime_repo_links.sh` before assuming a live root has diverged from Git.
- Conversation continuity is provided by engine-native session files. Pi stores per-chat/topic JSONL in `~/.pi/agent/telegram-sessions/`; Codex stores per-exec-session JSONL in `~/.codex/sessions/`. Both replay full history to the provider API on every turn. `/reset` clears both the bridge thread_id and the Pi session files.
- Local media services now use one canonical internal namespace: `/data/downloads` and `/data/media/...`; avoid reintroducing alternate path aliases like `/downloads`, `/tv`, `/movies`, or `/media`.
- Server3 state resilience now uses a monthly quiesced backup path (`server3-state-backup.service` / `server3-state-backup.timer`) that snapshots rebuild-critical host/app/runtime state to `/srv/external/server3-backups/state`; the Arr media payload stays on the external data disk and is intentionally excluded.
- Server time standard for operations is Brisbane (`Australia/Brisbane`, AEST/UTC+10).
- Server4/API/browser engine integration keeps Server3 as the bot/control-plane host: use `/engine gemma`, `/engine pi`, `/engine codex`, `/engine chatgptweb`, `/engine reset`, and `/engine status` per chat/topic. Gemma is a direct text-only Ollama path; Pi runs locally in the Server3 runtime root while using Server4 Ollama through the tunnel; Venice remains available as a Pi provider rather than a first-class engine choice; `chatgptweb` is a brittle Browser Brain-backed lab engine; all report live health details in `/engine status` where applicable.

## Recent Changes (Rolling Max 8)
- 2026-05-05: code infrastructure overhaul. Eliminated pervasive `try/except ImportError` anti-pattern from all 54 bridge modules (-1,116 lines) by adding proper package structure with `__init__.py`, `pyproject.toml` build system, and `PYTHONPATH` in systemd units. Extracted reusable `Env` parser class (`env_parser.py`, 187 lines) replacing 11 duplicated parse functions. Split `engine_adapter.py` (1,407 lines) into 8 focused files under `engines/` subpackage. Removed vestigial memory systemd units from live system. Net source reduction: -3,087 / +492 = -2,595 lines.
- 2026-05-05: removed SQLite memory engine entirely (`memory_engine.py`, `memory_merge.py`, `memory_scope.py`, ~590 lines). Engine-native session files (Pi JSONL per chat/topic, Codex JSONL per exec session) already provide full conversation continuity, making the 10k-token SQLite memory layer redundant. Removed memory env vars from bridge config, deleted memory systemd units (9 files) and ops scripts (10 files), and cleared memory.sqlite3. `/reset` now clears thread_id + Pi session files only.
- 2026-05-03: split `state_store.py` into `state_models.py` + `session_state.py` + `request_state.py`; centralized cross-module lazy facade in `bridge_deps.py` replacing 4x duplicated `_bridge_handlers()` patterns.
- 2026-04-28: added automatic Pi session retention for scope-based Pi state. The Pi adapter now rotates per-scope JSONL files when they exceed size or age thresholds, archives them under a dedicated archive directory, and prunes old rotated archives on the same pass so short-term continuity stays available without letting session files grow without bound.
- 2026-04-28: promoted the experimental ChatGPT web bridge from CLI-only to selectable `chatgptweb` engine plumbing for Architect. It remains text-only and brittle, depends on a manually logged-in visible `chatgpt.com` Browser Brain session, and is still separate from the later Pi-backed agentic harness goal.
- 2026-04-30: removed `venice` from the user-facing selectable `/engine` list across the shared Telegram bridge env/docs while keeping Venice available as a `PI_PROVIDER=venice` backend. Help text now renders the `/engine` choices from configured selectable engines so runtime docs stay aligned with live config.
- 2026-04-26: added a selectable Pi engine path to the shared Telegram bridge. The corrected `pi` design runs the Pi binary locally inside each Server3 runtime root and uses Server4 Beast only as the Ollama model backend through an SSH tunnel; configurable knobs include `PI_RUNNER`, `PI_LOCAL_CWD`, `PI_PROVIDER`, `PI_MODEL`, `PI_TOOLS_MODE`, `PI_SESSION_MODE`, and timeout/tunnel settings. `/engine status` reports Pi health/version/model availability.
- 2026-04-26: added a selectable Server4 Gemma engine path for Telegram bridge runtimes. Server4 Beast is reachable as `server4-beast` for both the current operator user and live `architect` service user, Ollama serves `gemma4:26b` locally on Server4, and the new `gemma` bridge engine calls it through SSH-backed Ollama transport without exposing Ollama on the LAN. Added per-chat `/engine status|codex|gemma|reset`, persisted chat engine overrides, config defaults for Gemma, docs/runbook coverage, and tests.

## Current Risks/Watchouts (Max 5)
- The external USB HDD at `/srv/external/server3-arr` is now the live Arr data disk for both `downloads` and `media`; avoid unplugging it while Server3 is running, and treat any future disk replacement as a full data-plane migration rather than a casual hot-swap.
- The monitoring stack currently binds Grafana to `192.168.0.148:3000`, but that host-specific LAN IP can change; if it does, update `/etc/default/server3-monitoring` and restart `server3-monitoring.service`.
- The new Server3 backup path is local-only on the attached USB backup disk at `/srv/external/server3-backups`; if the host and that backup disk are lost together, the rebuild path is gone.
- Tank keeps `/home/tank/tankbot/src` linked to the shared repo source tree; preserve `TELEGRAM_RUNTIME_ROOT=/home/tank/tankbot` in its unit/env so runtime identity does not collapse back to the shared repo root.
- `Mavali ETH` is live on a temporary public Ethereum RPC (`https://mainnet.gateway.tenderly.co`); replace it with a dedicated authenticated provider before treating the wallet runtime as durable production infrastructure.

## Archive Pointer
- `SERVER3_ARCHIVE.md` is the canonical long-term detailed history.
- For per-change rollout evidence, use `logs/changes/*.md`.
