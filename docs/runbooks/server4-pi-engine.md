# Pi Engine With Server4 Ollama

Purpose: run Pi as a selectable Telegram bridge engine without changing the chatbot's working directory or instruction discovery.

## Topology

- Server3 hosts Telegram bridge runtimes, memory, command handling, runtime roots, and Pi execution.
- Server4 Beast hosts Ollama and the heavy local models.
- In true engine-swap mode, Pi runs on Server3 in the same runtime root Codex uses, such as `/home/tank/tankbot`.
- Pi reaches Server4 Ollama through an SSH tunnel from Server3 localhost to Server4 localhost.

This keeps these invariant across `codex` and `pi`:

- chatbot working directory
- `AGENTS.md` / context-file discovery
- bridge memory wrapper
- runtime state paths

## Server3 Pi Install

```bash
command -v pi || sudo npm install -g @mariozechner/pi-coding-agent@0.70.2
pi --version
```

Each runtime user needs a Pi model config. For Tank, Pi uses `/home/tank/.pi/agent/models.json` with an OpenAI-compatible Ollama endpoint:

```json
{
  "providers": {
    "ollama": {
      "api": "openai-completions",
      "apiKey": "ollama",
      "baseUrl": "http://127.0.0.1:11435/v1",
      "models": [
        {
          "_launch": true,
          "contextWindow": 262144,
          "id": "qwen3-coder:30b",
          "input": ["text"]
        },
        {
          "_launch": true,
          "contextWindow": 262144,
          "id": "gemma4:26b",
          "input": ["text", "image"],
          "reasoning": true
        }
      ]
    }
  }
}
```

## Server4

- Host/IP: `192.168.0.124`
- SSH alias from Server3 service users: `server4-beast`
- Ollama local endpoint on Server4: `http://127.0.0.1:11434`
- Default model: `qwen3-coder:30b`

Verify from Server3 as the runtime user:

```bash
sudo -u tank ssh -o BatchMode=yes server4-beast 'ollama list'
```

## Bridge Config

Generic defaults:

```bash
TELEGRAM_ENGINE_PLUGIN=codex
TELEGRAM_SELECTABLE_ENGINE_PLUGINS=codex,gemma,pi
PI_PROVIDER=ollama
PI_MODEL=qwen3-coder:30b
PI_RUNNER=ssh
PI_SSH_HOST=server4-beast
PI_SESSION_MODE=none
PI_TOOLS_MODE=default
PI_REQUEST_TIMEOUT_SECONDS=180
```

True engine-swap mode for Tank:

```bash
PI_RUNNER=local
PI_LOCAL_CWD=/home/tank/tankbot
PI_SESSION_MODE=none
PI_OLLAMA_TUNNEL_LOCAL_PORT=11435
PI_OLLAMA_TUNNEL_REMOTE_HOST=127.0.0.1
PI_OLLAMA_TUNNEL_REMOTE_PORT=11434
```

`PI_TOOLS_MODE` values:

- `default`: let Pi use its default tool policy.
- `none` / `no_tools`: pass `--no-tools`.
- `no_builtin`: pass `--no-builtin-tools`.
- `allowlist`: pass `--tools "$PI_TOOLS_ALLOWLIST"`.

`PI_SESSION_MODE` values:

- `none`: pass `--no-session`; bridge memory owns chat continuity.
- `telegram_scope`: use native Pi sessions keyed by Telegram scope under `PI_SESSION_DIR` or `~/.pi/agent/telegram-sessions`.

## Verify Local Tank Pi

```bash
sudo -u tank bash -lc 'cd /home/tank/tankbot && python3 - <<'"'"'PY'"'"'
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path("src/telegram_bridge").resolve()))
from engine_adapter import PiEngineAdapter
from executor import parse_executor_output

config = SimpleNamespace(
    pi_provider="ollama",
    pi_model="qwen3-coder:30b",
    pi_runner="local",
    pi_bin="pi",
    pi_ssh_host="server4-beast",
    pi_local_cwd="/home/tank/tankbot",
    pi_remote_cwd="/tmp",
    pi_tools_mode="none",
    pi_tools_allowlist="",
    pi_extra_args="",
    pi_ollama_tunnel_enabled=True,
    pi_ollama_tunnel_local_port=11435,
    pi_ollama_tunnel_remote_host="127.0.0.1",
    pi_ollama_tunnel_remote_port=11434,
    pi_request_timeout_seconds=90,
)
result = PiEngineAdapter().run(config, "Who are you, and what is your working directory?", None)
_, output = parse_executor_output(result.stdout)
print(output)
PY'
```

Expected shape:

```text
I am Tank, and my working directory is /home/tank/tankbot.
```

## Telegram Commands

Per chat/topic:

```text
/engine status
/engine pi
/engine codex
/engine reset
```

## Current Capability

- Pi supports text requests through local non-interactive Pi on Server3.
- Server4 supplies only the model backend.
- Chat memory is still owned by the bridge memory layer.
- Pi runs with `--no-session` by default; Server3 bridge memory provides conversation context.
- Optional native Pi sessions are available with `PI_SESSION_MODE=telegram_scope`; this maps each Telegram scope key to a stable JSONL file under `PI_SESSION_DIR` or `~/.pi/agent/telegram-sessions`.
- Image and document-heavy turns should stay on Codex for now.
