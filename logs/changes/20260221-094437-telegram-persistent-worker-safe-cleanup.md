# Change Record — 2026-02-21 09:44:37 AEST

## Summary
- Applied low-risk cleanup after persistent-worker rollout to reduce redundant state churn without changing user-visible behavior.
- Removed dead helper code made obsolete by the cleanup.

## Repo Changes
- `src/telegram_bridge/main.py`
  - Removed redundant worker-session touch in `process_prompt(...)` because session freshness is already handled in `ensure_chat_worker_session(...)`.
  - Removed now-unused `touch_worker_session(...)`.
  - Updated `set_thread_id(...)` to persist `chat_threads.json` only when the thread mapping actually changes, while preserving worker-session updates when a session exists.
  - Updated `clear_thread_id(...)` to persist `worker_sessions.json` only when a worker session exists, avoiding unnecessary writes.

## Validation
- `python3 -m py_compile src/telegram_bridge/main.py` (pass)
- `python3 src/telegram_bridge/main.py --self-test` (pass)
- `bash src/telegram_bridge/smoke_test.sh` (pass)
- targeted state-behavior check script (pass):
  - verifies `set_thread_id(...)` writes thread mapping correctly
  - verifies worker-session persistence still updates when session exists
  - verifies `clear_thread_id(...)` clears session thread id as expected

## Notes
- No live `/etc` or systemd/runtime configuration changes were made in this change set.
- This change is intentionally scoped to safe cleanup; larger architecture simplification (`chat_threads` consolidation) is deferred.
