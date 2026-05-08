import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from unittest import mock

MODULE_PATH = Path(__file__).resolve().parents[2] / "ops" / "ralph_loop" / "ralph_loop.py"
SPEC = spec_from_file_location("ralph_loop", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
ralph_loop = module_from_spec(SPEC)
sys.modules[SPEC.name] = ralph_loop
SPEC.loader.exec_module(ralph_loop)


class RalphLoopTests(unittest.TestCase):
    def test_build_candidates_ranks_worker_capacity_pressure_first(self) -> None:
        rows = (
            [{"event": "bridge.worker_capacity_rejected"} for _ in range(5)]
            + [{"event": "bridge.request_succeeded"} for _ in range(8)]
            + [
                {
                    "event": "bridge.request_phase_timing",
                    "phase": "process_prompt_total",
                    "duration_ms": 7000,
                },
                {
                    "event": "bridge.executor_phase_timing",
                    "phase": "codex_exec",
                    "duration_ms": 4000,
                },
            ]
        )

        candidates = ralph_loop.build_candidates(rows)

        self.assertEqual(candidates[0].id, "worker_capacity_pressure")
        self.assertEqual(candidates[0].score, 60)

    def test_phase_stats_reports_avg_and_p95(self) -> None:
        rows = [
            {"event": "bridge.request_phase_timing", "phase": "engine_run", "duration_ms": 1000},
            {"event": "bridge.request_phase_timing", "phase": "engine_run", "duration_ms": 2000},
            {"event": "bridge.request_phase_timing", "phase": "engine_run", "duration_ms": 3000},
        ]

        stats = ralph_loop.phase_stats(rows, "bridge.request_phase_timing", "engine_run")

        self.assertEqual(stats["count"], 3.0)
        self.assertEqual(stats["avg_ms"], 2000.0)
        self.assertEqual(stats["p95_ms"], 2900.0)

    def test_format_report_includes_top_target_and_evidence(self) -> None:
        candidate = ralph_loop.Candidate(
            id="worker_capacity_pressure",
            title="Reduce worker capacity pressure",
            score=72,
            category="capacity",
            why="Worker-capacity rejects directly drop requests.",
            next_action="Tune session policy.",
            evidence={"worker_capacity_rejected_last_window": 6},
            target_paths=["src/telegram_bridge/session_manager.py"],
        )

        text = ralph_loop.format_report(
            observed_at=datetime(2026, 5, 9, 1, 2, 3, tzinfo=timezone.utc),
            unit="telegram-architect-bridge.service",
            window_hours=6,
            snapshot={"kpis": {"request_fail_rate": {"rate_percent": 2.0}}},
            candidates=[candidate],
        )

        self.assertIn("worker_capacity_pressure", text)
        self.assertIn("Tune session policy.", text)
        self.assertIn(json.dumps(candidate.evidence, sort_keys=True), text)

    def test_collect_once_writes_backlog_and_report(self) -> None:
        observed_at = datetime(2026, 5, 9, 1, 2, 3, tzinfo=timezone.utc)
        fake_rows = [
            {"event": "bridge.request_succeeded"},
            {"event": "bridge.worker_capacity_rejected"},
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            with mock.patch.object(ralph_loop, "STATE_DIR", tmpdir_path), mock.patch.object(
                ralph_loop,
                "LATEST_REPORT_PATH",
                tmpdir_path / "latest.md",
            ), mock.patch.object(
                ralph_loop,
                "LATEST_BACKLOG_PATH",
                tmpdir_path / "optimization_backlog.json",
            ), mock.patch.object(
                ralph_loop,
                "HISTORY_PATH",
                tmpdir_path / "history.jsonl",
            ), mock.patch.object(
                ralph_loop,
                "now_utc",
                return_value=observed_at,
            ), mock.patch.object(
                ralph_loop.runtime_observer,
                "build_snapshot",
                return_value={"kpis": {"request_fail_rate": {"rate_percent": 0.0}}},
            ), mock.patch.object(
                ralph_loop,
                "load_bridge_events",
                return_value=fake_rows,
            ), mock.patch("builtins.print"):
                result = ralph_loop.collect_once()

            self.assertEqual(result, 0)
            backlog = json.loads((tmpdir_path / "optimization_backlog.json").read_text())
            self.assertEqual(backlog["top_candidate_id"], "worker_capacity_pressure")
            self.assertTrue((tmpdir_path / "latest.md").exists())

    def test_ensure_state_dir_falls_back_when_primary_is_not_writable(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            fallback = Path(tmpdir) / "fallback"
            with mock.patch.object(
                ralph_loop,
                "STATE_DIR",
                Path("/root/forbidden-ralph-loop"),
            ), mock.patch.object(
                ralph_loop,
                "LATEST_REPORT_PATH",
                Path("/root/forbidden-ralph-loop/latest.md"),
            ), mock.patch.object(
                ralph_loop,
                "LATEST_BACKLOG_PATH",
                Path("/root/forbidden-ralph-loop/optimization_backlog.json"),
            ), mock.patch.object(
                ralph_loop,
                "HISTORY_PATH",
                Path("/root/forbidden-ralph-loop/history.jsonl"),
            ), mock.patch.dict(
                "os.environ",
                {"RALPH_LOOP_FALLBACK_STATE_DIR": str(fallback)},
                clear=False,
            ), mock.patch.object(
                Path,
                "mkdir",
                side_effect=[PermissionError("denied"), None],
            ):
                ralph_loop.ensure_state_dir()
                self.assertEqual(ralph_loop.STATE_DIR, fallback)
                self.assertEqual(ralph_loop.LATEST_REPORT_PATH, fallback / "latest.md")


if __name__ == "__main__":
    unittest.main()
