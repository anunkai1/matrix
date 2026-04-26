# Server4 Gemma Engine

Purpose: run Gemma on Server4 Beast as a selectable Telegram bridge engine while keeping Server3 as the bot/control-plane host.

## Topology

- Server3 hosts Telegram bridge runtimes, memory, command handling, and Codex.
- Server4 Beast hosts Ollama and the local model `gemma4:26b`.
- The bridge reaches Server4 through SSH by default, calling Ollama on Server4 localhost. This avoids exposing the Ollama API on the LAN.

## Server4

- Host/IP: `192.168.0.124`
- SSH alias from Server3 service users: `server4-beast`
- Login user: `v`
- Ollama model: `gemma4:26b`
- Ollama local endpoint on Server4: `http://127.0.0.1:11434/api/chat`

Verify from Server3 as the live Architect user:

```bash
sudo -u architect ssh -o BatchMode=yes server4-beast 'ollama list'
```

Verify the bridge adapter directly:

```bash
sudo -u architect bash -lc 'cd /home/architect/matrix && python3 - <<'"'"'PY'"'"'
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path("src/telegram_bridge").resolve()))
from engine_adapter import GemmaEngineAdapter
from executor import parse_executor_output

config = SimpleNamespace(
    gemma_provider="ollama_ssh",
    gemma_model="gemma4:26b",
    gemma_ssh_host="server4-beast",
    gemma_request_timeout_seconds=60,
)
result = GemmaEngineAdapter().run(config, "Reply with exactly: gemma ok", None)
_, output = parse_executor_output(result.stdout)
print(output)
PY'
```

## Bridge Config

Defaults are intentionally usable without changing `/etc/default/telegram-architect-bridge`:

```bash
TELEGRAM_ENGINE_PLUGIN=codex
TELEGRAM_SELECTABLE_ENGINE_PLUGINS=codex,gemma
GEMMA_PROVIDER=ollama_ssh
GEMMA_MODEL=gemma4:26b
GEMMA_SSH_HOST=server4-beast
GEMMA_REQUEST_TIMEOUT_SECONDS=180
```

Use `GEMMA_PROVIDER=ollama_http` only after deliberately exposing Ollama over a controlled LAN bind/firewall rule.

## Telegram Commands

Per chat/topic:

```text
/engine status
/engine gemma
/engine codex
/engine reset
```

There is no smart routing in this mode. The service default or explicit chat selection decides the engine.

When the effective engine is `gemma`, `/engine status` also performs a short live health check and reports:

- Gemma health: `ok` or `error`
- Gemma response time
- Whether the configured model is listed by Ollama
- The current check error, or `(none)`

## Current Capability

- Gemma engine supports text requests through Ollama.
- Chat memory is still owned by the bridge memory layer.
- Gemma does not yet have a tool/action harness. Use Codex for server operations, repo edits, image handling, and high-risk actions until the harness is added.
