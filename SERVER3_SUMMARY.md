# Server3 Summary

Last updated: 2026-05-19 (AEST, +10:00)

## Current Snapshot
- Primary active component: `telegram-architect-bridge.service`
- Runtime pattern: Telegram long polling + live `codex app-server` for Architect Codex turns, with per-scope coalesced follow-up steering for active plain-text turns
- Live runtime inventory lives in `infra/server3-runtime-manifest.json`; verify actual state with `python3 ops/server3_runtime_status.py`.
- Architect currently defaults to `codex`; selectable chat engines are driven by live env/config (`codex`, `gemma`, `pi` in the current Architect runtime), with the user-facing `/engine` alias `ollama(s4)` now mapped to internal engine key `gemma`.
- Core capabilities: text/photo/voice/document handling, persistent workers, safe queued `/restart`, and canonical SQLite session state. Provider-side continuity still relies on engine-native sessions (Pi JSONL per scope, Codex JSONL per exec session).
- Priority stateless routes: `HA ...`, `Server3 TV ...`, `Nextcloud ...`, `SRO ...`, and bare YouTube links.

## Operational Memory (Pinned)
- Runtime observer runs from `server3-runtime-observer.timer` every 5 minutes; live mode is currently `telegram_alerts_daily`.
- Govorun cross-channel routing contract guard is enforced by `ops/chat-routing/validate_chat_routing_contract.py` with canonical policy in `infra/contracts/server3-chat-routing.contract.env`; daily drift timer is `server3-chat-routing-contract-check.timer`.
- Tank identity depends on `TELEGRAM_RUNTIME_ROOT=/home/tank/tankbot`; preserve it so the shared `src` tree does not collapse Tank back onto the shared repo root.
- Runtime policy/doc drift should now be checked with `bash /home/architect/matrix/ops/runtime_personas/check_runtime_repo_links.sh` before assuming a live root has diverged from Git.
- Local media services now use one canonical internal namespace: `/data/downloads` and `/data/media/...`; avoid reintroducing alternate path aliases like `/downloads`, `/tv`, `/movies`, or `/media`.
- Server3 state resilience now uses a monthly quiesced backup path (`server3-state-backup.service` / `server3-state-backup.timer`) that snapshots rebuild-critical host/app/runtime state to `/srv/external/server3-backups/state`; the Arr media payload stays on the external data disk and is intentionally excluded.
- Dream loop now runs from `server3-dream-loop.timer` around `02:15 AEST` and writes the production truth/health baseline under `/var/lib/server3-dream-loop`.

## Recent Changes (Rolling Max 8)
- 2026-05-18: Server3 audit fixes landed: Grafana admin credentials now load from `/etc/server3-monitoring/grafana-admin.env`, the control-plane auto-refreshes stale snapshots before serving them, restore verification matches the live timer inventory again, and the Oracle transport now tolerates client disconnects with a longer daemon startup timeout.
- 2026-05-18: Architect Telegram Codex turns now default to live `codex app-server` on Server3, and same-scope plain-text follow-up messages can steer into an active turn across direct chats, group chats, and forum topics.
- 2026-05-17: enabled the bounded Server3 dream loop with a live systemd timer/service and production truth/health state under `/var/lib/server3-dream-loop`.
- 2026-05-16: removed the retired `Ralph` loop from the repo and host cleanup scope; the old Ralph code, tests, runbook, and systemd unit definitions are no longer part of the supported Server3 runtime.
- 2026-05-15: Architect's user-facing `/engine` label for the Server4 Gemma path is now `ollama(s4)`; that engine now supports chat-scoped `/model list` and `/model <name>` selection from the live Server4 Ollama tag catalog, and Pi `ollama` model selection now also merges raw Server4 Ollama tags into `/model list` so freshly pulled tags remain selectable before Pi's own catalog refreshes.
- 2026-05-15: runtime observer now classifies Telegram poll incidents by outage bursts/duration instead of raw retry-attempt totals, and WhatsApp reconnect alerts now include close status-code context (for example `428`, `503`) to make transport instability easier to diagnose.
- 2026-05-10: added English TTS voice replies via `ops/telegram-voice/tts_english.sh`; the bridge can now return Telegram voice notes through the existing `sendVoice` pipeline.
- 2026-05-05: finished the shared-bridge packaging/refactor cleanup (`pyproject.toml`, package `__init__.py` files, reusable `env_parser.py`, split `engines/` modules) and removed the old SQLite memory-engine codepath/systemd leftovers.
## Current Risks/Watchouts (Max 5)
- The external USB HDD at `/srv/external/server3-arr` is now the live Arr data disk for both `downloads` and `media`; avoid unplugging it while Server3 is running, and treat any future disk replacement as a full data-plane migration rather than a casual hot-swap.
- The monitoring stack currently binds Grafana to `192.168.0.148:3000`, but that host-specific LAN IP can change; if it does, update `/etc/default/server3-monitoring` and restart `server3-monitoring.service`.
- The new Server3 backup path is local-only on the attached USB backup disk at `/srv/external/server3-backups`; if the host and that backup disk are lost together, the rebuild path is gone.
- Tank keeps `/home/tank/tankbot/src` linked to the shared repo source tree; preserve `TELEGRAM_RUNTIME_ROOT=/home/tank/tankbot` in its unit/env so runtime identity does not collapse back to the shared repo root.
- `Mavali ETH` is live on a temporary public Ethereum RPC (`https://mainnet.gateway.tenderly.co`); replace it with a dedicated authenticated provider before treating the wallet runtime as durable production infrastructure.

## Archive Pointer
- `SERVER3_ARCHIVE.md` is the canonical long-term detailed history.
- For per-change rollout evidence, use `logs/changes/*.md`.
