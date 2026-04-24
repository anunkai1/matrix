# Server3 Summary

Last updated: 2026-04-25 (AEST, +10:00)

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

## Recent Changes (Rolling Max 8)
- 2026-04-25: added a persistent LESSONS entry requiring real HA frontend render checks after custom Lovelace dashboard/card/resource/theme changes. This prevents API-only verification from missing visible card-level `Configuration error` failures, especially for HACS cards and chart configs.
- 2026-04-24: refreshed the tracked Server3 control-plane snapshot payloads in `docs/server3-control-plane-data.json` and `docs/server3-control-plane-data.js` from live host state. The committed snapshot now reflects `2026-04-24 07:00 AEST` runtime posture with 6 healthy runtimes, Oracle degraded, no approval items, and the updated operator playback/history surface.
- 2026-04-24: hardened Telegram shared-memory session startup against stale thread reuse. `begin_memory_turn` now reconciles the bridge's canonical per-chat thread ID with the memory engine's stored session thread before `begin_turn`, clearing stale memory-only thread IDs when bridge state is empty and syncing memory state back to the bridge thread when present. Added regression coverage in `tests/telegram_bridge/test_bridge_core.py` for both stale-clear and bridge-sync cases.
- 2026-04-24: updated the host-global Codex CLI from `0.121.0` to `0.124.0` with `sudo npm install -g @openai/codex@0.124.0`. Verified the active binary remains `/usr/bin/codex`, `codex --version` reports `codex-cli 0.124.0`, and `/usr/lib/node_modules/@openai/codex/package.json` now reports `0.124.0`. Updated the tracked target-state and live change record to match.
- 2026-04-23: replaced the temporary Server3/systemd AC schedule with native Home Assistant automations created through HA's automation editor backend. The visible enabled HA automations are `automation.ac_mid_room_heat_22c_at_11_50pm` (`23:50`, mid room heat 22C), `automation.ac_mid_and_living_heat_26c_at_5_30am` (`05:30`, mid room and living heat 26C), and `automation.ac_mid_and_living_off_at_9am` (`09:00`, mid room and living off). The earlier Server3 `ha-daily-ac-schedule-*` timers and repo files were removed in commit `2e7faa6`.
- 2026-04-20: updated Server2 Kidstories to use Venice text model `zai-org-glm-4.7` while keeping image model `qwen-image`; live env is `/home/lepton/kidstories-api/.env` and service is `kidstories-api.service`. The public Kidstories form at `https://mavali.top/kidstories/` now uses one story prompt textarea (`storyPrompt`) instead of separate character/theme inputs, with the backend request contract preserved by mapping that single prompt to both `characterDescription` and `theme`. Backend parsing now accepts Venice JSON wrapped in Markdown code fences; Server2 infra commit `dae5695` tracks the fix. The live frontend now recovers from long-generation client disconnects by polling the no-store library endpoint and redirecting to the new book when it appears. Rollback backups are `/home/architect/server2-maintenance/20260420-131551-kidstories-model-ui`, `/home/architect/server2-maintenance/20260420-144200-kidstories-json-parser`, and `/home/architect/server2-maintenance/20260420-145200-kidstories-client-recovery`. Verified with a 3-page live generation test (`74151ecb-4186-4adc-aa6e-171de94ade84`) and confirmed the owner's later 10-page attempt created `26f3d7f3-4ddc-4d76-930b-2e4fbc2269b3` with all page images despite a browser-side `499` disconnect.
- 2026-04-20: completed Server2 maintenance via the general `server2` SSH operations path. Created DB/app rollback snapshots under `/home/architect/server2-maintenance/20260420-083454`, `/home/architect/server2-maintenance/20260420-084820-nextcloud33`, `/home/architect/server2-maintenance/20260420-094055-node22`, and `/home/architect/server2-maintenance/20260420-111311-node24`; upgraded pending APT packages (`containerd.io`, `docker-compose-plugin`, `grafana`, `rsyslog`, `snapd`), removed stale `musl`, refreshed FileGator/Gitea/Nextcloud Docker stacks, moved Nextcloud from `32.0.5` through `32.0.8` to `33.0.2`, updated Nextcloud apps, and migrated Server2 Node from `v18.20.8` through `v22.22.2` to `v24.14.1` with npm `10.9.8`/corepack `0.34.6`; rebuilt Chordle/Kidstories dependencies after each Node jump. Verified no pending APT updates, no reboot required, no failed units, containers healthy, Nextcloud/OnlyOffice healthy, and Chordle/Kidstories/SignalTube/Gitea public health checks passing. `documentserver_community` is disabled after the Nextcloud 33 upgrade while the active `onlyoffice` app remains enabled.
- 2026-04-20/21/25: updated Foodle in `docs/projects/foodle.html` so the combined calendar starts weeks on Monday, share text includes the public URL, the mobile tracker layout keeps compact dot-tracker cards side by side, the calendar/trackers support a third red dot-style `Over eating` marker, and the top Sugar/Carb/Dairy stat cards show both longest and current streaks; the live Server2 Foodle HTML was republished after each change.

## Current Risks/Watchouts (Max 5)
- The external USB HDD at `/srv/external/server3-arr` is now the live Arr data disk for both `downloads` and `media`; avoid unplugging it while Server3 is running, and treat any future disk replacement as a full data-plane migration rather than a casual hot-swap.
- The monitoring stack currently binds Grafana to `192.168.0.148:3000`, but that host-specific LAN IP can change; if it does, update `/etc/default/server3-monitoring` and restart `server3-monitoring.service`.
- The new Server3 backup path is local-only on the attached USB backup disk at `/srv/external/server3-backups`; if the host and that backup disk are lost together, the rebuild path is gone.
- Tank keeps `/home/tank/tankbot/src` linked to the shared repo source tree; preserve `TELEGRAM_RUNTIME_ROOT=/home/tank/tankbot` in its unit/env so runtime identity does not collapse back to the shared repo root.
- `Mavali ETH` is live on a temporary public Ethereum RPC (`https://mainnet.gateway.tenderly.co`); replace it with a dedicated authenticated provider before treating the wallet runtime as durable production infrastructure.

## Archive Pointer
- `SERVER3_ARCHIVE.md` is the canonical long-term detailed history.
- For per-change rollout evidence, use `logs/changes/*.md`.
