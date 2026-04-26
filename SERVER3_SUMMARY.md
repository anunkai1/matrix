# Server3 Summary

Last updated: 2026-04-26 (AEST, +10:00)

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
- Server4 Beast (`192.168.0.124`) now hosts Ollama model `gemma4:26b`; Server3 Telegram bridge chats can select `gemma` directly through Ollama or `pi` through Server4's Pi coding agent using SSH alias `server4-beast`; default engine remains `codex`.
- Core capabilities: text/photo/voice/document handling, per-chat memory persistence, optional persistent workers, optional canonical session model, safe queued `/restart`
- Browser Brain live mode is now `existing_session` on local CDP port `9223`; the visible `tv` Brave helper is the intended on-screen login path for sites like `x.com`, while the Browser Brain API now keeps snapshot refs locator-friendly with ARIA snapshots and supports guarded hover/select/dialog/console/network actions.
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
- Server2 access is a general-purpose Server2 operations path, not a SignalTube-only path: mention `server2` or `staker2` to target the LAN-connected Server2 host over SSH; SignalTube is only one current automation using that route.
- Runtime policy/doc drift should now be checked with `bash /home/architect/matrix/ops/runtime_personas/check_runtime_repo_links.sh` before assuming a live root has diverged from Git.
- Architect memory now uses `shared:architect:main` as a shared archive identity while active Telegram chats write to per-chat live session keys under that namespace; live keys are merged back into the archive only on idle expiry, and CLI can still point directly at the shared archive.
- Local media services now use one canonical internal namespace: `/data/downloads` and `/data/media/...`; avoid reintroducing alternate path aliases like `/downloads`, `/tv`, `/movies`, or `/media`.
- Server3 state resilience now uses a monthly quiesced backup path (`server3-state-backup.service` / `server3-state-backup.timer`) that snapshots rebuild-critical host/app/runtime state to `/srv/external/server3-backups/state`; the Arr media payload stays on the external data disk and is intentionally excluded.
- Server time standard for operations is Brisbane (`Australia/Brisbane`, AEST/UTC+10).
- Server4 engine integration keeps Server3 as the bot/control-plane host: use `/engine gemma`, `/engine pi`, `/engine codex`, `/engine reset`, and `/engine status` per chat/topic. Gemma is a direct text-only Ollama path; Pi is an SSH-backed non-interactive `pi -p` path on Server4; both report live health details in `/engine status`.

## Recent Changes (Rolling Max 8)
- 2026-04-26: added a selectable Server4 Pi engine path to the shared Telegram bridge. The new `pi` engine runs Server4's `/usr/local/bin/pi` over SSH alias `server4-beast` with configurable `PI_PROVIDER`, `PI_MODEL`, `PI_REMOTE_CWD`, `PI_TOOLS_MODE`, and timeout settings; `/engine status` now reports Pi health/version/model availability. Verified focused bridge tests and a live adapter call returning `pi bridge ok`.
- 2026-04-26: replaced `ARCHITECT_INSTRUCTION.md` with a Sentinel-style runtime policy adapted for Architect. The new policy keeps Architect identity, `SERVER3_SUMMARY.md`, Brisbane time, Telegram attachment ambiguity handling, live capability verification, and `telegram-architect-bridge.service` scope while removing the older heavier change-control/summary-retention wording.
- 2026-04-26: rolled back the experimental Gemma read-only/web agent harness while keeping `/engine status` health detail and the core selectable Server4 Gemma engine. Removed the read-only tools, file/list fallbacks, web search/fetch tools, bare-domain/news fallbacks, and Tank live web research enablement; Tank remains a Gemma-default text bot with selectable `codex,gemma`.
- 2026-04-26: expanded shared-core `/engine status` for Gemma-selected chats. When the effective engine is `gemma`, status now performs a short live Ollama tags check through the configured Gemma transport and reports Gemma health, response time, model availability, and current check error. Verified with 260 Telegram bridge tests, live Server4 health check, and shared-runtime restarts for Architect, Tank, AgentSmith, Diary, Macrorayd, Mavali ETH, Govorun bridge, and Oracle bridge; a direct `tank` user status render reported `Gemma health: ok`, `Gemma model available: yes`, and no check error at `2026-04-26 10:31 AEST`.
- 2026-04-26: made Tank the first default Gemma test runtime. Live `/etc/default/telegram-tank-bridge` now sets `TELEGRAM_ENGINE_PLUGIN=gemma`, `TELEGRAM_SELECTABLE_ENGINE_PLUGINS=codex,gemma`, and explicit Server4 Gemma env (`GEMMA_PROVIDER=ollama_ssh`, `GEMMA_MODEL=gemma4:26b`, `GEMMA_SSH_HOST=server4-beast`, `GEMMA_REQUEST_TIMEOUT_SECONDS=180`). Restart verification passed at `2026-04-26 10:21:48 AEST`; Tank logs now report `Engine plugin active=gemma`, and a direct `tank` user adapter check returned `tank default gemma ok`.
- 2026-04-26: rolled the `/engine status|codex|gemma|reset` help entry across chatbot runtimes. Shared-core Telegram runtimes now load the committed help/engine command support after service restarts; stale overlay roots for Govorun, Oracle, Mavali ETH, and Macrorayd were resynced to shared-core shims; dedicated Sentinel and Trinity handler help text was patched and syntax-checked. AgentSmith, Diary, Tank, Trinity, Macrorayd, Mavali ETH, Govorun bridge, and Oracle bridge were restarted/verified active; Sentinel restart is queued through the drain-aware transient helper to reload after the current in-flight turn drains.
- 2026-04-26: added a selectable Server4 Gemma engine path for Telegram bridge runtimes. Server4 Beast is reachable as `server4-beast` for both the current operator user and live `architect` service user, Ollama serves `gemma4:26b` locally on Server4, and the new `gemma` bridge engine calls it through SSH-backed Ollama transport without exposing Ollama on the LAN. Added per-chat `/engine status|codex|gemma|reset`, persisted chat engine overrides, config defaults for Gemma, docs/runbook coverage, and tests; live adapter verification returned `architect gemma ok`.
- 2026-04-25: disabled the SignalTube daily/overnight scheduled scan on Server3. Live `signaltube-lab-overnight.timer` is now disabled/inactive with no next trigger; manual SignalTube collection paths remain available through the signed-in web app Rescan/Ask controls and `signaltube-lab-rescan.service` / `signaltube-lab-ask.service`. Updated the SignalTube installer and runtime manifest so future `apply` runs keep the daily timer disabled unless `enable-timer` is explicitly used.
## Current Risks/Watchouts (Max 5)
- The external USB HDD at `/srv/external/server3-arr` is now the live Arr data disk for both `downloads` and `media`; avoid unplugging it while Server3 is running, and treat any future disk replacement as a full data-plane migration rather than a casual hot-swap.
- The monitoring stack currently binds Grafana to `192.168.0.148:3000`, but that host-specific LAN IP can change; if it does, update `/etc/default/server3-monitoring` and restart `server3-monitoring.service`.
- The new Server3 backup path is local-only on the attached USB backup disk at `/srv/external/server3-backups`; if the host and that backup disk are lost together, the rebuild path is gone.
- Tank keeps `/home/tank/tankbot/src` linked to the shared repo source tree; preserve `TELEGRAM_RUNTIME_ROOT=/home/tank/tankbot` in its unit/env so runtime identity does not collapse back to the shared repo root.
- `Mavali ETH` is live on a temporary public Ethereum RPC (`https://mainnet.gateway.tenderly.co`); replace it with a dedicated authenticated provider before treating the wallet runtime as durable production infrastructure.

## Archive Pointer
- `SERVER3_ARCHIVE.md` is the canonical long-term detailed history.
- For per-change rollout evidence, use `logs/changes/*.md`.
