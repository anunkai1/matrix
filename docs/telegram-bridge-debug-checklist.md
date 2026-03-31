# Telegram Bridge Debug Checklist

Use this checklist when the Telegram bridge is slow, failing, or behaving unexpectedly.

## 1) Basic service health

```bash
bash ops/telegram-bridge/status_service.sh
sudo journalctl -u telegram-architect-bridge.service -n 120 --no-pager
```

If service is not active, restart and re-check:

```bash
bash ops/telegram-bridge/restart_and_verify.sh
bash ops/telegram-bridge/status_service.sh
```

## 2) Confirm startup sequence

The bridge now emits structured JSON logs with an `event` field.
Check recent startup events:

```bash
sudo journalctl -u telegram-architect-bridge.service -n 400 --no-pager | \
  jq -r 'select(.event? == "bridge.starting" or .event? == "bridge.started" or .event? == "bridge.startup_backlog_discard" or .event? == "bridge.state_load_failed")'
```

Expected signals:
- `bridge.starting`
- `bridge.startup_backlog_discard`
- `bridge.started`

If `bridge.state_load_failed` appears, a state file was quarantined and reset.

## 3) Trace one request end-to-end

Find request lifecycle events:

```bash
sudo journalctl -u telegram-architect-bridge.service -n 800 --no-pager | \
  jq -r 'select(.event? == "bridge.update_received" or .event? == "bridge.request_accepted" or .event? == "bridge.worker_started" or .event? == "bridge.request_processing_started" or .event? == "bridge.executor_attempt" or .event? == "bridge.request_succeeded" or .event? == "bridge.request_failed" or .event? == "bridge.request_timeout" or .event? == "bridge.request_processing_finished")'
```

Filter for one chat:

```bash
CHAT_ID="<chat_id>"
sudo journalctl -u telegram-architect-bridge.service -n 1200 --no-pager | \
  jq -r --argjson chat_id "$CHAT_ID" 'select(.chat_id? == $chat_id)'
```

## 4) Use the latency benchmark harness

For stable replay benchmarking, build a frozen corpus from recent traffic and run the local harness.

Build a corpus from Architect memory:

```bash
python3 ops/telegram-bridge/build_latency_corpus.py \
  --db /home/architect/.local/state/telegram-architect-bridge/memory.sqlite3 \
  --conversation-key shared:architect:main \
  --output /tmp/architect_latency_corpus.json \
  --count 24
```

Replay it through the bridge:

```bash
python3 ops/telegram-bridge/latency_benchmark.py \
  --corpus /tmp/architect_latency_corpus.json \
  --iterations 20
```

Use this harness when you need:
- a frozen benchmark before changing code
- a baseline against a later optimization attempt
- deterministic bridge-overhead measurements without live Telegram noise

## 5) Inspect live phase timing

The bridge now emits two timing event families:

- `bridge.request_phase_timing`
  - request phases such as:
  - `handle_update_pre_worker`
  - `prepare_prompt_input`
  - `begin_memory_turn`
  - `engine_run`
  - `finalize_prompt_success`
  - `process_prompt_total`
- `bridge.executor_phase_timing`
  - deeper executor split:
  - `auth_sync`
  - `wrapper_bootstrap`
  - `codex_exec`

Request-level phase timing query:

```bash
sudo journalctl -u telegram-architect-bridge.service -n 1600 --no-pager | \
  jq -r 'select(.event? == "bridge.request_phase_timing") | {ts, chat_id, message_id, phase, duration_ms}'
```

Executor subphase query:

```bash
sudo journalctl -u telegram-architect-bridge.service -n 1600 --no-pager | \
  jq -r 'select(.event? == "bridge.executor_phase_timing") | {ts, chat_id, phase, duration_ms, mode}'
```

Interpretation rule:
- if `codex_exec` dominates, the bridge is not the main bottleneck
- if `auth_sync` or `wrapper_bootstrap` grows large, investigate local wrapper/bootstrap work
- if `finalize_prompt_success` grows large, inspect outbound Telegram/send path behavior

## 6) Understand request rejection reasons

Rejected requests emit `bridge.request_rejected` with `reason`:
- `input_too_long`
- `rate_limited`
- `worker_capacity`
- `chat_busy`

Query:

```bash
sudo journalctl -u telegram-architect-bridge.service -n 1000 --no-pager | \
  jq -r 'select(.event? == "bridge.request_rejected") | {ts, chat_id, message_id, reason}'
```

Denied non-allowlisted chats use:
- `bridge.request_denied` with reason `chat_not_allowlisted`

## 7) Debug executor behavior

Executor subprocess events:
- `bridge.executor_subprocess_start`
- `bridge.executor_subprocess_finish`
- `bridge.executor_subprocess_timeout`

Request-level executor events:
- `bridge.executor_attempt`
- `bridge.request_retry_scheduled`
- `bridge.executor_completed`
- `bridge.request_failed`
- `bridge.request_timeout`

Query:

```bash
sudo journalctl -u telegram-architect-bridge.service -n 1200 --no-pager | \
  jq -r 'select(.event? | startswith("bridge.executor") or .event? == "bridge.request_retry_scheduled" or .event? == "bridge.request_timeout" or .event? == "bridge.request_failed")'
```

## 8) Debug persistent worker lifecycle

Worker/session diagnostic events:
- `bridge.worker_evicted_for_capacity`
- `bridge.worker_reset_for_policy_change`
- `bridge.worker_capacity_rejected`
- `bridge.worker_idle_expired`

Query:

```bash
sudo journalctl -u telegram-architect-bridge.service -n 1200 --no-pager | \
  jq -r 'select(.event? == "bridge.worker_evicted_for_capacity" or .event? == "bridge.worker_reset_for_policy_change" or .event? == "bridge.worker_capacity_rejected" or .event? == "bridge.worker_idle_expired")'
```

## 9) Debug safe restart flow

Restart diagnostic events:
- `bridge.restart_requested`
- `bridge.restart_state_checked`
- `bridge.restart_script_started`
- `bridge.restart_script_failed` / `bridge.restart_script_succeeded`
- `bridge.restart_triggered_after_work`

Query:

```bash
sudo journalctl -u telegram-architect-bridge.service -n 1200 --no-pager | \
  jq -r 'select(.event? | startswith("bridge.restart"))'
```

## 10) When `jq` is unavailable

Use raw logs:

```bash
sudo journalctl -u telegram-architect-bridge.service -n 300 --no-pager
```

Or grep event names:

```bash
sudo journalctl -u telegram-architect-bridge.service -n 1200 --no-pager | \
  grep '"event": "bridge.request_failed"\|"event": "bridge.request_timeout"\|"event": "bridge.poll_error"'
```
