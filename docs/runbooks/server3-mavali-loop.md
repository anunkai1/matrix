# Server3 Mavali Loop

Canonical repo:
- `/home/architect/mavali-loop`

Compatibility wrappers remain in `matrix` under `ops/mavali_loop`, but the standalone repo is now the source of truth.

Purpose:
- reusable bounded end-to-end task runner for Server3 repo work
- spec-driven successor to one-off temporary loops
- suitable for small to medium campaigns where each task has clear target paths and verification

Primary files:
- runner: `/home/architect/mavali-loop/src/mavali_loop/runner.py`
- executor: `/home/architect/mavali-loop/scripts/codex_exec.sh`
- tmux launcher: `/home/architect/mavali-loop/scripts/tmux_control.sh`
- example campaign: `/home/architect/mavali-loop/campaigns/examples/server3_code_review_may_2026.json`
- state root: `/var/lib/mavali-loop`
- fallback state root: `/home/architect/mavali-loop/.state/mavali-loop`

Campaign spec shape:
- `campaign_id`
- `title`
- `summary`
- `repo_root` optional target git repo root; defaults to the `matrix` repo
- `default_max_attempts_per_task`
- `commit_prefix`
- `notify_prefix`
- `allowed_dirty_paths`
- `completion_review` optional end-of-campaign review gate
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

Optional `completion_review` shape:
- `guidance`
- `max_followup_campaigns`

Behavior:
- when all listed tasks complete, the runner can do one more Codex review pass against the campaign's real end goal
- that review must return either `ready` or a bounded follow-up campaign
- if a follow-up campaign is returned, the runner writes it next to the current campaign JSON and continues automatically
- use this only when the campaign needs a real end-goal gate, not for routine one-shot task bundles

Commands:
- default detached launch: `bash /home/architect/mavali-loop/scripts/tmux_control.sh /abs/path/to/campaign.json`
- explicit detached launch: `bash /home/architect/mavali-loop/scripts/tmux_control.sh start /abs/path/to/campaign.json`
- tmux-backed status: `bash /home/architect/mavali-loop/scripts/tmux_control.sh status /abs/path/to/campaign.json`
- tmux-backed logs: `bash /home/architect/mavali-loop/scripts/tmux_control.sh logs /abs/path/to/campaign.json`
- stop the detached loop: `bash /home/architect/mavali-loop/scripts/tmux_control.sh stop /abs/path/to/campaign.json`
- show current status: `PYTHONPATH=/home/architect/mavali-loop/src python3 -m mavali_loop status /abs/path/to/campaign.json`
- reset state/results: `PYTHONPATH=/home/architect/mavali-loop/src python3 -m mavali_loop reset-state /abs/path/to/campaign.json`
- create a starter campaign from a plain task list file: `PYTHONPATH=/home/architect/mavali-loop/src python3 -m mavali_loop create-campaign --output /abs/path/to/campaign.json --campaign-id my_campaign --title "My Campaign" --summary "..." --tasks-file /abs/path/to/tasks.txt`
- foreground debug run only: `PYTHONPATH=/home/architect/mavali-loop/src python3 -m mavali_loop run /abs/path/to/campaign.json`

Path tokens:
- `${ROOT}` resolves to the standalone loop repo root
- `${REPO_ROOT}` resolves to the campaign target repo root
- `${QA_PYTHON}` prefers `<repo_root>/.venv/server3-qa/bin/python`, then falls back to the loop repo QA venv, then `python3`

Execution model:
- the default executor now lives in the standalone repo and runs `codex exec` directly from the campaign `repo_root`
- external-repo campaigns no longer depend on the shared Telegram bridge executor wrapper

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
- tmux is the operational default for launches because foreground runs stop when the caller session is torn down

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
- launch it through `tmux_control.sh` by default
- check status or logs while it runs
- wait for the final completion report
