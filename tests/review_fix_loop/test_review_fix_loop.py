import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from unittest import mock

MODULE_PATH = Path(__file__).resolve().parents[2] / "ops" / "review_fix_loop" / "review_fix_loop.py"
SPEC = spec_from_file_location("review_fix_loop", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
review_fix_loop = module_from_spec(SPEC)
sys.modules[SPEC.name] = review_fix_loop
SPEC.loader.exec_module(review_fix_loop)


class ReviewFixLoopTests(unittest.TestCase):
    def test_build_prompt_includes_recent_history(self) -> None:
        issue = review_fix_loop.ISSUES[0]
        issue_state = {
            "history": [
                {
                    "status": "qa_failed",
                    "summary": "tests failed",
                    "changed_files": ["src/telegram_bridge/prompt_preparation.py"],
                }
            ]
        }

        prompt = review_fix_loop.build_prompt(issue, issue_state, 2, 1, 7)

        self.assertIn(issue.issue_id, prompt)
        self.assertIn("tests failed", prompt)
        self.assertIn("src/telegram_bridge/prompt_preparation.py", prompt)

    def test_update_issue_state_marks_success_complete(self) -> None:
        issue_state = {"status": "pending", "attempts": 0, "history": []}
        result = review_fix_loop.AttemptResult(
            observed_at_utc="2026-05-09T00:00:00+00:00",
            issue_id="x",
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

        review_fix_loop.update_issue_state(issue_state, result)

        self.assertEqual(issue_state["status"], "completed")
        self.assertEqual(issue_state["attempts"], 1)
        self.assertEqual(issue_state["history"][0]["status"], "applied")

    def test_git_status_entries_ignores_internal_state_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            state_dir = repo_root / ".state" / "server3-review-fix-loop"
            state_dir.mkdir(parents=True)
            output = "?? .state/server3-review-fix-loop/state.json\n M src/example.py\n"
            proc = mock.Mock(returncode=0, stdout=output)
            with mock.patch.object(review_fix_loop, "ROOT", repo_root), mock.patch.object(
                review_fix_loop,
                "STATE_DIR",
                state_dir,
            ), mock.patch.object(
                review_fix_loop,
                "run_command_capture",
                return_value=proc,
            ):
                entries = review_fix_loop.git_status_entries()

        self.assertEqual(entries, {"src/example.py": " M"})

    def test_path_matches_ignored_prefix_handles_parent_directory_entry(self) -> None:
        self.assertTrue(
            review_fix_loop.path_matches_ignored_prefix(
                ".state/",
                [".state/server3-review-fix-loop"],
            )
        )

    def test_run_loop_retries_issue_until_completed(self) -> None:
        issues = [
            review_fix_loop.ReviewIssue(
                issue_id="issue-one",
                title="Issue One",
                summary="one",
                guidance="fix one",
                target_paths=["a.py"],
                verification_commands=[["true"]],
            ),
            review_fix_loop.ReviewIssue(
                issue_id="issue-two",
                title="Issue Two",
                summary="two",
                guidance="fix two",
                target_paths=["b.py"],
                verification_commands=[["true"]],
            ),
        ]
        t0 = datetime(2026, 5, 9, 0, 0, tzinfo=timezone.utc)
        blocked = review_fix_loop.AttemptResult(
            observed_at_utc=t0.isoformat(),
            issue_id="issue-one",
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
        done_one = review_fix_loop.AttemptResult(
            observed_at_utc=t0.isoformat(),
            issue_id="issue-one",
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
        done_two = review_fix_loop.AttemptResult(
            observed_at_utc=t0.isoformat(),
            issue_id="issue-two",
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
            state_path = tmpdir_path / "state.json"
            results_path = tmpdir_path / "results.jsonl"
            with mock.patch.object(review_fix_loop, "ISSUES", issues), mock.patch.object(
                review_fix_loop,
                "STATE_DIR",
                tmpdir_path,
            ), mock.patch.object(
                review_fix_loop,
                "STATE_PATH",
                state_path,
            ), mock.patch.object(
                review_fix_loop,
                "RESULTS_PATH",
                results_path,
            ), mock.patch.object(
                review_fix_loop,
                "run_issue_attempt",
                side_effect=[blocked, done_one, done_two],
            ) as run_issue_attempt, mock.patch.object(
                review_fix_loop,
                "now_utc",
                return_value=t0,
            ), mock.patch("builtins.print"):
                rc = review_fix_loop.run_loop(max_attempts_per_issue=3)

            state = json.loads(state_path.read_text())
            self.assertEqual(rc, 0)
            self.assertEqual(run_issue_attempt.call_count, 3)
            self.assertEqual(state["issues"]["issue-one"]["status"], "completed")
            self.assertEqual(state["issues"]["issue-one"]["attempts"], 2)
            self.assertEqual(state["issues"]["issue-two"]["status"], "completed")

    def test_run_loop_stops_after_attempt_budget(self) -> None:
        issue = review_fix_loop.ReviewIssue(
            issue_id="issue-one",
            title="Issue One",
            summary="one",
            guidance="fix one",
            target_paths=["a.py"],
            verification_commands=[["true"]],
        )
        t0 = datetime(2026, 5, 9, 0, 0, tzinfo=timezone.utc)
        blocked = review_fix_loop.AttemptResult(
            observed_at_utc=t0.isoformat(),
            issue_id="issue-one",
            attempt=1,
            status="blocked",
            summary="still broken",
            codex_returncode=1,
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
            with mock.patch.object(review_fix_loop, "ISSUES", [issue]), mock.patch.object(
                review_fix_loop,
                "STATE_DIR",
                tmpdir_path,
            ), mock.patch.object(
                review_fix_loop,
                "STATE_PATH",
                tmpdir_path / "state.json",
            ), mock.patch.object(
                review_fix_loop,
                "RESULTS_PATH",
                tmpdir_path / "results.jsonl",
            ), mock.patch.object(
                review_fix_loop,
                "run_issue_attempt",
                return_value=blocked,
            ), mock.patch.object(
                review_fix_loop,
                "now_utc",
                return_value=t0,
            ), mock.patch("builtins.print"):
                rc = review_fix_loop.run_loop(max_attempts_per_issue=1)

            state = json.loads((tmpdir_path / "state.json").read_text())
            self.assertEqual(rc, 1)
            self.assertEqual(state["issues"]["issue-one"]["status"], "pending")
            self.assertEqual(state["issues"]["issue-one"]["attempts"], 1)

    def test_recover_abandoned_attempt_reverts_dirty_files_and_records_result(self) -> None:
        issue = review_fix_loop.ReviewIssue(
            issue_id="issue-one",
            title="Issue One",
            summary="one",
            guidance="fix one",
            target_paths=["a.py"],
            verification_commands=[["true"]],
        )
        t0 = datetime(2026, 5, 9, 0, 0, tzinfo=timezone.utc)

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            state = {
                "campaign_id": review_fix_loop.CAMPAIGN_ID,
                "issues": {},
                "active_attempt": {
                    "issue_id": "issue-one",
                    "attempt": 2,
                    "git_head_before": "abc123",
                    "started_at_utc": t0.isoformat(),
                },
            }
            with mock.patch.object(review_fix_loop, "ISSUES", [issue]), mock.patch.object(
                review_fix_loop,
                "STATE_DIR",
                tmpdir_path,
            ), mock.patch.object(
                review_fix_loop,
                "STATE_PATH",
                tmpdir_path / "state.json",
            ), mock.patch.object(
                review_fix_loop,
                "RESULTS_PATH",
                tmpdir_path / "results.jsonl",
            ), mock.patch.object(
                review_fix_loop,
                "git_status_entries",
                return_value={"src/example.py": " M"},
            ), mock.patch.object(
                review_fix_loop,
                "restore_paths",
                return_value=["src/example.py"],
            ) as restore_paths, mock.patch.object(
                review_fix_loop,
                "git_head",
                return_value="def456",
            ), mock.patch.object(
                review_fix_loop,
                "now_utc",
                return_value=t0,
            ):
                result = review_fix_loop.recover_abandoned_attempt(
                    state,
                    reason="previous run disappeared",
                )

            self.assertIsNotNone(result)
            assert result is not None
            self.assertEqual(result.status, "interrupted")
            self.assertEqual(result.changed_files, ["src/example.py"])
            self.assertEqual(result.reverted_files, ["src/example.py"])
            restore_paths.assert_called_once_with(["src/example.py"])
            self.assertNotIn("active_attempt", state)
            self.assertEqual(state["issues"]["issue-one"]["attempts"], 1)
            self.assertEqual(state["issues"]["issue-one"]["last_status"], "interrupted")

    def test_run_loop_records_interrupted_attempt(self) -> None:
        issue = review_fix_loop.ReviewIssue(
            issue_id="issue-one",
            title="Issue One",
            summary="one",
            guidance="fix one",
            target_paths=["a.py"],
            verification_commands=[["true"]],
        )
        t0 = datetime(2026, 5, 9, 0, 0, tzinfo=timezone.utc)

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            state_path = tmpdir_path / "state.json"
            results_path = tmpdir_path / "results.jsonl"
            with mock.patch.object(review_fix_loop, "ISSUES", [issue]), mock.patch.object(
                review_fix_loop,
                "STATE_DIR",
                tmpdir_path,
            ), mock.patch.object(
                review_fix_loop,
                "STATE_PATH",
                state_path,
            ), mock.patch.object(
                review_fix_loop,
                "RESULTS_PATH",
                results_path,
            ), mock.patch.object(
                review_fix_loop,
                "run_issue_attempt",
                side_effect=review_fix_loop.LoopInterrupted("received signal"),
            ), mock.patch.object(
                review_fix_loop,
                "git_status_entries",
                return_value={"src/example.py": " M"},
            ), mock.patch.object(
                review_fix_loop,
                "restore_paths",
                return_value=["src/example.py"],
            ), mock.patch.object(
                review_fix_loop,
                "git_head",
                return_value="abc123",
            ), mock.patch.object(
                review_fix_loop,
                "now_utc",
                return_value=t0,
            ), mock.patch.object(
                review_fix_loop,
                "install_signal_handlers",
                return_value={},
            ), mock.patch.object(
                review_fix_loop,
                "restore_signal_handlers",
            ), mock.patch("builtins.print"):
                rc = review_fix_loop.run_loop(max_attempts_per_issue=1)

            state = json.loads(state_path.read_text())
            results = results_path.read_text().strip().splitlines()
            self.assertEqual(rc, 1)
            self.assertEqual(len(results), 1)
            self.assertEqual(state["issues"]["issue-one"]["attempts"], 1)
            self.assertEqual(state["issues"]["issue-one"]["last_status"], "interrupted")
            self.assertNotIn("active_attempt", state)

    def test_install_signal_handlers_keeps_ignored_sighup_ignored(self) -> None:
        handlers = {
            review_fix_loop.signal.SIGINT: "old-int",
            review_fix_loop.signal.SIGTERM: "old-term",
            review_fix_loop.signal.SIGHUP: review_fix_loop.signal.SIG_IGN,
        }
        installed = []

        def fake_getsignal(signum):
            return handlers[signum]

        def fake_signal(signum, handler):
            installed.append(signum)
            return handler

        with mock.patch.object(review_fix_loop.signal, "getsignal", side_effect=fake_getsignal), mock.patch.object(
            review_fix_loop.signal,
            "signal",
            side_effect=fake_signal,
        ):
            previous = review_fix_loop.install_signal_handlers()

        self.assertEqual(previous[review_fix_loop.signal.SIGHUP], review_fix_loop.signal.SIG_IGN)
        self.assertIn(review_fix_loop.signal.SIGINT, installed)
        self.assertIn(review_fix_loop.signal.SIGTERM, installed)
        self.assertNotIn(review_fix_loop.signal.SIGHUP, installed)


if __name__ == "__main__":
    unittest.main()
