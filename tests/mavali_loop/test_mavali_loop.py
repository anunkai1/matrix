import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from unittest import mock

MODULE_PATH = Path(__file__).resolve().parents[2] / "ops" / "mavali_loop" / "mavali_loop.py"
SPEC = spec_from_file_location("mavali_loop", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
mavali_loop = module_from_spec(SPEC)
sys.modules[SPEC.name] = mavali_loop
SPEC.loader.exec_module(mavali_loop)


class MavaliLoopTests(unittest.TestCase):
    def build_spec(self) -> mavali_loop.CampaignSpec:
        return mavali_loop.CampaignSpec(
            campaign_id="example_campaign",
            title="Example Campaign",
            summary="Example summary",
            tasks=[
                mavali_loop.CampaignTask(
                    task_id="task-one",
                    title="Task One",
                    summary="one",
                    guidance="fix one",
                    target_paths=["a.py"],
                    verification_commands=[["true"]],
                    on_success_commands=[],
                    on_failure_commands=[],
                ),
                mavali_loop.CampaignTask(
                    task_id="task-two",
                    title="Task Two",
                    summary="two",
                    guidance="fix two",
                    target_paths=["b.py"],
                    verification_commands=[["true"]],
                    on_success_commands=[],
                    on_failure_commands=[],
                ),
            ],
        )

    def test_resolve_command_tokens_supports_external_repo_root(self) -> None:
        spec = mavali_loop.CampaignSpec(
            campaign_id="external_campaign",
            title="External Campaign",
            summary="external",
            repo_root="/srv/example/repo",
            tasks=[],
        )

        resolved = mavali_loop.resolve_command_tokens(
            spec,
            ["bash", "${REPO_ROOT}/script.sh", "${ROOT}/runner.sh"],
        )

        self.assertEqual(
            resolved,
            ["bash", "/srv/example/repo/script.sh", f"{mavali_loop.ROOT}/runner.sh"],
        )

    def test_build_prompt_includes_recent_history(self) -> None:
        spec = self.build_spec()
        task = spec.tasks[0]
        task_state = {
            "history": [
                {
                    "status": "qa_failed",
                    "summary": "tests failed",
                    "changed_files": ["src/example.py"],
                }
            ]
        }

        prompt = mavali_loop.build_prompt(spec, task, task_state, 2, 1)

        self.assertIn(spec.campaign_id, prompt)
        self.assertIn(task.task_id, prompt)
        self.assertIn("tests failed", prompt)
        self.assertIn("src/example.py", prompt)
        self.assertIn(f"Repository root: {mavali_loop.campaign_repo_root(spec)}", prompt)

    def test_executor_command_defaults_to_local_mavali_wrapper(self) -> None:
        spec = self.build_spec()

        command = mavali_loop.executor_command(spec)

        self.assertEqual(command[1:], ["new"])
        self.assertTrue(command[0].endswith("/mavali-loop/scripts/codex_exec.sh"))

    def test_git_status_entries_ignores_internal_state_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            campaign_dir = repo_root / ".state" / "mavali-loop" / "example"
            campaign_dir.mkdir(parents=True)
            paths = mavali_loop.LoopPaths(
                state_root=repo_root / ".state" / "mavali-loop",
                campaign_dir=campaign_dir,
                state_path=campaign_dir / "state.json",
                results_path=campaign_dir / "results.jsonl",
                report_path=campaign_dir / "report.txt",
                log_path=campaign_dir / "tmux.log",
            )
            output = "?? .state/mavali-loop/example/state.json\n M src/example.py\n"
            proc = mock.Mock(returncode=0, stdout=output)
            with mock.patch.object(mavali_loop, "ROOT", repo_root), mock.patch.object(
                mavali_loop,
                "run_command_capture",
                return_value=proc,
            ):
                spec = mavali_loop.CampaignSpec(
                    campaign_id="example_campaign",
                    title="Example Campaign",
                    summary="Example summary",
                    repo_root=str(repo_root),
                    tasks=[],
                )
                entries = mavali_loop.git_status_entries(spec, paths)

        self.assertEqual(entries, {"src/example.py": " M"})

    def test_update_task_state_marks_success_complete(self) -> None:
        task_state = {"status": "pending", "attempts": 0, "history": []}
        result = mavali_loop.AttemptResult(
            observed_at_utc="2026-05-09T00:00:00+00:00",
            task_id="task-one",
            attempt=1,
            status="applied",
            summary="done",
            codex_returncode=0,
            codex_stdout="",
            codex_stderr="",
            verification_results=[],
            changed_files=["a.py"],
            reverted_files=[],
            git_head_before="a",
            git_head_after="b",
            commit_message="msg",
            committed_sha="abc123",
            push_succeeded=True,
            push_stdout="",
            push_stderr="",
        )

        mavali_loop.update_task_state(task_state, result)

        self.assertEqual(task_state["status"], "completed")
        self.assertEqual(task_state["attempts"], 1)
        self.assertEqual(task_state["history"][0]["status"], "applied")

    def test_run_loop_retries_task_until_completed(self) -> None:
        spec = self.build_spec()
        t0 = datetime(2026, 5, 9, 0, 0, tzinfo=timezone.utc)
        blocked = mavali_loop.AttemptResult(
            observed_at_utc=t0.isoformat(),
            task_id="task-one",
            attempt=1,
            status="qa_failed",
            summary="retry",
            codex_returncode=0,
            codex_stdout="",
            codex_stderr="",
            verification_results=[],
            changed_files=["a.py"],
            reverted_files=["a.py"],
            git_head_before="a",
            git_head_after="a",
        )
        done_one = mavali_loop.AttemptResult(
            observed_at_utc=t0.isoformat(),
            task_id="task-one",
            attempt=2,
            status="applied",
            summary="done one",
            codex_returncode=0,
            codex_stdout="",
            codex_stderr="",
            verification_results=[],
            changed_files=["a.py"],
            reverted_files=[],
            git_head_before="a",
            git_head_after="b",
            commit_message="msg1",
            committed_sha="sha1",
            push_succeeded=True,
            push_stdout="",
            push_stderr="",
        )
        done_two = mavali_loop.AttemptResult(
            observed_at_utc=t0.isoformat(),
            task_id="task-two",
            attempt=1,
            status="no_change",
            summary="done two",
            codex_returncode=0,
            codex_stdout="",
            codex_stderr="",
            verification_results=[],
            changed_files=[],
            reverted_files=[],
            git_head_before="b",
            git_head_after="b",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            paths = mavali_loop.LoopPaths(
                state_root=tmpdir_path,
                campaign_dir=tmpdir_path / "example_campaign",
                state_path=tmpdir_path / "example_campaign" / "state.json",
                results_path=tmpdir_path / "example_campaign" / "results.jsonl",
                report_path=tmpdir_path / "example_campaign" / "report.txt",
                log_path=tmpdir_path / "example_campaign" / "tmux.log",
            )
            paths.campaign_dir.mkdir(parents=True)
            with mock.patch.object(mavali_loop, "state_paths_for_campaign", return_value=paths), mock.patch.object(
                mavali_loop,
                "run_task_attempt",
                side_effect=[blocked, done_one, done_two],
            ) as run_task_attempt, mock.patch.object(
                mavali_loop,
                "now_utc",
                return_value=t0,
            ), mock.patch.object(
                mavali_loop,
                "send_telegram_message",
                return_value=False,
            ), mock.patch("builtins.print"):
                rc = mavali_loop.run_loop(spec, max_attempts_per_task=3)

            state = json.loads(paths.state_path.read_text(encoding="utf-8"))
            self.assertEqual(rc, 0)
            self.assertEqual(run_task_attempt.call_count, 3)
            self.assertEqual(state["tasks"]["task-one"]["status"], "completed")
            self.assertEqual(state["tasks"]["task-one"]["attempts"], 2)
            self.assertEqual(state["tasks"]["task-two"]["status"], "completed")

    def test_completion_report_is_written_and_notified_once(self) -> None:
        spec = self.build_spec()
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            paths = mavali_loop.LoopPaths(
                state_root=tmpdir_path,
                campaign_dir=tmpdir_path / "example_campaign",
                state_path=tmpdir_path / "example_campaign" / "state.json",
                results_path=tmpdir_path / "example_campaign" / "results.jsonl",
                report_path=tmpdir_path / "example_campaign" / "report.txt",
                log_path=tmpdir_path / "example_campaign" / "tmux.log",
            )
            paths.campaign_dir.mkdir(parents=True)
            state = {
                "campaign_id": spec.campaign_id,
                "tasks": {
                    "task-one": {"status": "completed", "attempts": 1, "last_summary": "done"},
                    "task-two": {"status": "completed", "attempts": 1, "last_summary": "done"},
                },
            }
            with mock.patch.object(mavali_loop, "send_telegram_message", return_value=True) as send_message:
                mavali_loop.maybe_send_completion_report(spec, paths, state, exit_code=0)
                mavali_loop.maybe_send_completion_report(spec, paths, state, exit_code=0)

            self.assertTrue(paths.report_path.exists())
            self.assertEqual(send_message.call_count, 1)

    def test_recover_abandoned_attempt_preserves_allowlisted_dirty_paths(self) -> None:
        spec = mavali_loop.CampaignSpec(
            campaign_id="allowlist_campaign",
            title="Allowlist Campaign",
            summary="allowlist",
            tasks=[
                mavali_loop.CampaignTask(
                    task_id="task-one",
                    title="Task One",
                    summary="one",
                    guidance="fix one",
                    target_paths=["src/app.py"],
                    verification_commands=[["true"]],
                    on_success_commands=[],
                    on_failure_commands=[],
                )
            ],
            allowed_dirty_paths=["src/user_dirty.py"],
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            paths = mavali_loop.LoopPaths(
                state_root=tmpdir_path,
                campaign_dir=tmpdir_path / "allowlist_campaign",
                state_path=tmpdir_path / "allowlist_campaign" / "state.json",
                results_path=tmpdir_path / "allowlist_campaign" / "results.jsonl",
                report_path=tmpdir_path / "allowlist_campaign" / "report.txt",
                log_path=tmpdir_path / "allowlist_campaign" / "tmux.log",
            )
            paths.campaign_dir.mkdir(parents=True)
            state = {
                "tasks": {},
                "active_attempt": {
                    "task_id": "task-one",
                    "attempt": 1,
                    "git_head_before": "abc123",
                },
            }
            dirty_entries = {
                "src/user_dirty.py": " M",
                "src/generated.py": " M",
            }
            with mock.patch.object(mavali_loop, "git_status_entries", return_value=dirty_entries), mock.patch.object(
                mavali_loop,
                "restore_paths",
                return_value=["src/generated.py"],
            ) as restore_paths, mock.patch.object(
                mavali_loop,
                "git_head",
                return_value="abc123",
            ), mock.patch.object(
                mavali_loop,
                "now_utc",
                return_value=datetime(2026, 5, 9, 0, 0, tzinfo=timezone.utc),
            ):
                result = mavali_loop.recover_abandoned_attempt(
                    spec,
                    paths,
                    state,
                    reason="Attempt crashed before completion; restored leftover changes.",
                )

        assert result is not None
        restore_paths.assert_called_once_with(spec, ["src/generated.py"])
        self.assertEqual(result.changed_files, ["src/generated.py"])
        self.assertEqual(result.reverted_files, ["src/generated.py"])
        self.assertIn("Preserved allowlisted dirty paths: src/user_dirty.py.", result.summary)

    def test_load_state_migrates_legacy_review_loop_state(self) -> None:
        spec = mavali_loop.CampaignSpec(
            campaign_id="legacy_campaign",
            title="Legacy Campaign",
            summary="legacy",
            tasks=[
                mavali_loop.CampaignTask(
                    task_id="task-one",
                    title="Task One",
                    summary="one",
                    guidance="fix one",
                    target_paths=["a.py"],
                    verification_commands=[["true"]],
                    on_success_commands=[],
                    on_failure_commands=[],
                )
            ],
            legacy_state_dirs=["${ROOT}/legacy-state"],
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            legacy_dir = repo_root / "legacy-state"
            legacy_dir.mkdir(parents=True)
            (legacy_dir / "state.json").write_text(
                json.dumps(
                    {
                        "campaign_id": "legacy_campaign",
                        "issues": {
                            "task-one": {
                                "status": "completed",
                                "attempts": 1,
                                "history": [],
                            }
                        },
                        "active_attempt": {"issue_id": "task-one", "attempt": 1},
                    }
                ),
                encoding="utf-8",
            )
            (legacy_dir / "results.jsonl").write_text(
                json.dumps({"issue_id": "task-one", "status": "applied"}) + "\n",
                encoding="utf-8",
            )
            paths = mavali_loop.LoopPaths(
                state_root=repo_root / ".state",
                campaign_dir=repo_root / ".state" / "legacy-campaign",
                state_path=repo_root / ".state" / "legacy-campaign" / "state.json",
                results_path=repo_root / ".state" / "legacy-campaign" / "results.jsonl",
                report_path=repo_root / ".state" / "legacy-campaign" / "report.txt",
                log_path=repo_root / ".state" / "legacy-campaign" / "tmux.log",
            )
            paths.campaign_dir.mkdir(parents=True)
            with mock.patch.object(mavali_loop, "ROOT", repo_root):
                state = mavali_loop.load_state(spec, paths)

            self.assertEqual(state["tasks"]["task-one"]["status"], "completed")
            self.assertEqual(state["active_attempt"]["task_id"], "task-one")
            migrated_result = json.loads(paths.results_path.read_text(encoding="utf-8").strip())
            self.assertEqual(migrated_result["task_id"], "task-one")

    def test_load_campaign_spec_rejects_duplicate_task_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            spec_path = Path(tmpdir) / "campaign.json"
            spec_path.write_text(
                json.dumps(
                    {
                        "campaign_id": "dup-campaign",
                        "title": "Duplicate Campaign",
                        "tasks": [
                            {
                                "task_id": "task-one",
                                "title": "Task One",
                                "summary": "one",
                                "verification_commands": [["true"]],
                            },
                            {
                                "task_id": "task-one",
                                "title": "Task One Again",
                                "summary": "two",
                                "verification_commands": [["true"]],
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "task_id values must be unique"):
                mavali_loop.load_campaign_spec(str(spec_path))

    def test_load_campaign_spec_resolves_repo_root_token(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            loop_root = Path(tmpdir) / "loop-root"
            loop_root.mkdir()
            external_repo = Path(tmpdir) / "external-repo"
            external_repo.mkdir()
            spec_path = Path(tmpdir) / "campaign.json"
            spec_path.write_text(
                json.dumps(
                    {
                        "campaign_id": "external-campaign",
                        "title": "External Campaign",
                        "repo_root": str(external_repo),
                        "tasks": [
                            {
                                "task_id": "task-one",
                                "title": "Task One",
                                "summary": "one",
                                "verification_commands": [["${QA_PYTHON}", "-V"], ["echo", "${REPO_ROOT}"]],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            with mock.patch.object(mavali_loop, "ROOT", loop_root):
                spec = mavali_loop.load_campaign_spec(str(spec_path))

            self.assertEqual(spec.repo_root, str(external_repo.resolve()))
            self.assertEqual(
                mavali_loop.resolve_command_tokens(spec, ["echo", "${REPO_ROOT}"]),
                ["echo", str(external_repo.resolve())],
            )

    def test_parse_task_lines_accepts_numbered_and_bulleted_input(self) -> None:
        lines = mavali_loop.parse_task_lines(
            "1. first task\n"
            "2) second task\n"
            "- third task\n"
            "* fourth task\n"
        )

        self.assertEqual(lines, ["first task", "second task", "third task", "fourth task"])

    def test_create_campaign_spec_writes_placeholder_campaign(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "campaign.json"
            rc = mavali_loop.create_campaign_spec(
                output_path=str(output_path),
                campaign_id="new_campaign",
                title="New Campaign",
                summary="summary",
                task_lines=["Task One", "Task One"],
            )

            payload = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(rc, 0)
            self.assertEqual(payload["campaign_id"], "new_campaign")
            self.assertEqual(payload["tasks"][0]["task_id"], "task-one")
            self.assertEqual(payload["tasks"][1]["task_id"], "task-one-2")
            self.assertEqual(payload["tasks"][0]["verification_commands"], [["true"]])

    def test_load_campaign_spec_parses_completion_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            spec_path = Path(tmpdir) / "campaign.json"
            spec_path.write_text(
                json.dumps(
                    {
                        "campaign_id": "review-campaign",
                        "title": "Review Campaign",
                        "summary": "summary",
                        "completion_review": {
                            "guidance": "Decide whether to stop or create a follow-up.",
                            "max_followup_campaigns": 2,
                        },
                        "tasks": [
                            {
                                "task_id": "task-one",
                                "title": "Task One",
                                "summary": "one",
                                "verification_commands": [["true"]],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            spec = mavali_loop.load_campaign_spec(str(spec_path))

            assert spec.completion_review is not None
            self.assertEqual(spec.completion_review.guidance, "Decide whether to stop or create a follow-up.")
            self.assertEqual(spec.completion_review.max_followup_campaigns, 2)
            self.assertEqual(spec.source_path, str(spec_path.resolve()))

    def test_extract_final_output_text_prefers_last_agent_message(self) -> None:
        stream = "\n".join(
            [
                json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "first"}}),
                json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "second"}}),
            ]
        )

        result = mavali_loop.extract_final_output_text(stream)

        self.assertEqual(result, "second")

    def test_build_followup_campaign_spec_inherits_parent_contract(self) -> None:
        parent = mavali_loop.CampaignSpec(
            campaign_id="parent_campaign",
            title="Parent Campaign",
            summary="parent summary",
            repo_root="/tmp/repo",
            tasks=[
                mavali_loop.CampaignTask(
                    task_id="task-one",
                    title="Task One",
                    summary="one",
                    guidance="fix one",
                    target_paths=["a.py"],
                    verification_commands=[["true"]],
                    on_success_commands=[],
                    on_failure_commands=[],
                )
            ],
            allowed_dirty_paths=[".state"],
            completion_review=mavali_loop.CompletionReviewSpec(
                guidance="Review and continue if needed.",
                max_followup_campaigns=2,
            ),
            source_path="/tmp/parent_campaign.json",
        )
        review_payload = {
            "status": "followup_required",
            "campaign": {
                "campaign_id_suffix": "cleanup",
                "title": "Cleanup",
                "summary": "cleanup summary",
                "tasks": [
                    {
                        "task_id": "cleanup-task",
                        "title": "Cleanup Task",
                        "summary": "cleanup",
                        "guidance": "fix cleanup",
                        "target_paths": ["docs/spec.md"],
                        "verification_commands": [["python3", "-c", "print('ok')"]],
                    }
                ],
            },
        }

        followup = mavali_loop.build_followup_campaign_spec(
            parent,
            review_payload,
            followup_index=1,
            remaining_followups=1,
        )

        self.assertEqual(followup.campaign_id, "parent_campaign_cleanup")
        self.assertEqual(followup.repo_root, parent.repo_root)
        self.assertEqual(followup.allowed_dirty_paths, [".state"])
        self.assertEqual(followup.legacy_state_dirs, [])
        assert followup.completion_review is not None
        self.assertEqual(followup.completion_review.max_followup_campaigns, 1)
        self.assertTrue(followup.source_path.endswith("__followup_1.json"))

    def test_run_loop_clears_stale_followup_pointer_when_review_is_ready(self) -> None:
        spec = self.build_spec()
        spec = mavali_loop.CampaignSpec(
            campaign_id=spec.campaign_id,
            title=spec.title,
            summary=spec.summary,
            tasks=spec.tasks,
            completion_review=mavali_loop.CompletionReviewSpec(
                guidance="Review until ready.",
                max_followup_campaigns=1,
            ),
        )
        t0 = datetime(2026, 5, 9, 0, 0, tzinfo=timezone.utc)
        done_one = mavali_loop.AttemptResult(
            observed_at_utc=t0.isoformat(),
            task_id="task-one",
            attempt=1,
            status="no_change",
            summary="done one",
            codex_returncode=0,
            codex_stdout="",
            codex_stderr="",
            verification_results=[],
            changed_files=[],
            reverted_files=[],
            git_head_before="a",
            git_head_after="a",
        )
        done_two = mavali_loop.AttemptResult(
            observed_at_utc=t0.isoformat(),
            task_id="task-two",
            attempt=1,
            status="no_change",
            summary="done two",
            codex_returncode=0,
            codex_stdout="",
            codex_stderr="",
            verification_results=[],
            changed_files=[],
            reverted_files=[],
            git_head_before="a",
            git_head_after="a",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            paths = mavali_loop.LoopPaths(
                state_root=tmpdir_path,
                campaign_dir=tmpdir_path / "example_campaign",
                state_path=tmpdir_path / "example_campaign" / "state.json",
                results_path=tmpdir_path / "example_campaign" / "results.jsonl",
                report_path=tmpdir_path / "example_campaign" / "report.txt",
                log_path=tmpdir_path / "example_campaign" / "tmux.log",
            )
            paths.campaign_dir.mkdir(parents=True)
            initial_state = {
                "campaign_id": spec.campaign_id,
                "followup_campaign_id": "stale_followup",
                "followup_campaign_path": "/tmp/stale_followup.json",
                "tasks": {},
            }
            paths.state_path.write_text(json.dumps(initial_state), encoding="utf-8")
            with mock.patch.object(mavali_loop, "state_paths_for_campaign", return_value=paths), mock.patch.object(
                mavali_loop,
                "run_task_attempt",
                side_effect=[done_one, done_two],
            ), mock.patch.object(
                mavali_loop,
                "run_completion_review",
                return_value=None,
            ), mock.patch.object(
                mavali_loop,
                "now_utc",
                return_value=t0,
            ), mock.patch.object(
                mavali_loop,
                "send_telegram_message",
                return_value=False,
            ), mock.patch("builtins.print"):
                rc = mavali_loop.run_loop(spec, max_attempts_per_task=2)

            state = json.loads(paths.state_path.read_text(encoding="utf-8"))
            self.assertEqual(rc, 0)
            self.assertNotIn("followup_campaign_id", state)
            self.assertNotIn("followup_campaign_path", state)
