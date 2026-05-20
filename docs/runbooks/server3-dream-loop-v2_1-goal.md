# Server3 Dream Loop V2.1 Goal Brief

Use this file as the single implementation brief when the dream loop should add bounded git commit/push automation after `v2`.

## Goal

Implement dream-loop spec `v2.1` exactly to the current boundary defined in [docs/specs/server3-dream-loop.md](/home/architect/matrix/docs/specs/server3-dream-loop.md).

`v2.1` is complete only when all of the following are true:

- the dream loop can auto-commit safe repo-managed changes created by the current run
- the dream loop can auto-push immediately after a successful auto-commit
- the loop stages only bounded managed-output files from the current run
- the loop never commits unrelated pre-existing dirty files
- the loop never commits unrelated pre-existing staged files
- dry-run mode never commits or pushes
- run state records commit/push decisions and outcomes
- the rendered report shows the git automation outcome
- tests cover success, no-change skip, dirty-file skip, staged-change skip, and push-failure behavior

## Boundaries

Do not add any of the following unless the spec changes first:

- broad `git add .`
- repo-wide cleanup commits
- automatic pulls, rebases, or force pushes
- conflict resolution logic
- sweeping up user edits that existed before the dream-loop run
- commit/push behavior for `latest_run_state.json` or `latest_report.md` in the same run

## Implementation Standard

- detect pre-existing staged repo state before auto-commit
- detect pre-existing dirty state for candidate managed files before auto-commit
- if safe files remain, stage and commit only those files
- if push fails, keep the truth/health outputs and report the failure clearly
