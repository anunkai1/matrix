# Server3 Mental Model

This document is the human map of Server3: what exists, why it exists, how the pieces fit together, and where to look when you want to use or operate something.

## One-Sentence Model

Server3 is a multi-runtime automation host built around one reusable Python bridge core that can talk through different channels, switch into deterministic operation modes, and hand work off to local scripts or Codex execution.

## The Four Layers

### 1. Entry Points

These are the ways work enters the server.

| Entry point | Purpose | Main live service/user |
| --- | --- | --- |
| Telegram Architect bot | General assistant and operator entry point | `telegram-architect-bridge.service` as `architect` |
| Telegram Tank bot | Separate Telegram runtime/profile for Tank | `telegram-tank-bridge.service` as `tank` |
| Signal Oracle | Signal-facing assistant persona with its own transport sidecar | `signal-oracle-bridge.service` + `oracle-signal-bridge.service` as `oracle` |
| WhatsApp Govorun | WhatsApp-facing assistant persona | `whatsapp-govorun-bridge.service` + `govorun-whatsapp-bridge.service` as `govorun` |
| Local shell launchers | Direct CLI use with shared memory | `architect`, `tank`, raw `codex` |

### 2. Shared Bridge Core

The main reusable runtime lives in [`src/telegram_bridge`](../src/telegram_bridge):

- [`main.py`](../src/telegram_bridge/main.py): bootstraps config, channel plugin, polling loop, and state loading.
- [`runtime_config.py`](../src/telegram_bridge/runtime_config.py): centralizes env parsing and runtime config defaults for the shared bridge core.
- [`runtime_profile.py`](../src/telegram_bridge/runtime_profile.py): centralizes runtime-facing profile helpers such as assistant labels, keyword routing prompts, and channel reply conventions.
- [`runtime_routing.py`](../src/telegram_bridge/runtime_routing.py): centralizes prefix gating and keyword-route resolution before handlers dispatch work.
- [`handlers.py`](../src/telegram_bridge/handlers.py): command handling, keyword routing, media handling, progress updates, and restart/cancel flows.
- [`executor.py`](../src/telegram_bridge/executor.py) and [`executor.sh`](../src/telegram_bridge/executor.sh): invoke local Codex safely and stream output back.
- [`memory_engine.py`](../src/telegram_bridge/memory_engine.py): durable chat memory and summaries.
- [`session_manager.py`](../src/telegram_bridge/session_manager.py): worker/session lifecycle, busy state, and safe restart coordination.
- [`plugin_registry.py`](../src/telegram_bridge/plugin_registry.py): lets the same core speak Telegram, WhatsApp, or Signal.

Mental shortcut:
- Telegram Architect and Tank are variations of the same bridge pattern.
- Oracle reuses the same Python bridge core, but its transport is fronted by a local Signal sidecar around `signal-cli`.
- Govorun reuses the same Python bridge core, but its transport is fronted by a Node WhatsApp API bridge.

### 3. Deterministic Operation Modules

When a request should not be handled as open-ended assistant chat, the bridge can route into specific script-backed modes.

| Mode | User trigger | What it does | Main scripts |
| --- | --- | --- | --- |
| Home Assistant | `HA ...` or `Home Assistant ...` | Stateless HA control/scheduling | [`ops/ha`](../ops/ha) |
| YouTube Link | bare YouTube URL or YouTube URL with a lightweight summary/transcript request | Transcript-first video analysis via `yt-dlp` captions or local transcription | [`ops/youtube`](../ops/youtube), [`ops/telegram-voice`](../ops/telegram-voice) |
| Browser Brain | `Server3 Browser ...` or `Browser Brain ...` | Structured real-browser automation via snapshot refs | [`ops/browser_brain`](../ops/browser_brain) |
| TV/Desktop | `Server3 TV ...` | Start desktop, open browser, control YouTube | [`ops/tv-desktop`](../ops/tv-desktop) |
| Nextcloud | `Nextcloud ...` | File and calendar operations | [`ops/nextcloud`](../ops/nextcloud) |

These modes are meant to be predictable and script-bounded. They are the "do the known thing" paths, not the "figure out anything" path.

### 4. Platform and Safety Layer

This is the infrastructure around the assistant runtimes.

| Area | Purpose | Main source-of-truth |
| --- | --- | --- |
| `infra/systemd` | Live service and timer definitions | [`infra/systemd`](../infra/systemd) |
| `infra/env` | Example/redacted env shapes | [`infra/env`](../infra/env) |
| `infra/server3-runtime-manifest.json` | Canonical operator-first runtime inventory | [`infra/server3-runtime-manifest.json`](../infra/server3-runtime-manifest.json) |
| `infra/contracts` | Cross-runtime config contracts | [`infra/contracts/server3-chat-routing.contract.env`](../infra/contracts/server3-chat-routing.contract.env) |
| `ops/runtime_observer` | Daily health/KPI observer | [`ops/runtime_observer`](../ops/runtime_observer) |
| `ops/server3_runtime_status.py` | Shared live runtime inspection command | [`ops/server3_runtime_status.py`](../ops/server3_runtime_status.py) |
| `ops/chat-routing` | Routing drift validation | [`ops/chat-routing`](../ops/chat-routing) |
| `ops/system-maintenance` | Monthly apt maintenance | [`ops/system-maintenance`](../ops/system-maintenance) |
| `ops/nordvpn`, `ops/tailscale` | Network posture and coexistence | [`docs/nordvpn-server3.md`](./nordvpn-server3.md), [`docs/tailscale-server3.md`](./tailscale-server3.md) |
| `infra/system/*target-state*` | Host-level intended state snapshots | [`infra/system`](../infra/system) |

## The Main Things That Exist

### Architect

This is the primary Server3 brain.

- Service: `telegram-architect-bridge.service`
- User: `architect`
- Workspace: `/home/architect/matrix`
- Purpose: general assistant, file/image/voice handling, memory-backed conversation, and operator routing into HA/Browser Brain/TV/Nextcloud modes.
- Main docs:
  - [`docs/telegram-architect-bridge.md`](./telegram-architect-bridge.md)
  - [`SERVER3_SUMMARY.md`](../SERVER3_SUMMARY.md)

Use Architect when you want:
- normal assistant help
- repository work
- operational actions via Telegram
- access to the keyword-routed tool modes

### Tank

Tank is a separate Telegram runtime/profile, not just a command inside Architect.

- Service: `telegram-tank-bridge.service`
- User: `tank`
- Workspace: `/home/tank/tankbot`
- Purpose: isolated bot identity/profile with its own env, memory, Joplin path, and sudo scope.
- Runtime model: shared core from `/home/architect/matrix` plus Tank runtime root identity at `/home/tank/tankbot`

Mental shortcut:
- Tank uses the same bridge architecture as Architect.
- Tank is separated because identity, memory, and permissions matter.

### Oracle Signal

Oracle is the Signal-facing sibling runtime.

- Transport service: `signal-oracle-bridge.service`
- Python bridge service: `oracle-signal-bridge.service`
- User: `oracle`
- Oracle bridge workspace: `/home/oracle/oraclebot`
- Signal transport root: `/home/oracle/signal-oracle`
- Purpose: run the shared bridge core behind a dedicated Signal account with isolated memory/state and Signal-specific progress behavior.
- Runtime model: shared core from `/home/architect/matrix` plus Oracle overlay root at `/home/oracle/oraclebot`
- Runbook: [`docs/runbooks/oracle-signal-operations.md`](./runbooks/oracle-signal-operations.md)

Use Oracle when you want:
- a dedicated Signal-side assistant persona
- isolated `sig:<chat_id>` memory/state
- Signal voice-note transcription and in-chat `/restart`

Key mental rule:
- Oracle is split like Govorun: local transport sidecar plus the shared Python bridge core.
- Keyword routing is intentionally disabled in v1; Oracle is a chat-focused runtime first.

### Govorun WhatsApp

Govorun is the WhatsApp-facing persona. It is two pieces, not one.

1. `whatsapp-govorun-bridge.service`
   - Node/Baileys transport bridge
   - talks to WhatsApp
   - exposes a local HTTP API for updates, files, and sends
2. `govorun-whatsapp-bridge.service`
   - Python bridge core
   - applies routing, memory, Codex execution, prefix rules, and response policy
   - runs the shared bridge core with Govorun identity/state rooted at `/home/govorun/govorunbot`

Why it is split:
- Node handles the WhatsApp protocol and media plumbing.
- Python reuses the existing bridge logic and policy layer.

Main docs:
- [`docs/runbooks/whatsapp-govorun-operations.md`](./runbooks/whatsapp-govorun-operations.md)
- [`docs/runbooks/telegram-whatsapp-dual-runtime.md`](./runbooks/telegram-whatsapp-dual-runtime.md)

Use Govorun when you want:
- WhatsApp chat handling
- the Russian-speaking persona workflow
- daily WhatsApp uplift message automation

### Other Sibling Runtimes

Server3 also has a few newer sibling runtimes that follow the same general pattern but solve narrower jobs.

- AgentSmith: another isolated Telegram sibling runtime with its own runtime root, state, and allowlist posture.
- Trinity: a separate Telegram runtime with its own dedicated code tree and persona experiments.
- Mavali ETH: a wallet-first Ethereum runtime that keeps deterministic wallet actions but can still fall through to Codex for general prompts.
- Macrorayd: a dedicated Telegram Codex helper runtime with isolated state and room for future runtime-local personality.

Mental shortcut:
- These are real live runtimes, not just ideas or branches.
- For exhaustive current inventory, trust `infra/server3-runtime-manifest.json` first; this mental model stays intentionally higher level.

### Home Assistant Mode

This is not its own long-running service. It is a script-backed mode that Architect can enter for one request.

- Trigger: `HA ...` or `Home Assistant ...`
- Scripts: [`ops/ha`](../ops/ha)
- Docs: [`docs/home-assistant-ops.md`](./home-assistant-ops.md)

Use it when you want:
- entity on/off
- climate mode changes
- temperature changes
- scheduled HA actions with timer-backed execution

Key mental rule:
- HA mode is stateless and constrained on purpose.
- It exists to avoid ad-hoc shell actions for HA.

### Server3 TV/Desktop Mode

This is also a mode, not a full assistant persona.

- Trigger: `Server3 TV ...`
- Runtime dependency: `lightdm.service` for desktop on/off
- Scripts: [`ops/tv-desktop`](../ops/tv-desktop)
- Docs: [`docs/server3-tv-desktop.md`](./server3-tv-desktop.md)

Use it when you want:
- start or stop the desktop session
- open a URL in Brave/Firefox
- open the top YouTube result
- play/pause YouTube reliably

Key mental rule:
- Server3 normally lives in CLI mode.
- TV mode is an on-demand desktop overlay.

### Server3 Browser Brain Mode

This is the structured browser-automation corridor.

- Trigger: `Server3 Browser ...` or `Browser Brain ...`
- Runtime dependency: `server3-browser-brain.service`
- Scripts: [`ops/browser_brain`](../ops/browser_brain)
- Docs: [`docs/runbooks/server3-browser-brain.md`](./runbooks/server3-browser-brain.md)

Use it when you want:
- open or navigate real browser tabs
- inspect the current page and get actionable refs
- click or type against exact snapshot refs
- drive a managed browser session end to end
- attach to an already-open local browser session when a site needs visible manual login

Key mental rule:
- Browser Brain is the machine-operated browser substrate.
- It has two connection modes: `managed` and `existing_session`.
- TV mode is still the human-visible desktop/browser path, but it can also act as the visible login helper for Browser Brain when Browser Brain attaches over local CDP.

### Nextcloud Mode

Nextcloud is another stateless script-backed mode.

- Trigger: `Nextcloud ...`
- Scripts: [`ops/nextcloud`](../ops/nextcloud)
- Docs: [`docs/nextcloud-ops.md`](./nextcloud-ops.md)

Use it when you want:
- list/upload/delete files
- list calendars
- create calendar events

## How Requests Actually Flow

### Normal Architect or Tank request

1. Telegram message arrives.
2. Bridge long-polls via Bot API.
3. [`handlers.py`](../src/telegram_bridge/handlers.py) decides whether this is a command, normal assistant request, or keyword-routed mode.
4. For assistant requests, memory/session context is assembled.
5. [`executor.sh`](../src/telegram_bridge/executor.sh) runs local Codex.
6. Output is streamed back with typing/progress updates.
7. Memory/session state is updated.

### Keyword-routed request

1. Message starts with `HA`, `Server3 Browser`, `Browser Brain`, `Server3 TV`, or `Nextcloud`, or it contains an auto-routed YouTube link request.
2. Bridge strips the keyword and switches to the bounded mode.
3. Request runs stateless with a script allowlist or deterministic backend.
4. Result is returned without carrying open-ended conversational memory.

### Govorun WhatsApp request

1. WhatsApp message arrives in the Node bridge.
2. Node exposes it through local HTTP API.
3. Python Govorun bridge polls that API using the WhatsApp channel plugin.
4. The same handler/memory/executor machinery processes it.
5. Replies and media go back through the Node bridge to WhatsApp.

### Oracle Signal request

1. Signal message arrives in the local `signal-cli` sidecar.
2. The Signal sidecar normalizes it through the local HTTP bridge API.
3. `oracle-signal-bridge.service` polls that API using the Signal channel plugin.
4. The shared handler/memory/executor flow processes it under `sig:<chat_id>` memory keys.
5. Replies go back through the Signal sidecar; progress uses no-edit fallback behavior because Signal does not support message edits.

## Where To Look Depending On The Job

| If you want to understand... | Start here |
| --- | --- |
| overall current live posture | [`SERVER3_SUMMARY.md`](../SERVER3_SUMMARY.md) |
| detailed current bridge behavior | [`docs/telegram-architect-bridge.md`](./telegram-architect-bridge.md) |
| the actual runtime code path | [`src/telegram_bridge`](../src/telegram_bridge) |
| how to operate a service | [`ops`](../ops) and the matching runbook in [`docs`](./) |
| what units/timers exist | [`infra/systemd`](../infra/systemd) |
| what env/config shape exists | [`infra/env`](../infra/env) |
| host/network/desktop intended state | [`infra/system`](../infra/system) |
| older decisions and migrations | [`SERVER3_ARCHIVE.md`](../SERVER3_ARCHIVE.md) |

## State, Secrets, and Deployment Shape

### Source-of-truth repo

- This repo, `/home/architect/matrix`, is the source-of-truth definition set.
- It contains code, service units, env templates, runbooks, ops scripts, and target-state docs.

### Deployed runtime roots

Server3 now uses one shared bridge core in `/home/architect/matrix` plus per-runtime roots under different Linux users:

- Architect: `/home/architect/matrix`
- Tank: `/home/tank/tankbot` (runtime root; `/home/tank/tankbot/src` points at the shared core tree)
- Oracle bridge: `/home/oracle/oraclebot` (overlay root)
- Oracle Signal transport: `/home/oracle/signal-oracle/app`
- Govorun Python bridge: `/home/govorun/govorunbot` (overlay root)
- Govorun Node transport: `/home/govorun/whatsapp-govorun/app`

### Secrets

Secrets do not belong in git. Live secrets mainly live in:

- `/etc/default/*` for systemd-managed runtimes
- `/etc/default/oracle-signal-bridge` and `/etc/default/signal-oracle-bridge` for Oracle Signal runtime config
- `/home/architect/.config/nextcloud/ops.env` for Nextcloud ops
- `/home/govorun/whatsapp-govorun/app/.env` for WhatsApp transport

### Runtime state

Important state mostly lives under each runtime user's home directory, especially `.local/state/...` for bridge memory/session files.

## Supporting Automation You Should Remember Exists

- Runtime observer:
  - `server3-runtime-observer.service`
  - `server3-runtime-observer.timer`
  - daily health/KPI collection and Telegram reporting
- Chat-routing contract checker:
  - `server3-chat-routing-contract-check.service`
  - `server3-chat-routing-contract-check.timer`
  - keeps Govorun/Telegram routing envs aligned
- Memory maintenance and health timers for Architect:
  - `telegram-architect-memory-maintenance.timer`
  - `telegram-architect-memory-health.timer`
  - `telegram-architect-memory-restore-drill.timer`
- Monthly package maintenance:
  - `server3-monthly-apt-upgrade.service`
  - `server3-monthly-apt-upgrade.timer`
- Daily Govorun morning message:
  - `govorun-whatsapp-daily-uplift.service`
  - `govorun-whatsapp-daily-uplift.timer`

## Fast Operator Decision Guide

If you want a general assistant:
- use Architect

If you want a separate persona/profile:
- use Tank, Govorun, Oracle, AgentSmith, Trinity, Mavali ETH, or Macrorayd depending on domain

If you want a bounded operational action:
- use the keyword modes: `HA`, `Server3 Browser`, `Server3 TV`, or `Nextcloud`

If you want to know how something is installed or restarted:
- check [`ops`](../ops) first, then the matching runbook

If you want to know what should exist on the host:
- check [`infra/systemd`](../infra/systemd), [`infra/env`](../infra/env), and [`infra/system`](../infra/system)

If you want current truth before acting:
- check [`SERVER3_SUMMARY.md`](../SERVER3_SUMMARY.md)

## Bottom-Line Mental Picture

Think of Server3 as one reusable assistant engine surrounded by multiple identities and bounded tool corridors:

- Architect is the main front door.
- Tank, Oracle, Govorun, AgentSmith, Trinity, Mavali ETH, and Macrorayd are sibling runtimes built around the same core idea: isolate identity and state when it matters.
- HA, Browser Brain, TV, and Nextcloud are the deterministic side corridors.
- systemd timers, observer checks, and config contracts are the guard rails that keep the whole machine stable.
