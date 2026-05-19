import unittest
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from unittest import mock

MODULE_PATH = Path(__file__).resolve().parents[2] / "ops" / "review_fix_loop" / "review_fix_loop.py"
REPO_LOCAL_CAMPAIGN_PATH = (
    Path(__file__).resolve().parents[2]
    / "ops"
    / "mavali_loop"
    / "campaigns"
    / "server3_code_review_may_2026.json"
)
SPEC = spec_from_file_location("review_fix_loop", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
review_fix_loop = module_from_spec(SPEC)
SPEC.loader.exec_module(review_fix_loop)


class ReviewFixLoopWrapperTests(unittest.TestCase):
    def test_wrapper_forwards_run_to_mavali_loop(self) -> None:
        fake_runner = mock.Mock()
        fake_runner.main.return_value = 0
        with mock.patch.object(review_fix_loop, "load_mavali_loop_module", return_value=fake_runner):
            rc = review_fix_loop.main(["run", "--max-attempts-per-issue", "7"])

        self.assertEqual(rc, 0)
        fake_runner.main.assert_called_once_with(
            [
                "run",
                str(review_fix_loop.CAMPAIGN_PATH),
                "--max-attempts-per-task",
                "7",
            ]
        )

    def test_wrapper_forwards_status_to_mavali_loop(self) -> None:
        fake_runner = mock.Mock()
        fake_runner.main.return_value = 0
        with mock.patch.object(review_fix_loop, "load_mavali_loop_module", return_value=fake_runner):
            rc = review_fix_loop.main(["status"])

        self.assertEqual(rc, 0)
        fake_runner.main.assert_called_once_with(["status", str(review_fix_loop.CAMPAIGN_PATH)])

    def test_repo_local_campaign_mirror_is_absent(self) -> None:
        self.assertFalse(REPO_LOCAL_CAMPAIGN_PATH.exists())
