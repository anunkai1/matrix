# Server3 Summary

Last updated: 2026-04-02 (AEST, +10:00)

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
- Core capabilities: text/photo/voice/document handling, per-chat memory persistence, optional persistent workers, optional canonical session model, safe queued `/restart`
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
- 2026-04-02: updated `docs/projects/foodle.html` so the Carb-light accent uses purple instead of orange by changing the shared `--carbs` theme token, which also updates the carb badge and combined-calendar carb band consistently.
- 2026-04-02: fixed `docs/projects/foodle.html` persistence so `foodle-v1` legacy storage can no longer overwrite newer `foodle-v2` browser data when the migration marker is missing; the loader now normalizes current data, merges legacy rows into existing saved rows instead of replacing them, and then persists the merged result once so sugar/carbs/dairy progress does not disappear on reload while older fasting entries remain.
- 2026-04-02: fixed the GitHub `telegram-bridge-ci` runner path so the final smoke step now uses the same QA virtualenv interpreter as the rest of `ops/dev/run_python_checks.sh` instead of falling back to the runner’s bare `python3`; `src/telegram_bridge/smoke_test.sh` now respects `PYTHON_BIN`, `ops/dev/run_python_checks.sh` passes the bootstrapped venv through explicitly, and the full local CI-equivalent command (`bash ops/dev/run_python_checks.sh`) now passes end to end with smoke enabled.
- 2026-04-01: removed shared-core idle-expiry resets themselves from `src/telegram_bridge/session_manager.py`, so persistent-worker contexts are no longer auto-cleared or archived after inactivity across the shared bot/CLI path; the legacy `TELEGRAM_PERSISTENT_WORKERS_IDLE_TIMEOUT_SECONDS` knob is now compatibility-only, status/log output in `src/telegram_bridge/handlers.py` and `src/telegram_bridge/main.py` now reports `idle_expiry=disabled`, the focused bridge regression in `tests/telegram_bridge/test_bridge_core.py` now asserts live context remains intact, `docs/telegram-architect-bridge.md` and `docs/telegram-bridge-debug-checklist.md` were aligned, and the live shared-core bridge services were restarted again with `ops/telegram-bridge/restart_and_verify.sh`.
- 2026-04-01: removed the user-facing idle-expiry reset notice (`Your session expired after ... Context was cleared.`) from the shared session manager in `src/telegram_bridge/session_manager.py`, so persistent-worker idle expiry still archives and clears live per-chat state silently across the shared-core bot fleet without sending a separate Telegram reset message; updated the focused bridge regression in `tests/telegram_bridge/test_bridge_core.py`, aligned `docs/telegram-architect-bridge.md`, and rolled the live shared-core services with the drain-aware helper (`telegram-architect-bridge`, `telegram-agentsmith-bridge`, `telegram-diary-bridge`, `telegram-tank-bridge`, `govorun-whatsapp-bridge`, `oracle-signal-bridge`, `telegram-mavali-eth-bridge`, `telegram-macrorayd-bridge`).
- 2026-04-01: hardened repo-wide Python QA ergonomics by adding tracked dev requirements in `requirements-dev.txt`, a reproducible local bootstrap/check flow in `ops/dev/bootstrap_python_checks.sh` and `ops/dev/run_python_checks.sh`, wiring `.github/workflows/telegram-bridge-ci.yml` to use the same shared runner, documenting in `docs/runbooks/server3-monitoring.md` and `ops/server3_monitoring/.env.example` that `SERVER3_MONITORING_BIND_IP` is host-specific and can change, and incrementally expanding enforced Ruff coverage beyond fatal-only rules for the cleaner operator-side surface (`ops/server3_runtime_status.py`, `ops/runtime_overlays/sync_server3_runtime_overlays.py`, `tests/test_server3_runtime_status.py`, `tests/test_sync_server3_runtime_overlays.py`); verified with `bash ops/dev/run_python_checks.sh --skip-smoke`.
- 2026-04-01: aligned the main markdown docs with the current shared-core behavior by updating `README.md` and `docs/telegram-architect-bridge.md` to document the default persistent-worker policy watch set (`AGENTS.md`, `ARCHITECT_INSTRUCTION.md`, `SERVER3_ARCHIVE.md`), the `TELEGRAM_POLICY_WATCH_FILES` / `TELEGRAM_POLICY_WATCH_MODE=off` overrides, the order-insensitive normalization of watched policy-file lists before fingerprinting, and the fact that `python3 ops/server3_runtime_status.py` now deduplicates repeated manifest units so each shared unit is queried from `systemctl` only once per status pass.
- 2026-04-01: tightened two shared-core quality paths after a repo-wide review by normalizing `src/telegram_bridge/session_manager.py` policy-fingerprint cache inputs so reordered or duplicated policy-file lists no longer trigger unnecessary worker cache misses/session resets, and by deduplicating repeated unit lookups in `ops/server3_runtime_status.py` so shared units are queried from `systemctl` only once per status pass; added regression coverage in `tests/telegram_bridge/test_bridge_core.py` and `tests/test_server3_runtime_status.py`, and re-verified the full Python suite with `python3 -m unittest discover -s tests -p 'test_*.py'`.
- 2026-04-01: extended the live Server3 control-plane from state-only view into operator playback/audit mode by adding durable audit logging plus incident bundle capture in `ops/server3_control_plane/serve.py`, threading those recorded actions and bundle artifacts into `ops/server3_control_plane/export_snapshot.py`, regenerating `docs/server3-control-plane-data.{json,js}`, and updating `docs/server3-control-plane-sketch.html` so the board now shows a dedicated operator playback lane, recent incident bundles, per-runtime operator history in the drawer, and a live `capture incident bundle` action on the deployed board.
- 2026-03-31: hardened and expanded the deployed Server3 control-plane LAN surface so `docs/server3-control-plane-sketch.html` now presents live LAN view mode by default, supports remote operator unlock with a host-local token prompt, keeps refresh/log/restart actions disabled until either `localhost` or a valid operator token is present, and exposes a dedicated Browser Brain lane in the runtime drawer with live connection mode, auth posture, visible TV takeover state, active target/tab inventory, retained captures, and recent browser actions sourced from the real Browser Brain service; `ops/server3_control_plane/serve.py` now exposes `/api/operator/status`, accepts `X-Server3-Operator-Token` for remote operator actions, and otherwise rejects remote refresh/log/restart calls with `403`; `ops/server3_control_plane/export_snapshot.py` now prefers privileged journal reads, summarizes recent runtime events instead of dumping raw structured log payloads, and enriches Browser Brain from `ops/browser_brain/browser_brain_ctl.py`, live TV window state, and capture inventory; `ops/server3_control_plane/ensure_operator_token.sh` now provisions `/home/architect/.config/server3-control-plane/operator_token`; regenerated `docs/server3-control-plane-data.{json,js}`, re-verified the live unit after refresh, and kept screenshots/previews local instead of routing them through Telegram.

## Current Risks/Watchouts (Max 5)
- The external USB HDD at `/srv/external/server3-arr` is now the live Arr data disk for both `downloads` and `media`; avoid unplugging it while Server3 is running, and treat any future disk replacement as a full data-plane migration rather than a casual hot-swap.
- The monitoring stack currently binds Grafana to `192.168.0.148:3000`, but that host-specific LAN IP can change; if it does, update `/etc/default/server3-monitoring` and restart `server3-monitoring.service`.
- The new Server3 backup path is local-only on the attached USB backup disk at `/srv/external/server3-backups`; if the host and that backup disk are lost together, the rebuild path is gone.
- Tank keeps `/home/tank/tankbot/src` linked to the shared repo source tree; preserve `TELEGRAM_RUNTIME_ROOT=/home/tank/tankbot` in its unit/env so runtime identity does not collapse back to the shared repo root.
- `Mavali ETH` is live on a temporary public Ethereum RPC (`https://mainnet.gateway.tenderly.co`); replace it with a dedicated authenticated provider before treating the wallet runtime as durable production infrastructure.

## Archive Pointer
- `SERVER3_ARCHIVE.md` is the canonical long-term detailed history.
- For per-change rollout evidence, use `logs/changes/*.md`.
