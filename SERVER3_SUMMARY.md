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
- 2026-04-25: clarified Telegram bridge `/status` output for current persistent-worker/memory behavior. User-facing status now reports `Saved Codex threads` instead of ambiguous `Saved contexts`, `This chat has Codex thread` instead of `This chat has saved context`, includes `Memory messages`, and no longer prints the stale-looking `legacy_idle_timeout` field while idle expiry remains disabled. Sentinel live code was updated and a safe restart was handed to the detached verifier to apply after the current request drains.
- 2026-04-25: restored Sentinel to the canonical shared Codex auth model. `architect` and `sentinel` now both link `~/.codex/auth.json` to `/etc/server3-codex/auth.json`, and the new enabled `server3-codex-auth-sync.service` runs `ops/codex/watch_shared_auth.py` to detect Architect auth replacement within ~2 seconds and relink all Codex-backed manifest runtimes, including Sentinel. The shared-auth installer is now idempotent to avoid symlink/metadata churn, the shared-auth runbook documents automatic refresh, and the Server3 state-backup profile now includes `/etc/server3-codex` plus the watcher service.
- 2026-04-25: added Server3 HDMI dance-pad gameplay support. The LTEK pad now enumerates as `03eb:8041 Atmel Corp. L-TEK Dance Pad PRO` with `/dev/input/js0` and `/dev/input/event11`; installed ITGmania `1.2.1` to `/opt/itgmania`, installed `libusb-0.1-4`, and added `ops/tv-desktop/server3-tv-itgmania.sh` to start the existing on-demand `tv` desktop and launch/focus/fullscreen ITGmania as the `tv` user. The shared TV session bootstrap now disables XFCE compositing, and the ITGmania launcher enforces the L-TEK keymap order left/right/up/down = `Joy1_B1/B2/B3/B4`. For lower pad/display latency, the ITGmania launcher now defaults HDMI to `1920x1080@119.88Hz` and keeps ITGmania true-fullscreen, no-vsync, and `InputDebounceTime=0`. Installed the `GG Basics` pop song pack under `/opt/itgmania/Songs/GG Basics`; individually requested songs go under `/opt/itgmania/Songs/V`, currently including `Starships`, `Macarena`, `Mambo NO.5`, `DRAGOSTEA DIN TEI`, `GOLDEN`, `...Baby One More Time`, `Freestyler`, `I Feel It Coming`, `I WANT YOU TO KNOW`, `Gangnam Style`, `Despacito`, `Say So`, `Chandelier`, `1 2 Step`, `Listen To Your Heart`, `Boom Boom Boom Boom!`, `CINEMA (SKRILLEX REMIX)`, `Call Me Maybe`, `Whistle`, and `Starboy`. Optional video assets were removed from `/opt/itgmania/Songs/V` after the latest song batch to keep ITGmania startup reliable; chart/audio/image assets remain installed.
- 2026-04-25: updated the host-global Codex CLI from `0.124.0` to `0.125.0` with `sudo npm install -g @openai/codex@0.125.0`. Verified the active binary remains `/usr/bin/codex`, `codex --version` reports `codex-cli 0.125.0`, `npm list -g @openai/codex --depth=0` reports `@openai/codex@0.125.0`, and `/usr/lib/node_modules/@openai/codex/package.json` now reports `0.125.0`.
- 2026-04-25: added a persistent LESSONS entry requiring real HA frontend render checks after custom Lovelace dashboard/card/resource/theme changes. This prevents API-only verification from missing visible card-level `Configuration error` failures, especially for HACS cards and chart configs.
- 2026-04-24: refreshed the tracked Server3 control-plane snapshot payloads in `docs/server3-control-plane-data.json` and `docs/server3-control-plane-data.js` from live host state. The committed snapshot now reflects `2026-04-24 07:00 AEST` runtime posture with 6 healthy runtimes, Oracle degraded, no approval items, and the updated operator playback/history surface.
- 2026-04-24: hardened Telegram shared-memory session startup against stale thread reuse. `begin_memory_turn` now reconciles the bridge's canonical per-chat thread ID with the memory engine's stored session thread before `begin_turn`, clearing stale memory-only thread IDs when bridge state is empty and syncing memory state back to the bridge thread when present. Added regression coverage in `tests/telegram_bridge/test_bridge_core.py` for both stale-clear and bridge-sync cases.
- 2026-04-24: updated the host-global Codex CLI from `0.121.0` to `0.124.0` with `sudo npm install -g @openai/codex@0.124.0`. Verified the active binary remains `/usr/bin/codex`, `codex --version` reports `codex-cli 0.124.0`, and `/usr/lib/node_modules/@openai/codex/package.json` now reports `0.124.0`. Updated the tracked target-state and live change record to match.
- 2026-04-23: replaced the temporary Server3/systemd AC schedule with native Home Assistant automations created through HA's automation editor backend. The visible enabled HA automations are `automation.ac_mid_room_heat_22c_at_11_50pm` (`23:50`, mid room heat 22C), `automation.ac_mid_and_living_heat_26c_at_5_30am` (`05:30`, mid room and living heat 26C), and `automation.ac_mid_and_living_off_at_9am` (`09:00`, mid room and living off). The earlier Server3 `ha-daily-ac-schedule-*` timers and repo files were removed in commit `2e7faa6`.
## Current Risks/Watchouts (Max 5)
- The external USB HDD at `/srv/external/server3-arr` is now the live Arr data disk for both `downloads` and `media`; avoid unplugging it while Server3 is running, and treat any future disk replacement as a full data-plane migration rather than a casual hot-swap.
- The monitoring stack currently binds Grafana to `192.168.0.148:3000`, but that host-specific LAN IP can change; if it does, update `/etc/default/server3-monitoring` and restart `server3-monitoring.service`.
- The new Server3 backup path is local-only on the attached USB backup disk at `/srv/external/server3-backups`; if the host and that backup disk are lost together, the rebuild path is gone.
- Tank keeps `/home/tank/tankbot/src` linked to the shared repo source tree; preserve `TELEGRAM_RUNTIME_ROOT=/home/tank/tankbot` in its unit/env so runtime identity does not collapse back to the shared repo root.
- `Mavali ETH` is live on a temporary public Ethereum RPC (`https://mainnet.gateway.tenderly.co`); replace it with a dedicated authenticated provider before treating the wallet runtime as durable production infrastructure.

## Archive Pointer
- `SERVER3_ARCHIVE.md` is the canonical long-term detailed history.
- For per-change rollout evidence, use `logs/changes/*.md`.
