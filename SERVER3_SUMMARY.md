# Server3 Summary

Last updated: 2026-04-09 (AEST, +10:00)

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
- 2026-04-09: hardened shared YouTube link summarization in `src/telegram_bridge/handlers.py` and `ops/youtube/analyze_youtube.py` so default video summaries now include a compact but informative `Source credibility:` explanation with channel-profile context, not just a bare label; the pipeline now fetches channel metadata from YouTube itself (description, follower count, channel URL), feeds that into the model prompt, and appends a deterministic fallback note when the model omits it. The note now covers creator format, commentary vs primary reporting, channel self-description/scale, and transcript-quality caveats. Added regression coverage in `tests/telegram_bridge/test_bridge_core.py` and `tests/youtube/test_analyze_youtube.py`, and verified with `python3 -m unittest tests.youtube.test_analyze_youtube tests.telegram_bridge.test_bridge_core -q` (`172` tests, passed).
- 2026-04-09: added the new Macrorayd Telegram supergroup `chat_id=-1003547492287` to the live `/etc/default/telegram-macrorayd-bridge` allowlist after the owner added `MACRORAYD` to the group and the bridge denied the test message with `reason=chat_not_allowlisted`; confirmed the older denied id `-5196308223` was the obsolete pre-upgrade group id because Telegram returned `group chat was upgraded to a supergroup chat`, restarted `telegram-macrorayd-bridge.service` successfully at `2026-04-09 14:11 AEST`, verified startup with `allowed_chat_count=2`, and added the tracked redacted env mirror `infra/env/telegram-macrorayd-bridge.server3.redacted.env`.
- 2026-04-09: adjusted shared `mavali_eth` backburner state handling in `src/mavali_eth/backburner_strategy.py` so arming over an already-open futures position no longer locks immediately; the strategy now persists the arm-time baseline position size, keeps repricing while current size stays at that baseline, and only flips `anchor_locked=true` after the total position grows beyond the baseline; added focused coverage in `tests/mavali_eth/test_service.py`, restarted `telegram-mavali-eth-bridge.service` successfully at `2026-04-09 10:15 AEST`, normalized the live `XAGUSDT` backburner state to `anchor_locked=false initial_position_qty=2.805`, repriced the active ladder to `71.64 / 70.56 / 69.50` with stop `67.41`, and removed the stale old stop so only the current `bb-9b783bf557-stop-r2` stop remains on Aster.
- 2026-04-08: corrected shared `mavali_eth` backburner inverse-RSI seeding in `src/mavali_eth/backburner_strategy.py` so `1h` ladders now solve RSI 30 from full fetched candle history using standard Wilder/RMA state instead of truncating to the minimum trailing `period + 2` closes; added a deterministic regression in `tests/mavali_eth/test_service.py`, restarted `telegram-mavali-eth-bridge.service` successfully at `2026-04-08 15:01 AEST`, and verified the live recomputed `XAGUSDT` ladder moved to `68.42 / 67.39 / 66.37` with stop `64.37` while the currently armed pre-fix ladder remains `68.16 / 67.13 / 66.12` with stop `64.13` until a future reprice/reset cycle.
- 2026-04-08: updated shared `mavali_eth` backburner logic in `src/mavali_eth/backburner_strategy.py` so `backburner buy XAGUSDT 1h total ...` can arm over an already-open futures position, immediately place the fresh protective stop for the full live position size while still placing the normal ladder, and keep later cycle stop sizing tied to total filled position; added focused regression coverage in `tests/mavali_eth/test_service.py`, aligned the live Mavali ETH overlay shim at `/home/mavali_eth/mavali_ethbot/src/telegram_bridge/main.py` with the shared-core arm path, and restarted `telegram-mavali-eth-bridge.service` successfully at `2026-04-08 14:12 AEST`.
- 2026-04-06: hardened Govorun’s daily WhatsApp uplift sender in `ops/whatsapp_govorun/send_daily_uplift.py` so a chosen Reddit LPT is reserved in the local history DB before delivery and only flipped from `pending` to `sent` after the bridge call returns, preventing the next morning from reusing the same tip when the prior day timed out after likely delivery; added focused coverage in `tests/whatsapp_govorun/test_send_daily_uplift.py` and migrated the live Govorun uplift DB schema to include the new `delivery_status` field.
- 2026-04-03: promoted the Kids World prototype beyond a static mock by adding `src/kids_world/server.py` and `tests/kids_world/test_server.py`, so Server3 can now serve the child-shell HTML over HTTP on a local port, answer `GET /health`, and back the `Create` room with a real `POST /api/create-demo` JSON seam that the browser calls when the app is loaded from the server.
- 2026-04-03: hardened Sentinel’s autonomous host-operator behavior by patching `src/telegram_bridge/handlers.py` so Telegram turns that depend on reply targeting now inject explicit `Current Telegram Context` metadata, including the current inbound `message_id` and any replied-to message id, into the model prompt; added focused coverage in `tests/telegram_bridge/test_bridge_core.py`, deployed the patched handler into `/home/sentinel/sentinelbot/src/telegram_bridge/handlers.py`, updated Sentinel’s live `SENTINEL_INSTRUCTION.md`, `SENTINEL_SUMMARY.md`, and `LESSONS.md` so runtime isolation is treated as code/state separation rather than a host-access limit, and restarted `telegram-sentinel-bridge.service` successfully at `2026-04-03 14:55 AEST`.
- 2026-04-03: verified that the live Architect Telegram bridge can send outbound photo attachments directly through the shared transport path and used it to deliver the kids-shell GUI mockup into chat `211761499`; recorded the corresponding operator lesson in `LESSONS.md` so future file/image delivery requests check Telegram attachment capability before claiming it is unavailable.

## Current Risks/Watchouts (Max 5)
- The external USB HDD at `/srv/external/server3-arr` is now the live Arr data disk for both `downloads` and `media`; avoid unplugging it while Server3 is running, and treat any future disk replacement as a full data-plane migration rather than a casual hot-swap.
- The monitoring stack currently binds Grafana to `192.168.0.148:3000`, but that host-specific LAN IP can change; if it does, update `/etc/default/server3-monitoring` and restart `server3-monitoring.service`.
- The new Server3 backup path is local-only on the attached USB backup disk at `/srv/external/server3-backups`; if the host and that backup disk are lost together, the rebuild path is gone.
- Tank keeps `/home/tank/tankbot/src` linked to the shared repo source tree; preserve `TELEGRAM_RUNTIME_ROOT=/home/tank/tankbot` in its unit/env so runtime identity does not collapse back to the shared repo root.
- `Mavali ETH` is live on a temporary public Ethereum RPC (`https://mainnet.gateway.tenderly.co`); replace it with a dedicated authenticated provider before treating the wallet runtime as durable production infrastructure.

## Archive Pointer
- `SERVER3_ARCHIVE.md` is the canonical long-term detailed history.
- For per-change rollout evidence, use `logs/changes/*.md`.
