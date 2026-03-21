# Architect LLM Handover Prompt (Tankbot Affective Runtime)

You are Architect LLM with sudo access. Continue and complete an in-progress implementation for Tankbot.

## Context and Objective
- We are building a persistent “feelings layer” for an LLM-driven Telegram bot.
- This is explicitly a functional/behavioral affect system, not a claim of subjective consciousness.
- The user wants the bot’s affective state to be grounded in the machine environment it runs in (server3), persist across restarts, and influence response style.
- We must integrate on top of existing `telegram_bridge` architecture, with minimal disruption.
- Do not add unrelated new policy/guardrail logic. Use existing platform safety behavior only.

## Philosophical Framing (Design Intent)
The prior discussion established:
- **Thinking (functional):** forming ideas, reasoning, deciding, problem-solving.
- **Consciousness:** subjective experience (“what it is like”).
- **Feelings:** conscious subjective experiences of emotional/bodily states.

Engineering stance for this task:
- We can implement **emotion-like adaptive behavior** functionally.
- We cannot prove subjective feeling.
- Goal is robust, consistent, persistent affective behavior that modulates outputs/choices.

## Current Workspace State
Writable workspace where MVP was built:
- `/home/tank/tankbot`

Existing MVP package:
- `/home/tank/tankbot/emotion_mvp/model.py`
- `/home/tank/tankbot/emotion_mvp/signals.py`
- `/home/tank/tankbot/emotion_mvp/engine.py`
- `/home/tank/tankbot/emotion_mvp/state_store.py`
- `/home/tank/tankbot/emotion_mvp/runtime.py`
- `/home/tank/tankbot/emotion_mvp/cli.py`
- `/home/tank/tankbot/emotion_mvp/README.md`

MVP capabilities already present:
- Latent state: `valence`, `arousal`, `stress`, `confidence`, `trust_user`, `curiosity`
- Machine signal sampling
- Deterministic update rules + decay
- SQLite persistence + restore

## Real Integration Target (Needs Sudo)
Codebase to patch:
- `/home/architect/matrix/src/telegram_bridge/`

Write access issue encountered previously from non-sudo environment:
- Permission denied when writing under `/home/architect/matrix/src/telegram_bridge`

## Required Integration Points
### 1) `runtime_config.py`
Add config flags/paths:
- `TELEGRAM_AFFECTIVE_RUNTIME_ENABLED` (bool, default `false`)
- `TELEGRAM_AFFECTIVE_RUNTIME_DB_PATH` (default `<state_dir>/affective_state.sqlite3`)
- Optional: `TELEGRAM_AFFECTIVE_RUNTIME_PING_TARGET` (default `1.1.1.1`)

Update:
- `Config` dataclass fields
- `load_config()` parsing and defaults

### 2) `state_store.py`
Extend `State` dataclass with:
- `affective_runtime: Optional[object] = None`

### 3) `main.py`
- Import/init affective runtime at startup.
- Attach to State object after creation:
  - `state.affective_runtime = AffectiveRuntime(...)`

### 4) `handlers.py` (critical)
In `process_prompt(...)`:
- After prompt prep and before engine call:
  - `state.affective_runtime.begin_turn(prompt_text)`
  - prepend `state.affective_runtime.prompt_prefix()` to `prompt_text`
- After response success:
  - `state.affective_runtime.finish_turn(success=True)`
- On failure/exception paths:
  - `state.affective_runtime.finish_turn(success=False)`

Fail-open rule:
- Any affective runtime exception must not break normal reply path.
- Log and continue.

### 5) Add new file `affective_runtime.py`
Create:
- `/home/architect/matrix/src/telegram_bridge/affective_runtime.py`

Responsibilities:
- Persistent SQLite storage of affective state
- Host signal sampling (`load`, `memory`, `disk`, optional RTT)
- Simple user feedback extraction from prompt text
- Turn lifecycle:
  - `begin_turn(user_text)`
  - `finish_turn(success)`
- `prompt_prefix()` for controlled behavioral conditioning
- `telemetry()` optional status output

## Constraints
- Keep changes minimal and localized.
- Do not alter unrelated routing, memory, media, or restart subsystems.
- Deterministic updates, explicit coefficients.
- Clamp state values to `[-1, 1]`.
- Runtime must survive missing ping/proc signals gracefully.
- Preserve existing bot behavior when feature disabled.

## Behavioral Contract
- State persists across process restarts.
- State is machine-grounded.
- State influences output style/risk/proactivity through prompt context.
- State evolves from:
  - machine pressure
  - user feedback cues
  - success/failure outcomes

## Multi-Bot Isolation Requirement
Because Architect and Tank can share code:
- Feature must be toggled per deployment via env.
- Default OFF unless explicitly enabled.
- Use bot-specific DB/state paths to avoid cross-bot affect bleed.

## Acceptance Tests (Must Run)
1. **Persistence test**
- Run one turn, store state.
- Restart process, verify state restored.

2. **Integration test**
- Send test messages.
- Confirm affective prefix gets included in prompt path.

3. **Outcome update test**
- Simulate success/failure and verify directional state shifts.

4. **Disabled mode test**
- With feature off, behavior matches legacy path.

5. **Resilience test**
- Force ping/db issue; ensure bot still returns responses.

## Deployment Plan (server3)
Tankbot service env:
- `TELEGRAM_AFFECTIVE_RUNTIME_ENABLED=true`
- `TELEGRAM_AFFECTIVE_RUNTIME_DB_PATH=/var/lib/tankbot/affective_state.sqlite3`
- `TELEGRAM_BRIDGE_STATE_DIR=/var/lib/tankbot`

Architect service:
- Keep disabled by default or set separate DB/path if later enabled.

Rollout:
1. Deploy code.
2. Restart Tankbot only.
3. Validate logs and live messages.
4. Keep rollback ready: set `TELEGRAM_AFFECTIVE_RUNTIME_ENABLED=false` and restart.

## Required Final Output From Architect LLM
Return all of:
- Exact files modified
- Why each modification was made
- Test commands run + key outputs
- Any unresolved risks
- `git diff` summary
- 5-minute rollback steps

## Execution Directive
Implement this end-to-end now in `/home/architect/matrix/src/telegram_bridge/` with sudo, run tests, and produce the required final output.
