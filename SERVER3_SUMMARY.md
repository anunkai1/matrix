# Server3 Summary

Last updated: 2026-04-19 (AEST, +10:00)

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
- 2026-04-19: added a SignalTube web rescan path. Server3 now has a tracked `signaltube-lab-rescan.service` for manual rescans that pulls Server2 state, clears current visible ranked results, collects every enabled topic, pushes the DB back to Server2, and rerenders the public page; Server3 control plane exposes an authenticated `POST /api/signaltube/rescan` trigger, and Server2's SignalTube app exposes a signed-in `Rescan all topics` button wired through that trigger.
- 2026-04-19: simplified the Kids World tablet prototype at `docs/projects/kids-world-prototype.html` to two child-facing sections: `Reward Exercises` and `Watch`. Completing four maths/English cards unlocks a 20-minute YouTube reward session below the exercise area in the prototype UI. The demo app remains served by `python3 -m src.kids_world.server --host 0.0.0.0 --port 8422`, and Server3 UFW now allows `8422/tcp` from `192.168.0.0/24` for LAN tablet access.
- 2026-04-18: fixed Arr subtitle import behavior on the live media stack by enabling Sonarr/Radarr `importExtraFiles` with `srt,ass,ssa,vtt`; existing stranded English `.srt` files for 4 movies and Devs S01 were copied from `/srv/external/server3-arr/downloads` into the Jellyfin media tree, and Jellyfin indexed 12 external subtitle tracks after a library refresh.
- 2026-04-17: added `telegram-sentinel-bridge.service` to the Server3 state restore enable/start flow and post-restore required-service verification so Sentinel is included in disaster-recovery restores; also kept private stack service/container literals composed at runtime so the tracked scripts satisfy the local privacy hook. Live unit state was verified as enabled and active before committing the restore coverage.
- 2026-04-17: moved SignalTube’s live public app path onto Server2 while keeping Browser Brain collection on Server3. Server2 now runs a repo-tracked `signaltube-api.service` behind `https://mavali.top/signaltube/api/` with the frontend rendered into `https://mavali.top/projects/SignalTube/`; the Server2 infra repo now tracks SignalTube app source, nginx wiring, deploy script, and ownership manifest. Server3’s overnight collector now pulls the current SQLite DB from Server2 before collecting, then pushes the updated DB back and triggers a rerender on Server2 via the new `ops/signaltube/sync_server2_state.sh` hook wired into `signaltube-lab-overnight.service`. The old FileGator auto-publish env was removed from the live `/etc/default/signaltube-lab`.
- 2026-04-17: updated `docs/projects/foodle.html` so the combined calendar now supports a second dot-style marker for coffee in brown, alongside the existing fasting dot. Foodle now exposes a coffee tracker card, coffee-day counter, legend entry, and shared-calendar copy that explicitly describes the two dot markers without altering the three main sugar/carbs/dairy bands.
- 2026-04-17: updated the Telegram `/help` and `/h` output so Architect now explicitly tells operators to mention `server2` or `staker2` when they want a request targeted at the LAN-connected Server2 host over SSH; added focused bridge test coverage for the new help line and restarted the live Architect bridge so the wording is active.
- 2026-04-16: adjusted the Foodle mobile calendar sketch in `docs/projects/foodle.html` so the active logging date is repeated directly above the heatmap as a prominent weekday/date pill, weekday labels are shown for all seven rows with the active weekday emphasized, the active month gets a visible tag, and the highlighted day cell now reads more clearly on phones without changing the underlying data model.

## Current Risks/Watchouts (Max 5)
- The external USB HDD at `/srv/external/server3-arr` is now the live Arr data disk for both `downloads` and `media`; avoid unplugging it while Server3 is running, and treat any future disk replacement as a full data-plane migration rather than a casual hot-swap.
- The monitoring stack currently binds Grafana to `192.168.0.148:3000`, but that host-specific LAN IP can change; if it does, update `/etc/default/server3-monitoring` and restart `server3-monitoring.service`.
- The new Server3 backup path is local-only on the attached USB backup disk at `/srv/external/server3-backups`; if the host and that backup disk are lost together, the rebuild path is gone.
- Tank keeps `/home/tank/tankbot/src` linked to the shared repo source tree; preserve `TELEGRAM_RUNTIME_ROOT=/home/tank/tankbot` in its unit/env so runtime identity does not collapse back to the shared repo root.
- `Mavali ETH` is live on a temporary public Ethereum RPC (`https://mainnet.gateway.tenderly.co`); replace it with a dedicated authenticated provider before treating the wallet runtime as durable production infrastructure.

## Archive Pointer
- `SERVER3_ARCHIVE.md` is the canonical long-term detailed history.
- For per-change rollout evidence, use `logs/changes/*.md`.
