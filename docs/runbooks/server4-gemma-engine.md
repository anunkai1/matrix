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
GEMMA_READONLY_TOOLS_ENABLED=true
GEMMA_READONLY_ROOTS=
GEMMA_READONLY_TOOL_TIMEOUT_SECONDS=20
GEMMA_WEB_RESEARCH_ENABLED=false
```

Use `GEMMA_PROVIDER=ollama_http` only after deliberately exposing Ollama over a controlled LAN bind/firewall rule.

`GEMMA_READONLY_ROOTS` is optional. When unset, the read-only harness allows the runtime root and shared core root. File tools also block sensitive-looking path names such as token, secret, credential, password, auth, key, and session.

`GEMMA_WEB_RESEARCH_ENABLED=true` enables raw public web research mode through Server3. In that mode Gemma can request:

- `web_search(query, max_results)` using a public web search page
- `fetch_url(url, max_bytes)` for arbitrary public `http`/`https` URLs

The gateway is intentionally broad for public web research, but still blocks local, private, loopback, link-local, multicast, reserved, and unspecified network targets so web mode cannot be used to probe Server3, Server4, or LAN services.

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
- Gemma has a Server3-side read-only agent harness. The model can request:
  - `list_files(path, max_depth)`
  - `read_file(path, max_bytes)`
  - `service_status(unit)`
  - `inspect_logs(unit, lines)`
  - `run_readonly_command(command)` for a small exact allowlist such as `date`, `uptime`, `df -h`, `free -h`, selected `systemctl` list commands, `git status --short`, and `git log -1 --oneline`
  - when enabled, `web_search(query, max_results)` and `fetch_url(url, max_bytes)` for public web research
- The harness does not allow writes, deletes, restarts, installs, shell pipelines, or arbitrary commands. Use Codex for repo edits, image handling, and high-risk actions.
