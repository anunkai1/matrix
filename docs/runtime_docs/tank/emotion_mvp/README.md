# Emotion-Grounded LLM MVP

This is a minimal prototype for **functional emotion-like behavior** grounded in the host computer state.

## What it does

- Reads machine signals (CPU, memory, disk, load, RTT)
- Accepts external social/task signals (`task_success`, `user_feedback`)
- Updates latent emotional state each tick:
  - `valence`, `arousal`, `stress`, `confidence`, `trust_user`, `curiosity`
- Uses deterministic update rules + temporal decay

## Run

```bash
python3 -m emotion_mvp.cli --steps 5 --interval 0.5 --task-success 0.4 --user-feedback 0.2
```

Without ping probe:

```bash
python3 -m emotion_mvp.cli --steps 5 --no-ping
```

## Persistent Runtime (server-style)

Run with durable state in SQLite:

```bash
python3 -m emotion_mvp.runtime --db-path ./emotion_mvp/state.db --steps 5 --interval 1 --task-success 0.2 --user-feedback 0.1
```

On restart, state is restored from the same DB:

```bash
python3 -m emotion_mvp.runtime --db-path ./emotion_mvp/state.db --steps 2 --interval 1
```

For long-lived host loop (e.g., server3 process):

```bash
python3 -m emotion_mvp.runtime --db-path /var/lib/emotion_mvp/state.db --interval 2
```

## Next iteration ideas

- Persist state and episodic memory across sessions (SQLite)
- Add event types (permission denied, timeout, crash)
- Add policy adapter that modulates response style from state
- Build evaluation suite for stability/consistency/recovery
