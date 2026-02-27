# Change Record - 2026-02-27T23:21:08+10:00

## Objective
Optimize memory retention prune path to avoid duplicate state reconciliation work, and sync TV desktop docs/help wording to match current maximized startup behavior.

## Repo State
- Branch: `main`
- Repo: `/home/architect/matrix`

## Changes Applied (Repo-Only)
1. Memory prune optimization:
   - `src/telegram_bridge/memory_engine.py`
   - moved reconcile trigger from each individual prune helper to one combined call in `_prune_conversation`
   - behavior preserved while eliminating duplicate reconcile work when both messages and summaries are pruned in one pass
2. Regression coverage:
   - `tests/telegram_bridge/test_memory_engine.py`
   - added test: `test_force_retention_reconciles_once_when_messages_and_summaries_pruned`
3. TV wording sync:
   - `docs/server3-tv-desktop.md`
   - `ops/tv-desktop/apply_server3.sh`
   - replaced stale "fullscreen" startup wording with "maximized" wording

## Verification
- `python3 -m unittest tests/telegram_bridge/test_memory_engine.py` -> `12 tests`, `OK`
- `bash -n ops/tv-desktop/apply_server3.sh` -> pass

## Notes
- No live restart or env/systemd changes were required for this optimization/doc update.
