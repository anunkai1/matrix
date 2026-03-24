# Server3 Archive

This file stores detailed operational history for Server3 tasks.

## 2026-03-24 (Summary Roll-Forward Trim for Diary Runtime Scaffold)

Summary:
- Added a new rolling-summary entry for the non-live `Diary` Telegram runtime scaffold, covering the isolated persona docs plus the env and systemd templates while deliberately deferring manifest/runtime-status integration until live deployment.
- Re-trimmed `SERVER3_SUMMARY.md` back to the rolling max-8 recent-change bound.

Migrated out of summary during this trim:
- 2026-03-23: taught the Govorun WhatsApp plugin ingress to batch consecutive inbound photo messages from the same sender/chat into one multi-image update with a short quiet window, aligning WhatsApp photo albums with the shared Python multi-image path and updating the Govorun runbook/bridge README to match.

## 2026-03-24 (Summary Roll-Forward Trim for AgentSmith Recreated Group Allowlist)

Summary:
- Added a new rolling-summary entry for allowlisting the recreated AgentSmith Telegram group `-5168463727` after the original group was accidentally deleted, including the live bridge restart verification and the note that topic-memory relink is still deferred.
- Re-trimmed `SERVER3_SUMMARY.md` back to the rolling max-8 recent-change bound.

Migrated out of summary during this trim:
- 2026-03-23: hardened Architect Telegram album handling again by buffering `media_group_id` photo batches across poll cycles with a short quiet-window flush, so 3/5/6/10-photo sends no longer depend on all album items landing in the same `getUpdates` response.
- 2026-03-23: taught the Architect Telegram bridge to collapse `media_group_id` albums into one request and carry multiple photo attachments through to Codex, so album-style image batches no longer fall into the per-chat busy guard after the first photo.

## 2026-03-22 (Runtime Doc Source-Of-Truth Migration)

Summary:
- Completed the Server3 runtime-doc migration so tracked runtime persona files now live canonically in `infra/runtime_personas` and tracked companion runtime docs now live canonically in `docs/runtime_docs`.
- Wired the live runtime roots for AgentSmith, Tank, Trinity, Govorun, Oracle, Mavali ETH, and Macrorayd back to those repo copies through symlinks.
- Added `ops/runtime_personas/check_runtime_repo_links.sh` plus `docs/runbooks/runtime-doc-source-of-truth.md` so both humans and LLMs have one canonical verification path.
- Pruned the temporary `*.pre-repo-link` rollback files after verification passed.
- Deleted Tank's retired local `emotion_mvp` prototype and removed the stale repo references after confirming the live Tank runtime was not using it.

Notes:
- This change intentionally did not move secrets, `.local/state` runtime data, caches, attachments, or live sqlite databases into git.
- The repo is now the canonical source for tracked runtime policy/docs; live runtime roots remain deployment paths only.

## 2026-03-20 (Summary Roll-Forward Trim for Mental Model Topology Tightening)

Summary:
- Added a new rolling-summary entry for tightening `docs/server3-mental-model.md` against the current runtime manifest and systemd inventory so the high-level topology now explicitly lists the newer Telegram entry points and the live Browser Brain service root.
- Re-trimmed `SERVER3_SUMMARY.md` back to the rolling max-8 recent-change bound.

Migrated out of summary during this trim:
- 2026-03-18: fixed the remaining live `Mavali ETH` Telegram/runtime bugs by teaching `src/mavali_eth/service.py` to strip the memory wrapper's `Current User Input:` section before intent matching, updating `src/telegram_bridge/session_manager.py` so restart requests fall back to the runtime's own `UNIT_NAME`, adding the repo/live sudoers mirror for `mavali_eth`, verifying `python3 -m unittest tests.mavali_eth.test_service tests.telegram_bridge.test_mavali_eth_plugin tests.telegram_bridge.test_session_manager`, and confirming `sudo -u mavali_eth bash /home/architect/matrix/ops/telegram-bridge/restart_and_verify.sh --unit telegram-mavali-eth-bridge.service` passes.

## 2026-03-19 (Summary Roll-Forward Trim for Architect Group Allowlist Fix)

Summary:
- Added a new rolling-summary entry for the live Architect Telegram allowlist fix after `architect#2` started arriving as a separate supergroup chat id once topics were enabled.
- Re-trimmed `SERVER3_SUMMARY.md` back to the rolling max-8 recent-change bound.

Migrated out of summary during this trim:
- 2026-03-18: rolled out the live `Mavali ETH` runtime on Server3 by provisioning the `mavali_eth` user/root, installing the shared-core overlay shims and dedicated signing venv, staging the wallet keystore into `/home/mavali_eth/.local/state/telegram-mavali-eth-bridge/wallet.json`, writing `/etc/default/telegram-mavali-eth-bridge` with owner chat `211761499`, starting `telegram-mavali-eth-bridge.service`, enabling `mavali-eth-receipt-monitor.timer`, verifying CLI wallet/balance/gas reads, and sending a Telegram deployment smoke message to the owner chat; temporary RPC is `https://mainnet.gateway.tenderly.co`.

## 2026-03-19 (Summary Roll-Forward Trim for Mavali ETH Doc Alignment)

Summary:
- Added a new rolling-summary entry for aligning the `Mavali ETH` spec/runbook/contract/runtime-manifest/env example with the live Server3 state, including the wallet-first hybrid runtime behavior and the intentionally temporary Tenderly RPC note.
- Re-trimmed `SERVER3_SUMMARY.md` back to the rolling max-8 recent-change bound.

Migrated out of summary during this trim:
- 2026-03-18: added Browser Brain `existing_session` attach mode alongside the default managed-profile mode, with config support for local CDP attachment, a new TV-side Brave helper at `ops/tv-desktop/server3-tv-brave-browser-brain-session.sh`, runbook/docs updates, targeted unit coverage, live managed-mode restart verification, and a live attach smoke against a temporary local CDP Brave instance; the practical on-screen login path is now “launch the visible `tv` Brave helper, log in manually there once, then let Browser Brain attach over local CDP” instead of trying to run Browser Brain itself headed on a host X display.
- 2026-03-18: changed Architect's shared Telegram memory behavior so `TELEGRAM_SHARED_MEMORY_KEY=shared:architect:main` now uses per-chat live session keys during active chats, reads the shared key as archive/background context, and merges each live key back into the shared archive only when the idle-expiry path clears that chat's session; this stops DM/group topic bleed during active sessions while preserving a combined archive for later sessions and CLI use.

## 2026-03-18 (Summary Roll-Forward Trim for Mavali ETH RPC Broadcast Fix)

Summary:
- Added a new rolling-summary entry for the `Mavali ETH` raw-transaction broadcast fix that normalizes signed transaction blobs to `0x...` form before `eth_sendRawTransaction` and records the live service restart.
- Re-trimmed `SERVER3_SUMMARY.md` back to the rolling max-8 recent-change bound.

Migrated out of summary during this trim:
- 2026-03-18: removed Govorun's remaining explicit default reply-length instructions from both the live runtime policy at `/home/govorun/govorunbot/AGENTS.md` and the active WhatsApp bridge env `/etc/default/govorun-whatsapp-bridge`, then restarted `govorun-whatsapp-bridge.service` so response length is no longer pinned there either.

## 2026-03-18 (Summary Roll-Forward Trim for Mavali ETH Signer Address Fix)

Summary:
- Added a new rolling-summary entry for the `Mavali ETH` signer helper fix that normalizes lowercase hex destination addresses before transaction signing and records the offline live-keystore verification.
- Re-trimmed `SERVER3_SUMMARY.md` back to the rolling max-8 recent-change bound.

Migrated out of summary during this trim:
- 2026-03-18: centralized trusted runtime Codex auth on Server3 behind one canonical shared file at `/etc/server3-codex/auth.json` with per-user `~/.codex/auth.json` symlinks managed by the new `ops/codex/install_shared_auth.sh` helper, keeping per-user history/state/config separate while making quota/auth behavior consistent across the runtime users.

## 2026-03-18 (Summary Roll-Forward Trim for Govorun Reply-Length Unpinning)

Summary:
- Updated the top rolling summary entry to reflect that Govorun no longer has explicit default reply-length instructions in either the live runtime policy or the active WhatsApp bridge env.
- Re-trimmed `SERVER3_SUMMARY.md` back to the rolling max-8 recent-change bound.

Migrated out of summary during this trim:
- 2026-03-18: replaced the Govorun WhatsApp 09:00 daily message rotation with a local Reddit-backed cache of highly popular `r/LifeProTips` posts from the last 5 years plus persistent anti-repeat SQLite history, then widened the cache refresh to merge several top-sorted subreddit search paths so the live source pool holds hundreds of unique cached posts while preserving the full cached source advice in Russian without adding a Reddit/source link; `LPT request` posts are now explicitly excluded and the existing request rows were purged from the live cache.

## 2026-03-16 (Architect Env Permission Hardening)

Summary:
- Hardened the live Architect Telegram env secret surface by changing `/etc/default/telegram-architect-bridge` and all readable `telegram-architect-bridge.bak*` plus `telegram-architect-whatsapp-bridge.bak*` backup copies under `/etc/default/` to `root:root` mode `600`.
- Verified after the permission change that `telegram-architect-bridge.service`, `telegram-tank-bridge.service`, and `telegram-macrorayd-bridge.service` all remained active, so the tighter env-file permissions did not break the bridge runtime.

Notes:
- This change only reduced local readability of the Architect env family; it did not rotate any bot/auth tokens and did not yet apply the same lockdown to other secret-bearing env files on the host.

## 2026-03-16 (Remaining Live Env Permission Hardening)

Summary:
- Hardened the remaining broader-read live `/etc/default` families for `telegram-tank-bridge`, `server3-runtime-observer`, `signal-oracle-bridge`, `oracle-signal-bridge`, `server3-state-backup`, and `govorun-whatsapp-daily-uplift` plus the readable backup copies that existed for Tank, runtime observer, and Signal Oracle.
- Verified after the permission change that `telegram-tank-bridge.service`, `signal-oracle-bridge.service`, `oracle-signal-bridge.service`, `server3-runtime-observer.timer`, `server3-state-backup.timer`, and `govorun-whatsapp-daily-uplift.timer` all remained active.

Notes:
- This was the follow-through on the earlier Architect env hardening pass and closed the broader-read `/etc/default` watchout that had remained in `SERVER3_SUMMARY.md`.

## 2026-03-15 (Server3 TV Neutral Start + Deterministic Browser Launch)

Summary:
- Removed the forced Brave-at-login behavior from the `tv` desktop session so Server3 TV now starts to a neutral desktop instead of opening a browser unconditionally.
- Hardened `ops/tv-desktop/server3-tv-open-browser-url.sh` to wait for the real `tv` session readiness, pass the correct TV-session environment (`DISPLAY`, `XAUTHORITY`, `XDG_RUNTIME_DIR`, DBus bus), and launch Firefox with a dedicated TV-only profile under the snap-managed path.
- Verified live behavior end to end: cold TV start now opens no browser, explicit Firefox launch reaches YouTube cleanly, explicit Brave launch still works, and TV shutdown still tears the session down cleanly.

Notes:
- `SERVER3_SUMMARY.md` was intentionally left unchanged in git for this change set because the local Arr-privacy pre-commit hook blocks staging that tracked file in this clone.

## 2026-03-15 (Summary Roll-Forward Trim for Arr Verification Closure)

Summary:
- Added a new rolling-summary entry documenting that the external Arr/media data plane has now been directly verified working correctly on the live mount stack.
- Removed the now-stale degraded-recovery verification follow-up from `SERVER3_SUMMARY.md` and cleared the matching active watchout.

Migrated out of summary during this trim:
- 2026-03-13: moved the high-growth local content data plane onto the external Toshiba USB HDD (`SERVER3_ARR`) through persistent mounts, which relieved root-disk pressure to about `32%` used; the cutover landed in a degraded recovery state and should be treated as needing direct content verification before any further cleanup.

## 2026-03-15 (Summary Roll-Forward Trim for Backup Retention Reduction)

Summary:
- Added a new rolling-summary entry for reducing `server3-state-backup` retention from 12 monthly snapshots to 3 across the live profile and tracked repo defaults.
- Re-trimmed `SERVER3_SUMMARY.md` back to the rolling max-8 recent-change bound.

Migrated out of summary during this trim:
- 2026-03-13: deployed a LAN-only Server3 monitoring stack with `server3-monitoring.service`, Dockerized `node_exporter` + Prometheus + Grafana, a provisioned `Server3 Node Overview` dashboard, Grafana bound to `192.168.0.148:3000`, Prometheus bound to `127.0.0.1:9090`, and live config in `/etc/default/server3-monitoring`.
- 2026-03-11: implemented the first `mavali_eth` MVP code path in the shared repo by adding a deterministic Ethereum wallet engine plugin, shared SQLite pending/ledger state, JSON-RPC wallet reads, signer-helper integration, a CLI surface, a receipt-monitor script, runtime env/unit/timer templates, and an operator runbook; the spec now reflects that `mavali_eth` is repo-implemented and live rollout is pending real env/RPC provisioning on Server3.

## 2026-03-15 (Summary Roll-Forward Trim for Server3 TV Bluetooth Enablement)

Summary:
- Added a new rolling-summary entry for enabling the Server3 TV Bluetooth stack and live `Blueman` pairing UI.
- Re-trimmed `SERVER3_SUMMARY.md` back to the rolling max-8 recent-change bound.

Migrated out of summary during this trim:
- 2026-03-13: added the official `Node Exporter Full` Grafana dashboard (`gnetId=1860`, revision `42`) to the LAN-only Server3 monitoring stack and verified it is live in the `Server3` folder alongside `Server3 Node Overview`.
- 2026-03-11: implemented the first `mavali_eth` MVP code path in the shared repo by adding a deterministic Ethereum wallet engine plugin, shared SQLite pending/ledger state, JSON-RPC wallet reads, signer-helper integration, a CLI surface, a receipt-monitor script, runtime env/unit/timer templates, and an operator runbook; the spec now reflects that `mavali_eth` is repo-implemented and live rollout is pending real env/RPC provisioning on Server3.

## 2026-03-15 (Summary Roll-Forward Trim for Server3 State Backup)

Summary:
- Added a new rolling-summary entry for the Server3 monthly quiesced state-backup workflow, restore helpers, and pinned backup service/timer memory in `SERVER3_SUMMARY.md`.
- Re-trimmed `SERVER3_SUMMARY.md` back to the rolling max-8 recent-change bound and max-10 pinned-memory bound.

Migrated out of summary during this trim:
- 2026-03-11: pinned the remaining `mavali_eth` planning decisions by defining inbound ETH as `2` confirmations, pinning the Telegram owner env field, defining strict raw `0x...` address parsing, and defining the mandatory transaction-confirmation prompt fields in both the human spec and the contract.
- Govorun WhatsApp behavior is env-tunable: progress wording, busy-lock wording, and reply-tone guidance are configured via `/etc/default/govorun-whatsapp-bridge`.
- WhatsApp progress edit behavior relies on valid outbound key mappings; mismatch paths should be treated as warning conditions.

## 2026-03-15 (Summary Roll-Forward Trim for Codex CLI Upgrade)

Summary:
- Added a new rolling-summary entry for the global Codex CLI upgrade on Server3.
- Re-trimmed `SERVER3_SUMMARY.md` to the rolling max-8 recent-change bound.

Migrated out of summary during this trim:
- 2026-03-11: completed the local media path normalization end to end by moving the catalog service from `/media` to `/data/media`, updating persisted library paths, and verifying the downloader, importers, request service, and catalog all respond cleanly with the library now indexed only under `/data/media/...`.

## 2026-03-08 (Summary Roll-Forward Trim for Off-Repo Runtime Path Compatibility Fix)

Summary:
- Added a new rolling-summary entry for the off-repo runtime path-compatibility fix after local-only service restore.
- Re-trimmed `SERVER3_SUMMARY.md` to the rolling max-8 recent-change bound.

Migrated out of summary during this trim:
- 2026-03-07: fixed Oracle Signal identity persistence bugs by making memory reset actually delete conversation messages/facts/summaries (not just the thread row), removing the hard-coded `Architect` assistant label from memory writes, and removing the Oracle-specific `TELEGRAM_RESPONSE_STYLE_HINT` override so persona/identity now come only from Oracle's `AGENTS.md`.

## 2026-03-08 (Summary Roll-Forward Trim for Local-Only Runtime Restore)

Summary:
- Added a new rolling-summary entry for restoration of a local-only runtime stack from retained host data outside git after live availability was removed too broadly.
- Re-trimmed `SERVER3_SUMMARY.md` to the rolling max-8 recent-change bound.

Migrated out of summary during this trim:
- 2026-03-07: fixed Oracle Signal in-chat `/restart` by adding `oracle-signal-bridge.service` to the shared restart-helper allowlist, adding Oracle-specific `TELEGRAM_RESTART_SCRIPT`/`TELEGRAM_RESTART_UNIT` env defaults, and provisioning a least-privilege sudoers rule for user `oracle` so restart requests no longer fall back to the removed local workspace path or the Architect unit.

## 2026-03-08 (Summary Roll-Forward Trim for ASTER Backburner Leverage)

Summary:
- Added a new rolling-summary entry for the live ASTER leverage env change on Server3.
- Re-trimmed `SERVER3_SUMMARY.md` to the rolling max-8 recent-change bound.

Migrated out of summary during this trim:
- 2026-03-07: adjusted Oracle Signal compact progress rendering so blank `TELEGRAM_PROGRESS_ELAPSED_PREFIX`/`TELEGRAM_PROGRESS_ELAPSED_SUFFIX` now suppress the stale elapsed text entirely; Oracle Signal defaults now show `Oracle is thinking...` instead of `Oracle is thinking... Already 1s` on channels like Signal where progress edits do not update in-place.

## 2026-03-08 (Summary Roll-Forward Trim for Oracle Signal Readiness Gate)

Summary:
- Added a new rolling-summary entry for Oracle Signal startup hardening with an explicit transport readiness gate plus dependency-safe live restart flow.
- Re-trimmed `SERVER3_SUMMARY.md` to the rolling max-8 recent-change bound.

Migrated out of summary during this trim:
- 2026-03-07: reduced the deployed Oracle Signal workspace at `/home/oracle/oraclebot` to a minimal runtime layout by changing `ops/signal_oracle/deploy_bridge.sh` to deploy only `src/telegram_bridge` while preserving Oracle's live `AGENTS.md` as the runtime persona/identity truth file, removing inherited Architect docs/tests/ops/instructions from the live Oracle workspace; documented the intentional minimal layout in `docs/runbooks/oracle-signal-operations.md`.

## 2026-03-08 (Summary Roll-Forward Trim for Residual Boot Cleanup)

Summary:
- Added a new rolling-summary entry for removal of stale local boot wiring that was still reappearing after restart from ignored local payload paths outside git.
- Re-trimmed `SERVER3_SUMMARY.md` to the rolling max-8 recent-change bound.

Migrated out of summary during this trim:
- 2026-03-07: fixed live Oracle Signal executor startup failure caused by the dedicated `oracle` runtime user missing Codex CLI auth (`~/.codex/auth.json`), provisioned the runtime auth on Server3, and hardened Oracle Signal ops so startup now fails fast with an explicit operator error when auth is absent; documented the required bootstrap step in `docs/runbooks/oracle-signal-operations.md` and enforced it in `ops/signal_oracle/start_service.sh`.

## 2026-03-07 (Summary Roll-Forward Trim for Oracle Signal Default Ports)

Summary:
- Added a new rolling-summary entry for the Oracle Signal default-port correction in code/tests.
- Re-trimmed `SERVER3_SUMMARY.md` to the rolling max-8 recent-change bound.

Migrated out of summary during this trim:
- 2026-03-07: added repo support for a new dedicated Signal persona/runtime `oracle` using the existing shared Python bridge plus a new local Signal transport sidecar around `signal-cli`: new `signal` channel plugin and shared HTTP adapter (`src/telegram_bridge/signal_channel.py`, `src/telegram_bridge/http_channel.py`, `src/telegram_bridge/plugin_registry.py`), shared-bridge config/handler upgrades for `sig:` memory keys, optional unlisted Signal DM/group admission, chat-only keyword-routing disable, and no-edit progress fallback (`src/telegram_bridge/main.py`, `src/telegram_bridge/handlers.py`, `src/telegram_bridge/memory_engine.py`), transport service/runtime assets (`ops/signal_oracle/bridge/signal_oracle_bridge.py`, `infra/systemd/*signal-oracle*.service`, `infra/env/*signal-oracle*.env.example`, `ops/signal_oracle/*.sh`), new operations runbook (`docs/runbooks/oracle-signal-operations.md`), regression coverage in `tests/telegram_bridge/test_bridge_core.py`, `tests/telegram_bridge/test_memory_engine.py`, and `tests/signal_oracle_bridge/test_signal_oracle_bridge.py`, plus follow-up default-port correction in repo templates/runbook from `8080/8797` to dedicated local ports `18080/18797` after discovering Docker already occupied `8080` on Server3.

## 2026-03-07 (Summary Roll-Forward Trim for Docs Consistency Pass)

Summary:
- Added a new rolling-summary entry for the 2026-03-07 docs consistency pass.
- Re-trimmed `SERVER3_SUMMARY.md` to the rolling max-8 recent-change bound and max-10 pinned-memory bound.

Migrated out of summary during this trim:
- 2026-03-07: added natural-language shared-memory recall for Architect bridge + CLI so plain-English prompts like “what were my last 5 messages?”, “what were your last 5 messages?”, “what do you remember from today?”, “what facts do you remember?”, and “what’s the latest summary?” are intercepted before Codex execution and answered directly from SQLite shared memory using Brisbane-time windowing; added regression coverage in `tests/telegram_bridge/test_memory_engine.py`, `tests/telegram_bridge/test_bridge_core.py`, and `tests/architect_cli/test_main.py`.
- 2026-03-07: added operator-facing mental map doc `docs/server3-mental-model.md` that explains Server3 by layers (entry points, shared bridge core, deterministic operation modes, platform/safety layer), documents the main runtimes/personas (Architect, Tank, ASTER, Govorun), shows how request routing works across Telegram/WhatsApp/CLI, and points to the canonical files/docs for each subsystem; linked from `README.md` as a primary orientation document.
- 2026-03-06: added ASTER trading runtime support in repo with free-form `Trade ...` / `Aster Trade ...` keyword routing in bridge (`src/telegram_bridge/handlers.py`), deterministic backend (`src/telegram_bridge/aster_trading.py`, `ops/trading/aster/assistant_entry.py`, `ops/trading/aster/trade_cli.sh`) that enforces confirmation tickets + risk guards (max notional, max leverage, daily realized-loss stop), improved notional sizing to nearest valid lot-step with overshoot protection (`ASTER_NOTIONAL_MAX_OVERSHOOT_PCT`, default `0.15`) to reduce underfill while preventing oversized fills for tiny requests, Telegram-friendly line-by-line preview with bold-uppercase field labels, default confirmation timeout increased to 120 seconds (`ASTER_CONFIRM_TTL_SECONDS`), and live runtime speed tuning via low reasoning override (`ARCHITECT_EXEC_ARGS="--config model_reasoning_effort=\"low\""`), plus new service/env templates (`infra/systemd/telegram-aster-trader-bridge.service`, `infra/env/telegram-aster-trader-bridge.env.example`), operations runbook (`docs/runbooks/aster-trader-operations.md`), restart helper allowlist update (`ops/telegram-bridge/restart_and_verify.sh`), regression tests (`tests/telegram_bridge/test_bridge_core.py`, `tests/telegram_bridge/test_aster_trading.py`), CI fix to install `requests` in `.github/workflows/telegram-bridge-ci.yml` so unit tests can import `src/telegram_bridge/aster_trading.py` on GitHub runners, and live ASTER bot tuning change on Server3 to set `/etc/default/telegram-aster-trader-bridge` `ARCHITECT_EXEC_ARGS` from `model_reasoning_effort="low"` to `model_reasoning_effort="high"` with service restart.

## 2026-03-07 (Summary Roll-Forward Trim for Server3 Mental Model)

Summary:
- Added a new rolling-summary entry for the operator-facing Server3 mental model document.
- Kept the rolling bound by migrating one oldest entry from summary into archive.

Migrated out of summary during this trim:
- 2026-03-05: finalized explicit tone rule for daily Govorun 09:00 WhatsApp message in code + runbook: fun/funny/light/warm/enjoyable, exactly one short fun fact, prefer funny/interesting history-culture, animals, science, space, wholesome stories, life hacks, avoid heavy topics, and no sarcasm at people; fixed short format `Доброе утро...` + `Даю справку: ...`.

## 2026-03-04 (Summary Roll-Forward Trim for Govorun Tone Control)

Summary:
- Added a new rolling-summary entry for Govorun WhatsApp tone control (`TELEGRAM_RESPONSE_STYLE_HINT`) with live runtime apply.
- Kept rolling bound by migrating one oldest entry from summary into archive.

Migrated out of summary during this trim:
- 2026-03-04: made WhatsApp `/help` and `/h` output minimal and command-only (`/start`, `/help`, `/status`, `/reset`, `/cancel`, `/restart`) by channel-specific help rendering in `src/telegram_bridge/handlers.py`; removed non-applicable WhatsApp help lines (voice-alias, TV helpers, routing keywords, memory help) for `channel_plugin=whatsapp`.

## 2026-03-04 (Summary Roll-Forward Trim for Runtime Observer Live Enable)

Summary:
- Added a new rolling-summary entry for live enablement of `server3-runtime-observer.timer` with immediate service execution verification on Server3.
- Kept rolling bound by migrating one oldest entry from summary into archive.

Migrated out of summary during this trim:
- 2026-03-03: updated Govorun/WhatsApp compact progress rendering to one-line elapsed format and 1s edit cadence.

## 2026-03-04 (Summary Roll-Forward Trim for Phase-1 Runtime Observer)

Summary:
- Added a new rolling-summary entry for Phase-1 runtime observer rollout (collect-only KPI control layer, timer/service path, and operator status/24h-summary commands).
- Kept rolling bound by migrating one oldest entry from summary into archive.

Migrated out of summary during this trim:
- 2026-03-03: strict WhatsApp runtime cleanup finalized `govorun`-only ops/docs and removed legacy user-unit artifact.

## 2026-03-04 (Summary Roll-Forward Trim for Strict WhatsApp Canonicalization)

Summary:
- Added a new rolling-summary entry for strict WhatsApp canonicalization cleanup (legacy `telegram-architect-whatsapp-bridge` unit/ops/env artifact removal, canonical `govorun-whatsapp-bridge` env template path, and live alias symlink cleanup).
- Kept rolling bound by migrating one oldest entry from summary into archive.

Migrated out of summary during this trim:
- 2026-03-03: unified Server3 Codex CLI to `0.107.0` in `/usr/local`; resolved `/usr/local` vs `/usr` version mismatch.

## 2026-03-04 (Summary Retention Refactor: Operator-First)

Summary:
- Updated `SERVER3_SUMMARY.md` from time-heavy rolling history to an operator-first format:
  - `Current Snapshot`
  - `Operational Memory (Pinned)`
  - `Recent Changes (Rolling Max 8)`
  - `Current Risks/Watchouts`
- Added mandatory summary-retention policy to `ARCHITECT_INSTRUCTION.md`.
- Updated `README.md` summary-tracking pointer to reference the new operator-first retention policy.

Migrated out of summary during this refactor:
- 2026-03-03: added lessons rule to clarify file-delivery target before sending (Codex chat vs Telegram attachment).
- 2026-03-02: added keyword-routed Nextcloud operations and changed desktop trigger from `Server3 ...` to `Server3 TV ...`.
- 2026-03-02: hardened TV/browser control flow with deterministic pause/play helpers, existing-window reuse, and Firefox autoplay fallback tooling (`wmctrl`, `xdotool`, `yt-dlp`).
- 2026-03-02: added Telegram Architect `/cancel` for per-chat in-flight interruption; change-time test run recorded `85 OK`.
- 2026-03-02: removed Architect Google runtime module/config/env/docs paths; change-time test run recorded `79 OK`.
- 2026-03-01: completed Telegram plugin architecture phases (A/B/C) plus WhatsApp bridge API + dual-runtime rollout; returned Architect primary channel to Telegram after WhatsApp auth/readiness failures.
- 2026-03-01: hardened Tank runtime (dedicated Joplin profile/sync path, DM prefix bypass in private chats, reasoning lowered to `low`).
- 2026-02-28: completed Telegram outbound hardening phases 1-4 (media sends, retries/backoff, observability, structured outbound envelope).
- 2026-02-28: deployed voice transcription quality/safety improvements (decode tuning, alias correction, confidence gating) across Architect/Tank paths.

## 2026-02-26 (Repository Scope Cleanup)

Summary:
- Removed legacy media automation records and artifacts from tracked repository history scope.
- Pruned associated docs, infra templates, service units, scripts, and historical change records tied to that scope.
- Updated baseline summary/archive/target-state files so active context stays focused on Telegram Architect bridge operations.

Execution Notes:
- Cleanup was executed as an intentional scope reset requested by maintainer.
- Current active operational focus remains Telegram bridge, Architect CLI memory integration, and associated reliability tooling.

## 2026-02-26 (Managed Architect Launcher + Bridge Restart)

Summary:
- Applied managed Architect launcher to `/home/architect/.bashrc` and restarted bridge service.
- Verified launcher routing to `/home/architect/matrix/src/architect_cli/main.py`.
- Verified bridge healthy after restart and memory runtime path present.

Traceability:
- `logs/changes/20260226-200802-bashrc-launcher-apply-and-bridge-restart-live.md`


## 2026-02-28 (Summary/Archive Rebalance Migration)

Summary:
- Rebalanced tracking so summary remains short rolling context and archive carries detailed long-term history.
- Migrated pre-rebalance detailed summary content into archive verbatim to avoid data loss.
- Updated policy wording in ARCHITECT_INSTRUCTION.md and README.md to enforce bounded summary growth.

Traceability:
- Source migrated content: pre-rebalance `SERVER3_SUMMARY.md` state captured and moved in this change set.

## 2026-02-28 (Summary Roll-Forward Trim for Voice Accuracy Rollout)

Summary:
- Added a new rolling-summary entry for the voice transcription accuracy rollout (decode tuning, alias correction, low-confidence confirmation gate).
- Re-trimmed `SERVER3_SUMMARY.md` back to rolling bounds by migrating oldest entries into archive.

Migrated out of summary during this trim:
- 2026-02-28: hardened direct HA scripts to reject `--token` CLI arguments (credential safety).
- 2026-02-28: restricted bridge restart helper to explicit allowlisted units.
- 2026-02-28: hardened HA scheduler scripts to reject token CLI forwarding.
- 2026-02-28: fixed required-prefix enforcement gap for voice/media requests without captions.
- 2026-02-27: optimized TV apply ownership updates and added policy fingerprint TTL cache in worker checks.
- 2026-02-27: optimized memory prune reconciliation and synced TV startup wording.
- 2026-02-27: changed TV startup browser mode to maximized (not fullscreen).
- 2026-02-27: added TV shell commands to Telegram `/help` and `/h`, then restarted bridge to activate.
- 2026-02-27: deployed command-start TV desktop profile while keeping default boot target as CLI.

## 2026-02-28 (Summary Roll-Forward Trim for Live Voice Env Apply)

Summary:
- Added a new rolling summary entry for live application of voice-accuracy env settings and bridge restart.
- Kept rolling bound by migrating one oldest entry from summary into archive.

Migrated out of summary during this trim:
- 2026-02-28: applied live Tank sudoers mirror so restart permission is restricted to `telegram-tank-bridge.service` only.

## 2026-02-28 (Summary Roll-Forward Trim for Voice Alias Learning Rollout)

Summary:
- Added a new rolling summary entry for controlled voice-alias self-learning with explicit approval commands.
- Re-trimmed summary back to rolling bounds by migrating two oldest entries into archive.

Migrated out of summary during this trim:
- 2026-02-28: removed legacy `tasks/lessons.md` compatibility stub and deleted empty `tasks/` folder after lessons migration to `docs/instructions/lessons.md`.
- 2026-02-28: recorded owner risk decisions (`H5/H6/H7/H9`) and delivered H8 hardening by rejecting `--base-url` in direct HA scripts; docs and lessons updated.

## 2026-03-16 (Summary Roll-Forward Trim for Trinity Runtime Rollout)

Summary:
- Added a new rolling summary entry for the Trinity runtime deployment, then refined it once Trinity moved from a shared-core overlay to its own dedicated code tree.
- Re-trimmed the rolling summary back to bound by migrating one oldest item into archive.

Migrated out of summary during this trim:
- 2026-03-13: provisioned a new isolated Telegram helper runtime `Macrorayd` with its own Linux user, runtime root, env/state/log separation, service template `telegram-macrorayd-bridge.service`, env template `infra/env/telegram-macrorayd-bridge.env.example`, restart wiring (`TELEGRAM_RESTART_UNIT` + dedicated sudoers mirror), manifest entry, and a neutral runtime-local `AGENTS.md`; it is intended as a clean Codex-powered helper bot whose personality can be specialized later without changing the shared bridge core.

## 2026-02-28 (Summary Roll-Forward Trim for Tank Voice Live Apply)

Summary:
- Added a new rolling summary entry for Tank live application of voice improvements (decode/confidence/learning) and restart verification.
- Re-trimmed summary to rolling bound by migrating two oldest entries into archive.

Migrated out of summary during this trim:
- 2026-02-28: cleaned doc inconsistencies by removing obsolete helper-bot instructions from bridge docs, aligning voucher handoff summary/archive wording with rolling policy, and removing contradictory lessons-path history line.
- 2026-02-28: moved lessons to root-level `LESSONS.md` (with `docs/instructions/lessons.md` redirect stub) so it sits with main repo docs.

## 2026-02-28 (Summary Roll-Forward Trim for TV Startup Wording Correction)

Summary:
- Added a new rolling-summary entry for TV startup wording alignment (fullscreen -> maximized).
- Re-trimmed summary back to rolling bound by migrating one oldest entry into archive.

Migrated out of summary during this trim:
- 2026-02-28: removed `docs/instructions/lessons.md` redirect stub; `LESSONS.md` is now the only active lessons path.

## 2026-02-28 (Summary Roll-Forward Trim for Claude Code Alias Default)

Summary:
- Added a new rolling-summary entry for default voice alias correction `clode code -> claude code` with docs/env/test updates.
- Re-trimmed summary back to rolling bound by migrating two oldest entries into archive.

Migrated out of summary during this trim:
- 2026-02-28: upgraded chat summarization to structured sections (objective/decisions/state/open items/preferences/risks), added summary-regeneration helper, and regenerated all 6 existing live summaries in `/home/architect/.local/state/telegram-architect-bridge/memory.sqlite3`.
- 2026-02-28: renamed memory mode label from `full` to `all_context` across runtime/help/docs, while keeping `full` as a backward-compatible alias.

## 2026-02-28 (Summary Roll-Forward Trim for Voucher Handoff Removal)

Summary:
- Added a new rolling-summary entry for deletion of `docs/handoffs/voucher-automation-resume-handoff.md` per owner request.
- Re-trimmed summary back to rolling bounds by migrating four oldest entries into archive.

Migrated out of summary during this trim:
- 2026-02-28: completed voice rollout traceability by syncing missing live voice env mirror keys (idle-timeout/socket/log path) and verifying live Telegram voice requests after restart with warm transcriber process/socket active.
- 2026-02-28: verified Tank memory parity with Architect; ran Tank summary regeneration (0 summary rows present to rewrite) and confirmed canonical mode rows are `all_context`.
- 2026-02-28: upgraded voice transcription runtime with a warm persistent service (`voice_transcribe_service.py`) that loads on first voice request, reuses the model, auto-unloads after idle timeout (default 1 hour), uses GPU-first with CPU fallback, and applies fixed ffmpeg preprocessing when available.
- 2026-02-28: improved high-level policy clarity in `ARCHITECT_INSTRUCTION.md` (added `LESSONS.md` to session-start checklist, referenced canonical Git section to avoid duplicate workflow drift, relaxed paused-state next-action wording to accept explicit approval with a recommended phrase, and updated sudo-boundary wording to present tense).


## Legacy Snapshot Pointer (2026-02-28 Verbatim)

Summary:
- The large migrated historical summary block was moved to `SERVER3_ARCHIVE_LEGACY_20260228.md`.
- Content in the legacy file is preserved verbatim for audit/history needs.
- `SERVER3_ARCHIVE.md` remains the concise canonical archive index for ongoing updates.

Maintenance Rule:
- Add new archival entries in this file.
- Keep verbatim historical dumps in separate `SERVER3_ARCHIVE_LEGACY_*.md` files and link them here.
