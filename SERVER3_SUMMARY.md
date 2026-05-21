# Server3 Summary

Last updated: 2026-05-21 (AEST, +10:00)

## Current Snapshot
- Primary active component: `telegram-architect-bridge.service`
- Runtime pattern: Telegram long polling + live `codex app-server` for Architect Codex turns, with per-scope coalesced follow-up steering for active plain-text turns
- Live runtime inventory lives in `infra/server3-runtime-manifest.json`; verify actual state with `python3 ops/server3_runtime_status.py`.
- Architect currently defaults to `codex`; selectable chat engines are driven by live env/config (`codex`, `gemma`, `pi` in the current Architect runtime), with the user-facing `/engine` alias `ollama(s4)` now mapped to internal engine key `gemma`.
- Server3 Telegram bridge runtimes now hardwire Codex unrestricted mode in shared bridge code and ignore sandbox env overrides.
- Core capabilities: text/photo/voice/document handling, voice transcription, raw voice-note archival for reuse, outbound Telegram voice-note replies, persistent workers, safe queued `/restart`, and canonical SQLite session state. Provider-side continuity still relies on engine-native sessions (Pi JSONL per scope, Codex JSONL per exec session).
- Priority stateless routes: `HA ...`, `Server3 TV ...`, `Nextcloud ...`, `SRO ...`, and bare YouTube links.

## Operator Capabilities
- Channel/runtime surface: Server3 is a multi-channel host across Telegram, WhatsApp, and Signal, with Architect as the main operator runtime and other runtimes kept isolated by runtime root and service identity.
- Browser/UI path: Server3 has an on-demand TV desktop path (`server3-tv-start` / `server3-tv-stop`) plus script-backed browser control under `ops/tv-desktop`; the preferred visible-browser attach path is `ops/tv-desktop/server3-tv-brave-remote-debug-session.sh`.
- Browser harness: local `browser-harness` is the current browser automation path, but it needs an attachable Chrome/Brave CDP session; on this host the reliable path is the TV Brave remote-debug session rather than assuming a headless local browser is already available.
- Home Assistant verification: HA control and scheduling are script-routed through `ops/ha`, but frontend/dashboard verification sometimes requires a real rendered Lovelace view; API-only checks are not sufficient for visible card/configuration issues.
- Media handling: Architect can ingest text, photos, voice notes, documents, and Telegram photo albums; attachment state is archived in SQLite-backed attachment storage for reuse/summarization.
- Photo album batching: multi-photo Telegram handling is supported, so album-style image batches are processed as one request rather than only the first image surviving the chat busy path.
- Message targeting: Architect keeps a bounded recent-message index per chat/topic so prompts that reference a specific Telegram message ID can resolve against recent local message context instead of guessing from history.
- Outbound delivery: Architect can send Telegram file/photo attachments and outbound voice-note replies through the shared transport path.
- Voice runtime: voice-note handling uses a warm transcription service with confidence gating plus learned alias correction for recurring transcript mistakes.
- Engine/runtime selection: Architect can switch per chat/topic between `codex`, `gemma` (`ollama(s4)`), and `pi`; `/engine status` is the live truth source for engine health and overrides.
- Follow-up steering: active Codex app-server turns support same-scope plain-text follow-up steering across direct chats, groups, and forum topics, with short coalescing to fold nearby follow-up messages together.
- Safe restart: operator-triggered `/restart` is queueable and generally drain-aware, so active work usually clears before the bridge restart proceeds.
- Deterministic side corridors: Server3 exposes bounded operator routes for Home Assistant (`HA ...`), TV/Desktop (`Server3 TV ...`), Nextcloud file/calendar ops (`Nextcloud ...`), Server3 Runtime Observer (`SRO ...`), and transcript-first YouTube link handling.
- Multi-runtime host: live sibling runtimes currently include Architect, AgentSmith, Diary, Tank, Trinity, Sentinel, Govorun (WhatsApp transport + bridge), Oracle (Signal transport + bridge), Mavali ETH, and Macrorayd.
- Control-plane/ops surface: Server3 also has a local control-plane snapshot/export path, runtime observer timers, monitoring stack, monthly state backup path, and the bounded dream loop health/truth baseline.

## Operational Memory (Pinned)
- Runtime observer runs from `server3-runtime-observer.timer` every 5 minutes; live mode is currently `telegram_alerts`.
- Govorun cross-channel routing contract guard is enforced by `ops/chat-routing/validate_chat_routing_contract.py` with canonical policy in `infra/contracts/server3-chat-routing.contract.env`; daily drift timer is `server3-chat-routing-contract-check.timer`.
- Tank identity depends on `TELEGRAM_RUNTIME_ROOT=/home/tank/tankbot`; preserve it so the shared `src` tree does not collapse Tank back onto the shared repo root.
- Runtime policy/doc drift should now be checked with `bash /home/architect/matrix/ops/runtime_personas/check_runtime_repo_links.sh` before assuming a live root has diverged from Git.
- Local media services now use one canonical internal namespace: `/data/downloads` and `/data/media/...`; avoid reintroducing alternate path aliases like `/downloads`, `/tv`, `/movies`, or `/media`.
- Server3 state resilience now uses a monthly quiesced backup path (`server3-state-backup.service` / `server3-state-backup.timer`) that snapshots rebuild-critical host/app/runtime state to `/srv/external/server3-backups/state`; the Arr media payload stays on the external data disk and is intentionally excluded.
- Dream loop now runs from `server3-dream-loop.timer` around `02:15 AEST` and writes the production truth/health baseline under `/var/lib/server3-dream-loop`.

## Recent Changes (Rolling Max 20)
- 2026-05-20: enabled the bounded Server3 dream loop with a live systemd timer/service and production truth/health state under `/var/lib/server3-dream-loop`.
- 2026-05-21: voice notes now archive their raw audio into the attachment store before temp cleanup, matching the photo/document reuse pattern and preserving the source clip for later analysis.
- 2026-05-21: the shared Telegram bridge core now hardwires Codex `danger-full-access` for all Server3 Telegram bridge runtimes, ignores `TELEGRAM_CODEX_SANDBOX_MODE` drift, and logs the active Codex launch policy at startup and per turn.
- 2026-05-19: removed the DishFramed bridge integration and host repo/cache from Server3; the bridge keeps a minimal `/dishframed` rejection guard so the old command cannot fall through into Codex prompt handling.
- 2026-05-19: Architect Codex runtime now hardwires unrestricted `danger-full-access` in bridge code, ignores `TELEGRAM_CODEX_SANDBOX_MODE` overrides, and suppresses the known bundled-`bubblewrap` advisory when Codex is already unrestricted.
- 2026-05-19: Architect Telegram Codex app-server sessions now default to unrestricted `sandbox=danger-full-access`; the bridge no longer treats the bundled-bubblewrap advisory as a startup failure.
- 2026-05-19: enabled the bounded Server3 dream loop with a live systemd timer/service and production truth/health state under `/var/lib/server3-dream-loop`.
- 2026-05-18: Server3 audit fixes landed: Grafana admin credentials now load from `/etc/server3-monitoring/grafana-admin.env`, the control-plane auto-refreshes stale snapshots before serving them, restore verification matches the live timer inventory again, and the Oracle transport now tolerates client disconnects with a longer daemon startup timeout.
- 2026-05-18: Architect Telegram Codex turns now default to live `codex app-server` on Server3, and same-scope plain-text follow-up messages can steer into an active turn across direct chats, group chats, and forum topics.
- 2026-05-17: enabled the bounded Server3 dream loop with a live systemd timer/service and production truth/health state under `/var/lib/server3-dream-loop`.

## Current Risks/Watchouts (Max 5)
- The external USB HDD at `/srv/external/server3-arr` is now the live Arr data disk for both `downloads` and `media`; avoid unplugging it while Server3 is running, and treat any future disk replacement as a full data-plane migration rather than a casual hot-swap.
- The monitoring stack currently binds Grafana to `192.168.0.148:3000`, but that host-specific LAN IP can change; if it does, update `/etc/default/server3-monitoring` and restart `server3-monitoring.service`.
- The new Server3 backup path is local-only on the attached USB backup disk at `/srv/external/server3-backups`; if the host and that backup disk are lost together, the rebuild path is gone.
- Tank keeps `/home/tank/tankbot/src` linked to the shared repo source tree; preserve `TELEGRAM_RUNTIME_ROOT=/home/tank/tankbot` in its unit/env so runtime identity does not collapse back to the shared repo root.
- `Mavali ETH` is live on a temporary public Ethereum RPC (`https://mainnet.gateway.tenderly.co`); replace it with a dedicated authenticated provider before treating the wallet runtime as durable production infrastructure.

## Archive Pointer
- `SERVER3_ARCHIVE.md` is the canonical long-term detailed history.
- For per-change rollout evidence, use `logs/changes/*.md`.
