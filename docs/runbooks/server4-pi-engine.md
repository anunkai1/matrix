# Server4 Pi Engine

Purpose: run the Server4 Beast `pi` coding agent as a selectable Telegram bridge engine while keeping Server3 as the bot/control-plane host.

## Topology

- Server3 hosts Telegram bridge runtimes, memory, command handling, and default Codex execution.
- Server4 Beast hosts Pi and Ollama.
- The bridge reaches Server4 through SSH alias `server4-beast` and runs `pi -p` in non-interactive mode.

## Server4

- Host/IP: `192.168.0.124`
- SSH alias from Server3 service users: `server4-beast`
- Login user: `v`
- Pi binary: `/usr/local/bin/pi`
- Default provider/model: `ollama` / `gemma4:26b`

Verify from Server3:

```bash
ssh -o BatchMode=yes server4-beast 'command -v pi && pi --version && ollama list'
```

Verify the bridge adapter directly:

```bash
python3 - <<'PY'
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path("src/telegram_bridge").resolve()))
from engine_adapter import PiEngineAdapter
from executor import parse_executor_output

config = SimpleNamespace(
    pi_provider="ollama",
    pi_model="gemma4:26b",
    pi_ssh_host="server4-beast",
    pi_remote_cwd="/tmp",
    pi_tools_mode="none",
    pi_tools_allowlist="",
    pi_extra_args="",
    pi_request_timeout_seconds=60,
)
result = PiEngineAdapter().run(config, "Reply with exactly: pi ok", None)
_, output = parse_executor_output(result.stdout)
print(output)
PY
```

## Bridge Config

Defaults are usable without changing `/etc/default/telegram-architect-bridge`:

```bash
TELEGRAM_ENGINE_PLUGIN=codex
TELEGRAM_SELECTABLE_ENGINE_PLUGINS=codex,gemma,pi
PI_PROVIDER=ollama
PI_MODEL=gemma4:26b
PI_SSH_HOST=server4-beast
PI_REMOTE_CWD=/tmp
PI_TOOLS_MODE=default
PI_TOOLS_ALLOWLIST=
PI_EXTRA_ARGS=
PI_REQUEST_TIMEOUT_SECONDS=180
```

`PI_TOOLS_MODE` values:

- `default`: let Pi use its default tool policy.
- `none` / `no_tools`: pass `--no-tools`.
- `no_builtin`: pass `--no-builtin-tools`.
- `allowlist`: pass `--tools "$PI_TOOLS_ALLOWLIST"`.

## Telegram Commands

Per chat/topic:

```text
/engine status
/engine pi
/engine codex
/engine reset
```

When the effective engine is `pi`, `/engine status` performs a short live health check and reports:

- Pi health: `ok` or `error`
- Pi response time
- Pi version
- Whether the configured model is listed by Ollama
- The current check error, or `(none)`

## Current Capability

- Pi engine supports text requests through SSH-backed non-interactive Pi.
- Chat memory is still owned by the bridge memory layer.
- The bridge runs Pi with `--no-session` and `--no-context-files`; Server3 memory provides conversation context.
- Image and document-heavy turns should stay on Codex for now.
