# Server3 Summary

Last updated: 2026-03-22 (AEST, +10:00)

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
- Runtime personas now live canonically in `infra/runtime_personas`, companion runtime docs now live canonically in `docs/runtime_docs`, and the live runtime roots consume those tracked files through repo-backed symlinks verified by `bash ops/runtime_personas/check_runtime_repo_links.sh`.
- Repo workflow: direct-to-`main` with mandatory commit/push proof for non-exempt changes
- Runtime observer daily Telegram summary now appends a plain-English operator line indicating whether attention is needed.
- Runtime observer daily health delivery is centralized through `staker_alerts_bot` to chat `211761499` (single destination).

## Runtime Inventory
- Canonical manifest: `infra/server3-runtime-manifest.json`
- Shared live status command: `python3 ops/server3_runtime_status.py`
- Covered runtime groups: Architect, AgentSmith, Tank, Trinity, Govorun transport/bridge, Oracle transport/bridge, network layer, guardrail timers, optional UI.

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
- 2026-03-22: expanded `mavali_eth` from ETH-only wallet handling into the first reusable Web3 substrate slice by adding generic contract-capable RPC helpers, ERC20 metadata/balance/allowance/transfer/approve primitives, generalized pending-action and execution-journal storage, inbound ERC20 receipt monitoring, a Polymarket API spike tool, and the first live read-only Polymarket runtime integration (`show polymarket markets`, `show polymarket market <id|slug>`) with focused unit coverage across `tests/mavali_eth/*` plus the bridge plugin test.
- 2026-03-22: finished the Server3 runtime-doc source-of-truth migration by moving canonical persona files into `infra/runtime_personas`, moving tracked companion docs into `docs/runtime_docs`, wiring the live runtime roots back through repo-backed symlinks, adding `ops/runtime_personas/check_runtime_repo_links.sh` plus `docs/runbooks/runtime-doc-source-of-truth.md`, pruning stale rollback `*.pre-repo-link` files, and deleting Tank's retired `emotion_mvp` prototype after verifying it was no longer active.
- 2026-03-21: changed Govorun WhatsApp to default to English without affecting other runtimes by installing a Govorun-local English-default `AGENTS.md` at `/home/govorun/govorunbot/AGENTS.md`, adding an English-first `TELEGRAM_RESPONSE_STYLE_HINT` plus English progress/busy/low-confidence wording in `/etc/default/govorun-whatsapp-bridge`, mirroring the new defaults in repo env/docs, restarting `govorun-whatsapp-bridge.service`, and verifying the live runtime now answers `I should reply in English by default.` to a direct executor smoke test.
- 2026-03-20: tightened `docs/server3-mental-model.md` against the current code/runtime manifest by promoting AgentSmith, Trinity, Mavali ETH, and Macrorayd to first-class entry points, documenting the dedicated-vs-overlay runtime-root split more explicitly, and adding the live Browser Brain service root so the human topology matches the deployed systemd/runtime inventory.
- 2026-03-19: refreshed `docs/server3-mental-model.md` so the human-facing map now matches the current Server3 topology by adding the newer sibling runtimes, removing the stale `Trade` reference, and explaining Browser Brain's real two-mode model including the live `existing_session` plus TV-side manual-login attach path.
- 2026-03-19: granted `agentsmith` full host sudo parity with `architect` by installing `/etc/sudoers.d/agentsmith` with `NOPASSWD:ALL`, adding `agentsmith` to the `sudo` group, mirroring the new drop-in in `infra/system/sudoers/agentsmith`, and verifying `sudo -l -U agentsmith` now shows unrestricted sudo in addition to the existing bridge-specific restart rule.
- 2026-03-19: unblocked the `architect#2` Telegram group after topic enablement exposed it as a separate supergroup chat id (`-1003894351534`), confirmed live denies in `telegram-architect-bridge.service` were allowlist failures rather than topic-thread handling, added the new chat id to `/etc/default/telegram-architect-bridge`, mirrored the live env in `infra/env/telegram-architect-bridge.server3.redacted.env`, restarted `telegram-architect-bridge.service`, and verified startup logs now show `Allowed chats=[-1003894351534, -5144577688, 211761499, 1434663945]`.
- 2026-03-19: aligned the `Mavali ETH` spec/runbook/contract/runtime-manifest/env example with the live Server3 state by marking the runtime as deployed, documenting the wallet-first hybrid wallet-plus-LLM behavior, correcting the bridge-vs-receipt allowlist env roles, and explicitly recording that the live RPC intentionally remains the temporary Tenderly public gateway for now and should be replaced later with a dedicated authenticated provider.
- 2026-03-18: fixed the live `Mavali ETH` broadcast failure after confirmation by normalizing raw signed transaction blobs to `0x...` form inside `src/mavali_eth/json_rpc.py` before `eth_sendRawTransaction`, adding focused coverage in `tests/mavali_eth/test_json_rpc.py`, verifying `python3 -m unittest tests.mavali_eth.test_json_rpc tests.mavali_eth.test_eth_account_helper tests.mavali_eth.test_service tests.telegram_bridge.test_mavali_eth_plugin tests.telegram_bridge.test_session_manager`, and restarting `telegram-mavali-eth-bridge.service` so the live bridge now uses the RPC-format patch.

## Current Risks/Watchouts (Max 5)
- The external USB HDD at `/srv/external/server3-arr` is now the live Arr data disk for both `downloads` and `media`; avoid unplugging it while Server3 is running, and treat any future disk replacement as a full data-plane migration rather than a casual hot-swap.
- The monitoring stack binds Grafana specifically to `192.168.0.148:3000`; if Server3's LAN IP changes, update `/etc/default/server3-monitoring` and restart `server3-monitoring.service`.
- The new Server3 backup path is local-only on the attached USB backup disk at `/srv/external/server3-backups`; if the host and that backup disk are lost together, the rebuild path is gone.
- Tank keeps `/home/tank/tankbot/src` linked to the shared repo source tree; preserve `TELEGRAM_RUNTIME_ROOT=/home/tank/tankbot` in its unit/env so runtime identity does not collapse back to the shared repo root.
- `Mavali ETH` is live on a temporary public Ethereum RPC (`https://mainnet.gateway.tenderly.co`); replace it with a dedicated authenticated provider before treating the wallet runtime as durable production infrastructure.

## Archive Pointer
- `SERVER3_ARCHIVE.md` is the canonical long-term detailed history.
- For per-change rollout evidence, use `logs/changes/*.md`.
