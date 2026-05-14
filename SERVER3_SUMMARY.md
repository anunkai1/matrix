# Server3 Summary

Last updated: 2026-05-15 (AEST, +10:00)

## Current Snapshot
- Primary active component: `telegram-architect-bridge.service`
- Runtime pattern: Telegram long polling + local `codex exec`
- Live runtime inventory lives in `infra/server3-runtime-manifest.json`; verify actual state with `python3 ops/server3_runtime_status.py`.
- Architect currently defaults to `codex`; selectable chat engines are driven by live env/config (`codex`, `gemma`, `pi`, `chatgptweb` in the current Architect runtime).
- Core capabilities: text/photo/voice/document handling, persistent workers, safe queued `/restart`, and canonical SQLite session state. Provider-side continuity still relies on engine-native sessions (Pi JSONL per scope, Codex JSONL per exec session).
- Browser Brain runs in `existing_session` mode on local CDP port `9223`; use the visible `tv` Brave helper for manual-login recovery when needed.
- Priority stateless routes: `HA ...`, `Server3 TV ...`, `Server3 Browser ...` / `Browser Brain ...`, `Nextcloud ...`, `SRO ...`, and bare YouTube links.

## Operational Memory (Pinned)
- Runtime observer runs from `server3-runtime-observer.timer` every 5 minutes; live mode is currently `telegram_alerts`, not the older daily-summary mode.
- Govorun cross-channel routing contract guard is enforced by `ops/chat-routing/validate_chat_routing_contract.py` with canonical policy in `infra/contracts/server3-chat-routing.contract.env`; daily drift timer is `server3-chat-routing-contract-check.timer`.
- Browser Brain `x.com` recovery path: keep `existing_session`, launch the visible TV-side Brave helper, do any needed manual login there, then attach over local CDP. Do not switch Browser Brain itself to headed mode.
- Tank identity depends on `TELEGRAM_RUNTIME_ROOT=/home/tank/tankbot`; preserve it so the shared `src` tree does not collapse Tank back onto the shared repo root.
- Runtime policy/doc drift should now be checked with `bash /home/architect/matrix/ops/runtime_personas/check_runtime_repo_links.sh` before assuming a live root has diverged from Git.
- Local media services now use one canonical internal namespace: `/data/downloads` and `/data/media/...`; avoid reintroducing alternate path aliases like `/downloads`, `/tv`, `/movies`, or `/media`.
- Server3 state resilience now uses a monthly quiesced backup path (`server3-state-backup.service` / `server3-state-backup.timer`) that snapshots rebuild-critical host/app/runtime state to `/srv/external/server3-backups/state`; the Arr media payload stays on the external data disk and is intentionally excluded.

## Recent Changes (Rolling Max 8)
- 2026-05-15: runtime observer now classifies Telegram poll incidents by outage bursts/duration instead of raw retry-attempt totals, and WhatsApp reconnect alerts now include close status-code context (for example `428`, `503`) to make transport instability easier to diagnose.
- 2026-05-10: added English TTS voice replies via `ops/telegram-voice/tts_english.sh`; the bridge can now return Telegram voice notes through the existing `sendVoice` pipeline.
- 2026-05-05: finished the shared-bridge packaging/refactor cleanup (`pyproject.toml`, package `__init__.py` files, reusable `env_parser.py`, split `engines/` modules) and removed the old SQLite memory-engine codepath/systemd leftovers.
- 2026-04-30: removed `venice` from the user-facing `/engine` list while keeping it available as `PI_PROVIDER=venice`.
- 2026-04-28: added automatic Pi scope-session rotation/pruning so JSONL retention stays bounded without losing short-term continuity.
- 2026-04-28: promoted the experimental Browser-Brain-backed `chatgptweb` path to a selectable Architect engine; it remains text-only and brittle.
- 2026-04-26: added selectable `pi` and `gemma` engine paths with live `/engine status` reporting.

## Current Risks/Watchouts (Max 5)
- The external USB HDD at `/srv/external/server3-arr` is now the live Arr data disk for both `downloads` and `media`; avoid unplugging it while Server3 is running, and treat any future disk replacement as a full data-plane migration rather than a casual hot-swap.
- The monitoring stack currently binds Grafana to `192.168.0.148:3000`, but that host-specific LAN IP can change; if it does, update `/etc/default/server3-monitoring` and restart `server3-monitoring.service`.
- The new Server3 backup path is local-only on the attached USB backup disk at `/srv/external/server3-backups`; if the host and that backup disk are lost together, the rebuild path is gone.
- Tank keeps `/home/tank/tankbot/src` linked to the shared repo source tree; preserve `TELEGRAM_RUNTIME_ROOT=/home/tank/tankbot` in its unit/env so runtime identity does not collapse back to the shared repo root.
- `Mavali ETH` is live on a temporary public Ethereum RPC (`https://mainnet.gateway.tenderly.co`); replace it with a dedicated authenticated provider before treating the wallet runtime as durable production infrastructure.

## Archive Pointer
- `SERVER3_ARCHIVE.md` is the canonical long-term detailed history.
- For per-change rollout evidence, use `logs/changes/*.md`.
