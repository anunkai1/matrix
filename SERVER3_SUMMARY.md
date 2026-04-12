# Server3 Summary

Last updated: 2026-04-13 (AEST, +10:00)

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
- Runtime policy/doc drift should now be checked with `bash /home/architect/matrix/ops/runtime_personas/check_runtime_repo_links.sh` before assuming a live root has diverged from Git.
- Architect memory now uses `shared:architect:main` as a shared archive identity while active Telegram chats write to per-chat live session keys under that namespace; live keys are merged back into the archive only on idle expiry, and CLI can still point directly at the shared archive.
- Local media services now use one canonical internal namespace: `/data/downloads` and `/data/media/...`; avoid reintroducing alternate path aliases like `/downloads`, `/tv`, `/movies`, or `/media`.
- Server3 state resilience now uses a monthly quiesced backup path (`server3-state-backup.service` / `server3-state-backup.timer`) that snapshots rebuild-critical host/app/runtime state to `/srv/external/server3-backups/state`; the Arr media payload stays on the external data disk and is intentionally excluded.
- Server time standard for operations is Brisbane (`Australia/Brisbane`, AEST/UTC+10).

## Recent Changes (Rolling Max 8)
- 2026-04-13: removed the default YouTube `Author reputation` injection end to end for Sentinel by aligning the stale dedicated runtime copy of `src/telegram_bridge/handlers.py` with the current shared repo version, updating the bridge regression test to assert the summary prompt omits reputation/credibility guidance and external-reputation blocks, then restarting `telegram-sentinel-bridge.service` for the live fix.
- 2026-04-11: increased Sentinel's persistent worker cap from `4` to `10` by updating the live `/etc/default/telegram-sentinel-bridge` and tracked `infra/env/telegram-sentinel-bridge.env.example`, then restarted `telegram-sentinel-bridge.service`; startup at `22:05:23 AEST` verified the live runtime now reports `Persistent workers enabled=True count=4 max=10`.
- 2026-04-11: added persistent `Seen` suppression to SignalTube Lab so cards now include a `Seen` action that copies a CLI command, a new `seen_videos` table stores suppressed `video_id`s, rendered feeds hide seen items, and future collections skip them before ranking/storage. Also removed `politics` from the active SignalTube topic set and pruned its current feed rows so the configured/scheduled topics are now `History`, `latest space videos`, `LLM AI news`, and `Ukraine Russia war`.
- 2026-04-11: added persistent channel suppression controls to SignalTube Lab so cards now include a `Don't recommend this channel` action that copies a CLI block command, blocked channels are stored in a new `blocked_channels` table, rendered feeds filter them out, and future collections skip them after metadata enrichment. Added focused CLI/store/render coverage and refreshed the live HTML so the current feed exposes the new channel-block button on every card.
- 2026-04-11: updated SignalTube Lab cards to show video duration by extending `yt-dlp` metadata enrichment, adding a schema migration for `videos.duration_text`, and rendering the duration beside channel/video-id metadata in the HTML feed. Verified with focused unit coverage plus a live scheduled-style recollection across the enabled topics so the current `private/signaltube/feed.html` now includes durations like `35:18`, `1:10:14`, and `2:21:34` where YouTube metadata provided them.
- 2026-04-11: added diversity-aware SignalTube Lab feed selection so the rendered HTML no longer just mirrors raw score order: ranking now derives lightweight story-cluster keys from video titles, `SignalTubeStore.load_ranked()` applies per-topic diversity caps of `max 2` videos per story cluster and `max 2` per channel, and focused tests now cover story clustering plus diversified store output. Verified on the live `latest space videos` dataset by rerendering the current feed from 14 near-identical Artemis II splashdown items down to 3 distinct story-angle entries.
- 2026-04-11: added feedback-aware SignalTube Lab scheduling end to end: SQLite now stores configured topics and feedback events, ranking now blends topic match, freshness, and prior feedback/channel trends, the feed copies exact feedback CLI commands from each card, and `ops/signaltube_lab.py` now supports `topics`, `feedback`, and `scheduled-collect`. Added Server3 rollout assets in `infra/systemd/signaltube-lab-overnight.{service,timer}`, `infra/env/signaltube-lab.env.example`, and `ops/signaltube/install_overnight_collector.sh`; installed the timer live on Server3 with `/etc/default/signaltube-lab` pinned to `latest space videos`, verified a real `16:26 AEST` run stored 14 ranked candidates, and added focused coverage for ranking, CLI, store/render, and runtime-manifest expectations.
- 2026-04-11: hardened Telegram current-chat/topic targeting in `src/telegram_bridge/handlers.py` after a Sentinel executor failure investigation: Telegram prompts now include authoritative current chat/topic guardrails by default, outbound text/media delivery preserves `message_thread_id`, oversized context wrappers are omitted instead of rejecting otherwise valid user prompts, and YouTube auto-routing keeps the raw user request text. Added focused regression coverage in `tests/telegram_bridge/test_bridge_core.py`, installed the updated handler into Sentinel's dedicated runtime root, and restarted `telegram-sentinel-bridge.service`.

## Current Risks/Watchouts (Max 5)
- The external USB HDD at `/srv/external/server3-arr` is now the live Arr data disk for both `downloads` and `media`; avoid unplugging it while Server3 is running, and treat any future disk replacement as a full data-plane migration rather than a casual hot-swap.
- The monitoring stack currently binds Grafana to `192.168.0.148:3000`, but that host-specific LAN IP can change; if it does, update `/etc/default/server3-monitoring` and restart `server3-monitoring.service`.
- The new Server3 backup path is local-only on the attached USB backup disk at `/srv/external/server3-backups`; if the host and that backup disk are lost together, the rebuild path is gone.
- Tank keeps `/home/tank/tankbot/src` linked to the shared repo source tree; preserve `TELEGRAM_RUNTIME_ROOT=/home/tank/tankbot` in its unit/env so runtime identity does not collapse back to the shared repo root.
- `Mavali ETH` is live on a temporary public Ethereum RPC (`https://mainnet.gateway.tenderly.co`); replace it with a dedicated authenticated provider before treating the wallet runtime as durable production infrastructure.

## Archive Pointer
- `SERVER3_ARCHIVE.md` is the canonical long-term detailed history.
- For per-change rollout evidence, use `logs/changes/*.md`.
