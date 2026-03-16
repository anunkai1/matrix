# Server3 Summary

Last updated: 2026-03-16 (AEST, +10:00)

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
- Canonical runtime inventory now lives in `infra/server3-runtime-manifest.json`, with shared live inspection via `python3 ops/server3_runtime_status.py`
- Shared runtime core now lives in `/home/architect/matrix/src/telegram_bridge`; Tank/Trinity/Govorun/Oracle run as per-runtime overlays with preserved service names, env paths, AGENTS, and state roots.
- Repo workflow: direct-to-`main` with mandatory commit/push proof for non-exempt changes
- Runtime observer daily Telegram summary now appends a plain-English operator line indicating whether attention is needed.
- Runtime observer daily health delivery is centralized through `staker_alerts_bot` to chat `211761499` (single destination).

## Runtime Inventory
- Canonical manifest: `infra/server3-runtime-manifest.json`
- Shared live status command: `python3 ops/server3_runtime_status.py`
- Covered runtime groups: Architect, Tank, Trinity, Govorun transport/bridge, Oracle transport/bridge, network layer, guardrail timers, optional UI.

## Operational Memory (Pinned)
- Routing keywords:
  - `HA ...` / `Home Assistant ...` for stateless HA operation mode
  - `Server3 TV ...` for desktop/browser control mode
  - `Nextcloud ...` for Nextcloud file/calendar operation mode
- Primary channel: `telegram`; WhatsApp runtime exists in parallel (`whatsapp-govorun-bridge.service` + `govorun-whatsapp-bridge.service`).
- Runtime observer is enabled on timer (`server3-runtime-observer.timer`) with Telegram daily summary mode (`RUNTIME_OBSERVER_MODE=telegram_daily_summary`) scheduled for `08:05` AEST.
- Govorun cross-channel routing contract guard is enforced by `ops/chat-routing/validate_chat_routing_contract.py` with canonical policy in `infra/contracts/server3-chat-routing.contract.env`; daily drift timer is `server3-chat-routing-contract-check.timer`.
- TV desktop/browser reliability is hardened with deterministic helpers, existing-window reuse, and autoplay fallback tooling (`wmctrl`, `xdotool`, `yt-dlp`).
- Tank defaults are hardened: DM prefix bypass in private chats, isolated Joplin profile/path, reasoning effort `low`.
- Architect Telegram + CLI now share one neutral memory identity on Server3 via `shared:architect:main`; the shared bucket merges the existing Architect Telegram chats and CLI history while starting a fresh unified Codex session thread.
- Local media services now use one canonical internal namespace: `/data/downloads` and `/data/media/...`; avoid reintroducing alternate path aliases like `/downloads`, `/tv`, `/movies`, or `/media`.
- Server3 state resilience now uses a monthly quiesced backup path (`server3-state-backup.service` / `server3-state-backup.timer`) that snapshots rebuild-critical host/app/runtime state to `/srv/external/server3-backups/state`; the Arr media payload stays on the external data disk and is intentionally excluded.
- Server time standard for operations is Brisbane (`Australia/Brisbane`, AEST/UTC+10).

## Recent Changes (Rolling Max 8)
- 2026-03-16: provisioned a new isolated Telegram runtime `Trinity` with its own Linux user, runtime root `/home/trinity/trinitybot`, state root `/var/lib/trinitybot`, private-chat-only allowlist, dedicated service/env/sudoers wiring, restart path, backup/restore coverage, and a machine-grounded affective runtime that is default-off in shared code and enabled only in `telegram-trinity-bridge.service`.
- 2026-03-16: completed the next host-side env-secret permission hardening pass by changing the remaining broader-read live `/etc/default` families for Tank, runtime observer, Signal/Oracle, `server3-state-backup`, and `govorun-whatsapp-daily-uplift` plus their readable backup copies to `root:root` mode `600`, and verified the affected services/timers all remained active.
- 2026-03-16: hardened the Architect Telegram bridge env secrets on the live host by changing `/etc/default/telegram-architect-bridge` and its readable Architect backup copies under `/etc/default/` to `root:root` mode `600`, and verified `telegram-architect-bridge.service`, `telegram-tank-bridge.service`, and `telegram-macrorayd-bridge.service` all remained active after the permission lockdown.
- 2026-03-15: completed direct post-cutover verification for the external Arr/media data plane and confirmed content visibility plus app behavior are operating correctly on the live `/srv/external/server3-arr` mount stack, closing the degraded-recovery follow-up from the 2026-03-13 migration.
- 2026-03-15: reduced `server3-state-backup` retention from 12 monthly snapshots to 3 in the live profile and tracked repo defaults so the attached backup disk keeps only the most recent quarter of rebuild-grade state archives.
- 2026-03-15: recovered the external Arr data disk after backup verification exposed a stale mount state; confirmed the root-side placeholder tree was clean, remounted `/dev/sdb1` at `/srv/external/server3-arr`, restarted `media-stack.service`, and passed `ops/server3_state/verify_restore.sh --require-media-mount`.
- 2026-03-15: reworked Server3 state backup into a monthly quiesced restore workflow on `/srv/external/server3-backups/state`, added manifest/checksum/git-bundle output plus restore/bootstrap/verify helpers, and verified both a live snapshot and a non-destructive restore extraction while keeping the Arr media payload excluded.
- 2026-03-14: extended the Server3 monitoring stack to expose the external Arr disk `/srv/external/server3-arr` through a host cron-driven node_exporter textfile metric and added an external-disk section to `Server3 Node Overview` for total/used/free/percent-used plus `sdb` read/write throughput.

## Current Risks/Watchouts (Max 5)
- The external USB HDD at `/srv/external/server3-arr` is now the live Arr data disk for both `downloads` and `media`; avoid unplugging it while Server3 is running, and treat any future disk replacement as a full data-plane migration rather than a casual hot-swap.
- The monitoring stack binds Grafana specifically to `192.168.0.148:3000`; if Server3's LAN IP changes, update `/etc/default/server3-monitoring` and restart `server3-monitoring.service`.
- The new Server3 backup path is local-only on the attached USB backup disk at `/srv/external/server3-backups`; if the host and that backup disk are lost together, the rebuild path is gone.
- Tank keeps `/home/tank/tankbot/src` linked to the shared repo source tree; preserve `TELEGRAM_RUNTIME_ROOT=/home/tank/tankbot` in its unit/env so runtime identity does not collapse back to the shared repo root.

## Archive Pointer
- `SERVER3_ARCHIVE.md` is the canonical long-term detailed history.
- For per-change rollout evidence, use `logs/changes/*.md`.
