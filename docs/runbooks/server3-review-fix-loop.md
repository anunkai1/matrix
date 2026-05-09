# Server3 Review Fix Loop

Purpose:
- temporary autonomous loop for the seven code-review / architecture issues identified in May 2026
- separate from Ralph
- intended to be launched manually, run until the seven issues are complete, then be deleted

Primary files:
- loop script: `ops/review_fix_loop/review_fix_loop.py`
- tmux launcher: `ops/review_fix_loop/tmux_control.sh`
- state: `/var/lib/server3-review-fix-loop/state.json`
- results: `/var/lib/server3-review-fix-loop/results.jsonl`

Commands:
- run the full loop: `python3 /home/architect/matrix/ops/review_fix_loop/review_fix_loop.py run`
- preferred detached launch: `bash /home/architect/matrix/ops/review_fix_loop/tmux_control.sh start`
- tmux-backed status: `bash /home/architect/matrix/ops/review_fix_loop/tmux_control.sh status`
- tmux-backed logs: `bash /home/architect/matrix/ops/review_fix_loop/tmux_control.sh logs`
- stop the detached loop: `bash /home/architect/matrix/ops/review_fix_loop/tmux_control.sh stop`
- show current status: `python3 /home/architect/matrix/ops/review_fix_loop/review_fix_loop.py status`
- reset loop state/results: `python3 /home/architect/matrix/ops/review_fix_loop/review_fix_loop.py reset-state`
- limit retries per issue for one invocation: `python3 /home/architect/matrix/ops/review_fix_loop/review_fix_loop.py run --max-attempts-per-issue 8`

Behavior:
- processes the seven issues in a fixed order
- does not advance to the next issue until the current issue is marked complete
- retries the same issue within the same run when an attempt fails
- requires a clean worktree before each attempt
- if an attempt changes files and then fails verification, the loop restores those files back to `HEAD` before retrying
- on success, the loop commits and pushes that issue before moving to the next one
- `applied` and `no_change` both count as complete; `no_change` means the loop judged the issue already fixed and verification passed
- when launching from chat-bound or other interactive tooling, prefer the tmux wrapper so the loop survives caller teardown

QA:
- targeted tests: `./.venv/server3-qa/bin/python3 -m pytest tests/review_fix_loop/test_review_fix_loop.py -q`
- repo QA path includes this loop through `bash ops/dev/run_python_checks.sh --skip-smoke`

Removal intent:
- once all seven issues are completed and verified well, remove:
  - `ops/review_fix_loop/review_fix_loop.py`
  - `ops/review_fix_loop/tmux_control.sh`
  - `tests/review_fix_loop/test_review_fix_loop.py`
  - this runbook
  - any temporary state/results files under `/var/lib/server3-review-fix-loop`
