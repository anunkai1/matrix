# Server3 Summary

Last updated: 2026-04-17 (AEST, +10:00)

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
- 2026-04-17: updated `docs/projects/foodle.html` so the combined calendar now supports a second dot-style marker for coffee in brown, alongside the existing fasting dot. Foodle now exposes a coffee tracker card, coffee-day counter, legend entry, and shared-calendar copy that explicitly describes the two dot markers without altering the three main sugar/carbs/dairy bands.
- 2026-04-17: updated the Telegram `/help` and `/h` output so Architect now explicitly tells operators to mention `server2` or `staker2` when they want a request targeted at the LAN-connected Server2 host over SSH; added focused bridge test coverage for the new help line and restarted the live Architect bridge so the wording is active.
- 2026-04-16: adjusted the Foodle mobile calendar sketch in `docs/projects/foodle.html` so the active logging date is repeated directly above the heatmap as a prominent weekday/date pill, weekday labels are shown for all seven rows with the active weekday emphasized, the active month gets a visible tag, and the highlighted day cell now reads more clearly on phones without changing the underlying data model.
- 2026-04-15: fixed Tank's live persona instructions so the runtime no longer identifies as Govorun or defaults into Russian on low-context prompts like bare YouTube links; `infra/runtime_personas/tank.AGENTS.md` now defines Tank-specific identity plus explicit language fallback rules (current-message language, then source language, else English), and `bash ops/runtime_personas/sync_tank_agents.sh --check` confirms the live `/home/tank/tankbot/AGENTS.md` matches the tracked file.
- 2026-04-15: opened the Server3 control plane to the LAN subnet by adding a host-firewall allow rule for `8420/tcp` from `192.168.0.0/24`; verified `ufw status` now lists `8420/tcp ALLOW IN 192.168.0.0/24`, `iptables` includes the matching `ufw-user-input` accept rule, and the control-plane service remained healthy while `http://192.168.0.148:8420/api/operator/status` continued returning `200` locally.
- 2026-04-14: upgraded the host-global `@openai/codex` npm package from `0.112.0` to `0.120.0` via `sudo npm install -g @openai/codex@0.120.0`; verified the active `/usr/bin/codex` now resolves to `/usr/lib/node_modules/@openai/codex/bin/codex.js` and reports `codex-cli 0.120.0`.
- 2026-04-13: added FileGator publishing support for SignalTube Lab so `ops/signaltube_lab.py publish` can push the current rendered HTML into `https://mavali.top/projects/SignalTube/index.html`, and both `render` and `scheduled-collect` now auto-publish to that same destination whenever `SIGNALTUBE_PUBLISH_*` env vars are present. Added the Playwright-backed helper `ops/signaltube_publish_filegator.py`, publish config helpers in `src/signaltube/publish.py`, focused CLI coverage, repo env examples, and docs. Also verified the live FileGator host by creating `/projects/SignalTube/` and uploading the current `index.html`.
- 2026-04-13: updated SignalTube Lab feed rendering with a top-of-page topic jump bar so each topic is clickable and scrolls directly to its section. Topic sections now render stable anchor ids derived from topic names, the live `private/signaltube/feed.html` was rerendered with jump links for the current active topics, and focused render/store tests now cover the nav markup.

## Current Risks/Watchouts (Max 5)
- The external USB HDD at `/srv/external/server3-arr` is now the live Arr data disk for both `downloads` and `media`; avoid unplugging it while Server3 is running, and treat any future disk replacement as a full data-plane migration rather than a casual hot-swap.
- The monitoring stack currently binds Grafana to `192.168.0.148:3000`, but that host-specific LAN IP can change; if it does, update `/etc/default/server3-monitoring` and restart `server3-monitoring.service`.
- The new Server3 backup path is local-only on the attached USB backup disk at `/srv/external/server3-backups`; if the host and that backup disk are lost together, the rebuild path is gone.
- Tank keeps `/home/tank/tankbot/src` linked to the shared repo source tree; preserve `TELEGRAM_RUNTIME_ROOT=/home/tank/tankbot` in its unit/env so runtime identity does not collapse back to the shared repo root.
- `Mavali ETH` is live on a temporary public Ethereum RPC (`https://mainnet.gateway.tenderly.co`); replace it with a dedicated authenticated provider before treating the wallet runtime as durable production infrastructure.

## Archive Pointer
- `SERVER3_ARCHIVE.md` is the canonical long-term detailed history.
- For per-change rollout evidence, use `logs/changes/*.md`.
