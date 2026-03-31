# Server3 Summary

Last updated: 2026-03-31 (AEST, +10:00)

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
- 2026-03-31: added a standalone static `docs/projects/streakdle.html` page for simple browser-local sugar/carbs/dairy streak tracking with one-tap daily logging, seven-day visual history, longest-streak summaries, and mobile-friendly share-sheet/clipboard sharing for Wordle-style progress updates.
- 2026-03-30: hardened `ops/server3_runtime_status.py` so healthy systemd timers that report `active/running` instead of `active/waiting` no longer produce false runtime warnings; live status now clears the spurious `Mavali ETH` receipt-monitor alert and leaves only genuine deviations such as the currently active optional UI layer.
- 2026-03-30: granted the dedicated `sentinel` runtime user full passwordless sudo parity with `architect` via tracked mirror `infra/system/sudoers/sentinel`, while retaining the separate Sentinel bridge-specific sudoers entry for restart ergonomics.
- 2026-03-29: polished the remaining small doc nits after the main sync by clarifying the README's shared-core wording around dedicated runtime roots, adding Diary to the runtime-doc inventory README, and replacing the Tank transcript's host-absolute handover link with a repo-local path.
- 2026-03-29: synced active docs back to the current runtime/code surface by replacing the stale Govorun companion README with WhatsApp-specific runtime guidance, fixing the Browser Brain `existing_session` runbook contradiction, refreshing the top-level README runtime inventory, and removing dead `TELEGRAM_AGENT_ORCHESTRATOR_*` comments from the Architect env example.
- 2026-03-29: restored WhatsApp Govorun to Russian-only behavior by switching its runtime-local persona back to Russian-only replies, translating Govorun-specific WhatsApp bridge UI strings (`TELEGRAM_RESPONSE_STYLE_HINT`, progress text, busy notice, low-confidence voice retry prompt) back to Russian in the repo mirrors/live env, and keeping the change isolated to the Govorun WhatsApp runtime so other Telegram/sibling bots remain English.
- 2026-03-28: expanded `Mavali ETH` into a venue-operations runtime by landing the generic venue-bootstrap substrate, persisted bootstrap run/credential state, modular prompt routing, richer owner-bound Aster and Hyperliquid command parsing/execution paths, the bridge-side guard that blocks Codex fallback from advertising `confirm` when no real `mavali_eth` pending action exists, focused regression coverage for the new service/store/bridge paths, and updated operator docs/spec coverage for the live Mavali ETH current-state/bootstrap surface.
- 2026-03-28: applied the post-orchestrator elegance cleanup by removing the now-unused `parse_capped_int_env` helper from `src/telegram_bridge/runtime_config.py` and splitting `process_prompt` in `src/telegram_bridge/handlers.py` into smaller internal phases for memory-turn setup, affective-turn setup, and request-start logging without changing behavior; focused bridge regression coverage remains green (`python3 -m unittest tests/telegram_bridge/test_bridge_core.py tests/telegram_bridge/test_runtime_config.py tests/telegram_bridge/test_affective_runtime.py tests/telegram_bridge/test_diary_bridge_flow.py`).
- 2026-03-27: removed the shared-bridge worker-split orchestrator entirely after live latency evidence showed the planner/worker subprocess fan-out was too expensive for interactive use; Architect now always goes straight to the main executor path, the `TELEGRAM_AGENT_ORCHESTRATOR_*` config surface and related docs/env examples are gone, the standalone orchestrator helper scripts/module were deleted, and the focused bridge regression suite stays green (`python3 -m unittest tests/telegram_bridge/test_bridge_core.py tests/telegram_bridge/test_runtime_config.py tests/telegram_bridge/test_affective_runtime.py tests/telegram_bridge/test_diary_bridge_flow.py`).

## Current Risks/Watchouts (Max 5)
- The external USB HDD at `/srv/external/server3-arr` is now the live Arr data disk for both `downloads` and `media`; avoid unplugging it while Server3 is running, and treat any future disk replacement as a full data-plane migration rather than a casual hot-swap.
- The monitoring stack binds Grafana specifically to `192.168.0.148:3000`; if Server3's LAN IP changes, update `/etc/default/server3-monitoring` and restart `server3-monitoring.service`.
- The new Server3 backup path is local-only on the attached USB backup disk at `/srv/external/server3-backups`; if the host and that backup disk are lost together, the rebuild path is gone.
- Tank keeps `/home/tank/tankbot/src` linked to the shared repo source tree; preserve `TELEGRAM_RUNTIME_ROOT=/home/tank/tankbot` in its unit/env so runtime identity does not collapse back to the shared repo root.
- `Mavali ETH` is live on a temporary public Ethereum RPC (`https://mainnet.gateway.tenderly.co`); replace it with a dedicated authenticated provider before treating the wallet runtime as durable production infrastructure.

## Archive Pointer
- `SERVER3_ARCHIVE.md` is the canonical long-term detailed history.
- For per-change rollout evidence, use `logs/changes/*.md`.
