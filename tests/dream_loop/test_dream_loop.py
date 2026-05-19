import importlib.util
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[2] / "ops" / "dream_loop" / "dream_loop.py"
spec = importlib.util.spec_from_file_location("server3_dream_loop", MODULE_PATH)
dream_loop = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = dream_loop
spec.loader.exec_module(dream_loop)


class TestDreamLoop(unittest.TestCase):
    def _fake_run_text_command(self, args):
        command = tuple(args)
        if command == (
            "systemctl",
            "show",
            "server3-runtime-observer.service",
            "-p",
            "Environment",
            "--value",
        ):
            return "PYTHONUNBUFFERED=1 RUNTIME_OBSERVER_MODE=collect_only\n"
        if command == ("systemctl", "cat", "server3-runtime-observer.timer"):
            return "[Timer]\nOnCalendar=*:0/5\n"
        if command == ("systemctl", "is-enabled", "server3-dream-loop.timer"):
            return "enabled\n"
        raise AssertionError(f"Unexpected text command: {command}")

    def _summary_fixture(self):
        return """# Server3 Summary

Last updated: 2026-05-16 (AEST, +10:00)

## Current Snapshot
- Primary active component: `telegram-architect-bridge.service`

## Operational Memory (Pinned)
- Runtime observer runs from `server3-runtime-observer.timer` every 5 minutes; live mode is currently `telegram_alerts`, not the older daily-summary mode.

## Recent Changes (Rolling Max 8)
- 2026-05-16: existing recent change

## Current Risks/Watchouts (Max 5)
- Existing risk
"""

    def _aligned_summary_fixture(self):
        return """# Server3 Summary

Last updated: 2026-05-17 (AEST, +10:00)

## Current Snapshot
- Primary active component: `telegram-architect-bridge.service`

## Operational Memory (Pinned)
- Runtime observer runs from `server3-runtime-observer.timer` every 5 minutes; live mode is currently `collect_only`.
- Dream loop now runs from `server3-dream-loop.timer` around `02:15 AEST` and writes the production truth/health baseline under `/var/lib/server3-dream-loop`.

## Recent Changes (Rolling Max 8)
- 2026-05-17: enabled the bounded Server3 dream loop with a live systemd timer/service and production truth/health state under `/var/lib/server3-dream-loop`.
- 2026-05-16: existing recent change

## Current Risks/Watchouts (Max 5)
- Existing risk
"""

    def _fake_run_json_command(self, args):
        command = tuple(args)
        if command == ("python3", "ops/server3_runtime_status.py", "--json"):
            return {
                "generated_at": "2026-05-17T14:46:24.000000+10:00",
                "manifest": "/repo/infra/server3-runtime-manifest.json",
                "runtimes": [
                    {
                        "name": "Architect",
                        "matches_expected": True,
                        "live_state": "active",
                        "expected_default_state": "active",
                    },
                    {
                        "name": "AgentSmith",
                        "matches_expected": True,
                        "live_state": "active",
                        "expected_default_state": "active",
                    },
                ],
            }
        if command == ("python3", "ops/runtime_observer/runtime_observer.py", "--json", "status"):
            return {
                "kpis": {
                    "service_up": {"severity": "ok"},
                    "telegram_retry_rate": {"severity": "warn"},
                },
                "warnings": ["sample-warning"],
            }
        if command == (
            "python3",
            "ops/runtime_observer/runtime_observer.py",
            "--json",
            "summary",
            "--hours",
            "24",
        ):
            return {
                "kpis": {
                    "restart_count": {"worst_severity": "critical"},
                    "service_up": {"worst_severity": "ok"},
                }
            }
        raise AssertionError(f"Unexpected command: {command}")

    def _fake_run_json_with_runtime_mismatch(self, args):
        payload = self._fake_run_json_command(args)
        if tuple(args) == ("python3", "ops/server3_runtime_status.py", "--json"):
            payload = dict(payload)
            payload["runtimes"] = [
                dict(item)
                for item in payload["runtimes"]
            ]
            payload["runtimes"][0]["matches_expected"] = False
            payload["runtimes"][0]["live_state"] = "failed"
        return payload

    def test_execute_dream_loop_dry_run_does_not_write_outputs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state_dir = Path(tmpdir) / "dream"
            bridge_state_dir = Path(tmpdir) / "bridge"
            summary_path = Path(tmpdir) / "SERVER3_SUMMARY.md"
            bridge_state_dir.mkdir(parents=True, exist_ok=True)
            summary_path.write_text(self._summary_fixture(), encoding="utf-8")
            config = dream_loop.DreamLoopConfig(
                state_dir=state_dir,
                bridge_state_dir=bridge_state_dir,
                timezone="Australia/Brisbane",
                dry_run=True,
                summary_path=summary_path,
            )
            result = dream_loop.execute_dream_loop(
                config,
                run_json_command=self._fake_run_json_command,
                run_text_command=self._fake_run_text_command,
            )
            self.assertEqual(result["run_state"]["run_status"], "dry_run_succeeded")
            self.assertFalse((state_dir / dream_loop.LATEST_TRUTH_STATE).exists())
            self.assertIn("Server3 Dream Loop Report", result["report_text"])
            self.assertIn("summary_out_of_alignment", result["truth_state"]["secondary_doc_alignment"])
            self.assertEqual(summary_path.read_text(encoding="utf-8"), self._summary_fixture())

    def test_execute_dream_loop_writes_outputs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state_dir = Path(tmpdir) / "dream"
            bridge_state_dir = Path(tmpdir) / "bridge"
            summary_path = Path(tmpdir) / "SERVER3_SUMMARY.md"
            bridge_state_dir.mkdir(parents=True, exist_ok=True)
            summary_path.write_text(self._summary_fixture(), encoding="utf-8")
            config = dream_loop.DreamLoopConfig(
                state_dir=state_dir,
                bridge_state_dir=bridge_state_dir,
                timezone="Australia/Brisbane",
                dry_run=False,
                summary_path=summary_path,
            )
            result = dream_loop.execute_dream_loop(
                config,
                run_json_command=self._fake_run_json_command,
                run_text_command=self._fake_run_text_command,
            )
            self.assertEqual(result["run_state"]["run_status"], "succeeded")
            truth_state = json.loads((state_dir / dream_loop.LATEST_TRUTH_STATE).read_text(encoding="utf-8"))
            health_state = json.loads((state_dir / dream_loop.LATEST_HEALTH_STATE).read_text(encoding="utf-8"))
            run_state = json.loads((state_dir / dream_loop.LATEST_RUN_STATE).read_text(encoding="utf-8"))
            report_text = (state_dir / dream_loop.LATEST_REPORT).read_text(encoding="utf-8")

            self.assertIn("machine_truth_fingerprint", truth_state)
            self.assertIn("health_status", health_state)
            self.assertEqual(run_state["run_status"], "succeeded")
            self.assertIn("Server3 Dream Loop Report", report_text)
            self.assertEqual(len(run_state["artifacts_written"]), 4)
            self.assertIn(str(summary_path), run_state["files_updated"])
            self.assertEqual(len(truth_state["secondary_doc_alignment"]["documents"]), 1)
            self.assertEqual(
                truth_state["secondary_doc_alignment"]["documents"][0]["doc_role"],
                "secondary_rendered_explainer",
            )
            report_output = truth_state["generated_output_status"]["outputs"][0]
            self.assertEqual(report_output["output_role"], "generated_report_layer")
            self.assertTrue(report_output["rendered_from_current_state"])
            self.assertTrue(
                truth_state["live_runtime_alignment"]["machine_truth_fingerprint_uses_structured_inputs_only"]
            )
            updated_summary = summary_path.read_text(encoding="utf-8")
            self.assertIn("live mode is currently `collect_only`.", updated_summary)
            self.assertIn("server3-dream-loop.timer", updated_summary)
            self.assertFalse(truth_state["secondary_doc_alignment"]["summary_out_of_alignment"])
            self.assertEqual(truth_state["secondary_doc_alignment"]["summary_changed_fields"], [])
            self.assertIn("Structured machine-truth inputs only: yes", report_text)
            self.assertIn("[rendered]", report_text)
            self.assertIn("[aligned]", report_text)

    def test_summary_alignment_is_idempotent_when_already_aligned(self):
        now = datetime(2026, 5, 17, 15, 30, tzinfo=timezone(timedelta(hours=10)))
        aligned_text, changed_fields = dream_loop._align_server3_summary(
            self._aligned_summary_fixture(),
            generated_at=now,
            summary_facts={
                "observer_mode": "collect_only",
                "observer_schedule_text": "every 5 minutes",
                "dream_loop_timer_enabled": True,
            },
        )
        self.assertEqual(aligned_text, self._aligned_summary_fixture())
        self.assertEqual(changed_fields, [])

    def test_execute_dream_loop_does_not_report_false_summary_drift(self):
        fixed_now = datetime(2026, 5, 17, 15, 30, tzinfo=timezone(timedelta(hours=10)))

        with tempfile.TemporaryDirectory() as tmpdir:
            state_dir = Path(tmpdir) / "dream"
            bridge_state_dir = Path(tmpdir) / "bridge"
            summary_path = Path(tmpdir) / "SERVER3_SUMMARY.md"
            bridge_state_dir.mkdir(parents=True, exist_ok=True)
            summary_path.write_text(self._aligned_summary_fixture(), encoding="utf-8")
            config = dream_loop.DreamLoopConfig(
                state_dir=state_dir,
                bridge_state_dir=bridge_state_dir,
                timezone="Australia/Brisbane",
                dry_run=True,
                summary_path=summary_path,
            )
            result = dream_loop.execute_dream_loop(
                config,
                now_fn=lambda _tz: fixed_now,
                run_json_command=self._fake_run_json_command,
                run_text_command=self._fake_run_text_command,
            )
            alignment = result["truth_state"]["secondary_doc_alignment"]
            self.assertFalse(alignment["summary_out_of_alignment"])
            self.assertEqual(alignment["summary_changed_fields"], [])

    def test_runtime_state_drift_is_visible_without_counting_as_machine_truth_change(self):
        fixed_now = datetime(2026, 5, 17, 15, 30, tzinfo=timezone(timedelta(hours=10)))

        with tempfile.TemporaryDirectory() as tmpdir:
            state_dir = Path(tmpdir) / "dream"
            bridge_state_dir = Path(tmpdir) / "bridge"
            summary_path = Path(tmpdir) / "SERVER3_SUMMARY.md"
            bridge_state_dir.mkdir(parents=True, exist_ok=True)
            summary_path.write_text(self._aligned_summary_fixture(), encoding="utf-8")
            config = dream_loop.DreamLoopConfig(
                state_dir=state_dir,
                bridge_state_dir=bridge_state_dir,
                timezone="Australia/Brisbane",
                dry_run=True,
                summary_path=summary_path,
            )
            result = dream_loop.execute_dream_loop(
                config,
                now_fn=lambda _tz: fixed_now,
                run_json_command=self._fake_run_json_with_runtime_mismatch,
                run_text_command=self._fake_run_text_command,
            )
            self.assertFalse(result["truth_state"]["stale_context_eligibility"]["machine_truth_changed"])
            self.assertEqual(
                result["truth_state"]["live_runtime_alignment"]["runtime_state_mismatches"],
                [
                    {
                        "name": "Architect",
                        "live_state": "failed",
                        "expected_default_state": "active",
                    }
                ],
            )
            self.assertIn("Runtime state mismatch: Architect is failed, expected active", result["report_text"])

    def test_truth_change_marks_active_scopes_eligible(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state_dir = Path(tmpdir) / "dream"
            bridge_state_dir = Path(tmpdir) / "bridge"
            summary_path = Path(tmpdir) / "SERVER3_SUMMARY.md"
            bridge_state_dir.mkdir(parents=True, exist_ok=True)
            summary_path.write_text(self._summary_fixture(), encoding="utf-8")

            previous_truth = {
                "machine_truth_fingerprint": "old-machine",
                "policy_truth_fingerprint": "old-policy",
                "watched_inputs": {
                    "machine_truth_inputs": [],
                    "policy_inputs": [],
                },
            }
            state_dir.mkdir(parents=True, exist_ok=True)
            (state_dir / dream_loop.LATEST_TRUTH_STATE).write_text(
                json.dumps(previous_truth),
                encoding="utf-8",
            )

            sqlite_path = bridge_state_dir / "chat_sessions.sqlite3"
            dream_loop.sqlite3.connect(str(sqlite_path)).close()
            with dream_loop.sqlite3.connect(str(sqlite_path)) as conn:
                conn.execute(
                    """
                    CREATE TABLE canonical_sessions (
                        scope_key TEXT PRIMARY KEY,
                        chat_id INTEGER,
                        message_thread_id INTEGER,
                        thread_id TEXT NOT NULL DEFAULT '',
                        worker_created_at REAL,
                        worker_last_used_at REAL,
                        worker_policy_fingerprint TEXT NOT NULL DEFAULT '',
                        in_flight_started_at REAL,
                        in_flight_message_id INTEGER
                    )
                    """
                )
                conn.execute(
                    """
                    INSERT INTO canonical_sessions (
                        scope_key,
                        chat_id,
                        message_thread_id,
                        thread_id,
                        worker_created_at,
                        worker_last_used_at,
                        worker_policy_fingerprint,
                        in_flight_started_at,
                        in_flight_message_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "tg:-1003894351534:topic:4677",
                        -1003894351534,
                        4677,
                        "thread-1",
                        1_700_000_000.0,
                        4_000_000_000.0,
                        "",
                        None,
                        None,
                    ),
                )
                conn.commit()

            config = dream_loop.DreamLoopConfig(
                state_dir=state_dir,
                bridge_state_dir=bridge_state_dir,
                timezone="Australia/Brisbane",
                dry_run=True,
                summary_path=summary_path,
            )
            result = dream_loop.execute_dream_loop(
                config,
                run_json_command=self._fake_run_json_command,
                run_text_command=self._fake_run_text_command,
            )
            stale = result["truth_state"]["stale_context_eligibility"]
            self.assertTrue(stale["machine_truth_changed"])
            self.assertEqual(stale["eligible_scope_count"], 1)
            self.assertEqual(stale["eligible_scope_keys"], ["tg:-1003894351534:topic:4677"])

    def test_execute_dream_loop_verifies_persisted_outputs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state_dir = Path(tmpdir) / "dream"
            bridge_state_dir = Path(tmpdir) / "bridge"
            summary_path = Path(tmpdir) / "SERVER3_SUMMARY.md"
            bridge_state_dir.mkdir(parents=True, exist_ok=True)
            summary_path.write_text(self._summary_fixture(), encoding="utf-8")
            config = dream_loop.DreamLoopConfig(
                state_dir=state_dir,
                bridge_state_dir=bridge_state_dir,
                timezone="Australia/Brisbane",
                dry_run=False,
                summary_path=summary_path,
            )

            original_verify = dream_loop._verify_persisted_outputs

            def fake_verify(**kwargs):
                mismatches = list(original_verify(**kwargs))
                mismatches.append("forced mismatch")
                return mismatches

            try:
                dream_loop._verify_persisted_outputs = fake_verify
                with self.assertRaisesRegex(RuntimeError, "dream loop output verification failed"):
                    dream_loop.execute_dream_loop(
                        config,
                        run_json_command=self._fake_run_json_command,
                        run_text_command=self._fake_run_text_command,
                    )
            finally:
                dream_loop._verify_persisted_outputs = original_verify


if __name__ == "__main__":
    unittest.main()
