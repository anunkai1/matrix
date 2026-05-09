# Server3 Mavali Loop

Purpose:
- reusable bounded end-to-end task runner for Server3 repo work
- spec-driven successor to one-off temporary loops
- suitable for small to medium campaigns where each task has clear target paths and verification

Primary files:
- runner: `ops/mavali_loop/mavali_loop.py`
- tmux launcher: `ops/mavali_loop/tmux_control.sh`
- example campaign: `ops/mavali_loop/campaigns/server3_code_review_may_2026.json`
- state root: `/var/lib/server3-mavali-loop`
- fallback state root: `.state/server3-mavali-loop`

Campaign spec shape:
- `campaign_id`
- `title`
- `summary`
- `repo_root` optional target git repo root; defaults to the `matrix` repo
- `default_max_attempts_per_task`
- `commit_prefix`
- `notify_prefix`
- `allowed_dirty_paths`
- `tasks`
- each task defines:
  - `task_id`
  - `title`
  - `summary`
  - `guidance`
  - `target_paths`
  - `verification_commands`
  - `on_success_commands`
  - `on_failure_commands`

Commands:
- run a campaign: `python3 /home/architect/matrix/ops/mavali_loop/mavali_loop.py run /abs/path/to/campaign.json`
- preferred detached launch: `bash /home/architect/matrix/ops/mavali_loop/tmux_control.sh start /abs/path/to/campaign.json`
- tmux-backed status: `bash /home/architect/matrix/ops/mavali_loop/tmux_control.sh status /abs/path/to/campaign.json`
- tmux-backed logs: `bash /home/architect/matrix/ops/mavali_loop/tmux_control.sh logs /abs/path/to/campaign.json`
- stop the detached loop: `bash /home/architect/matrix/ops/mavali_loop/tmux_control.sh stop /abs/path/to/campaign.json`
- show current status: `python3 /home/architect/matrix/ops/mavali_loop/mavali_loop.py status /abs/path/to/campaign.json`
- reset state/results: `python3 /home/architect/matrix/ops/mavali_loop/mavali_loop.py reset-state /abs/path/to/campaign.json`
- create a starter campaign from a plain task list file: `python3 /home/architect/matrix/ops/mavali_loop/mavali_loop.py create-campaign --output /abs/path/to/campaign.json --campaign-id my_campaign --title "My Campaign" --summary "..." --tasks-file /abs/path/to/tasks.txt`

Path tokens:
- `${ROOT}` resolves to the loop's own `matrix` repo root
- `${REPO_ROOT}` resolves to the campaign target repo root
- `${QA_PYTHON}` prefers `<repo_root>/.venv/server3-qa/bin/python`, then falls back to the loop repo QA venv, then `python3`

Behavior:
- processes tasks in the listed order
- does not advance until the current task is marked complete
- retries the same task within the run when an attempt fails, up to the configured attempt budget
- records explicit campaign run states: `running`, `completed`, `failed`, `paused`
- runs git status, executor, verification, restore, commit, and push against `repo_root`
- requires a clean worktree before each attempt unless the dirty paths are explicitly allowlisted
- restores changed files back to `HEAD` on failed verification or failed execution
- blocks the attempt if it touches allowlisted dirty paths
- commits and pushes a successful changed task before moving on
- supports per-task success/failure hook commands
- treats `applied` and `no_change` as complete
- writes persisted state/results per campaign so runs can resume
- writes a richer final report with task attempts and commit SHAs and, when configured, sends it to Telegram

Completion notification:
- set `TELEGRAM_BOT_TOKEN`
- set `<notify_prefix>_CHAT_ID`
- optionally set `<notify_prefix>_TOPIC_ID`
- example for the default prefix:
  - `MAVALI_LOOP_NOTIFY_CHAT_ID=-100...`
  - `MAVALI_LOOP_NOTIFY_TOPIC_ID=1234`

Future workflow:
- create a plain task list file
- generate a starter JSON campaign
- fill in task guidance, target paths, verification commands, and optional hooks
- launch it through `mavali_loop`
- check status or logs while it runs
- wait for the final completion report
