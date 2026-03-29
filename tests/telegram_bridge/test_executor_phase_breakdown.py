import importlib.util
import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
EXECUTOR_PATH = ROOT / "src" / "telegram_bridge" / "executor.py"
BRIDGE_DIR = EXECUTOR_PATH.parent

spec = importlib.util.spec_from_file_location("telegram_bridge_executor_phase_breakdown", EXECUTOR_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError("Failed to load telegram bridge executor module spec")
executor = importlib.util.module_from_spec(spec)
if str(BRIDGE_DIR) not in sys.path:
    sys.path.insert(0, str(BRIDGE_DIR))
sys.modules[spec.name] = executor
spec.loader.exec_module(executor)


def make_executable_script(path: Path, contents: str) -> None:
    path.write_text(contents, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


class ExecutorPhaseBreakdownTests(unittest.TestCase):
    def test_run_executor_emits_executor_phase_timing_events(self) -> None:
        with tempfile.TemporaryDirectory(prefix="executor-phase-breakdown-") as tmpdir:
            tmp_path = Path(tmpdir)
            fake_executor = tmp_path / "fake_executor.sh"
            make_executable_script(
                fake_executor,
                """#!/usr/bin/env bash
set -euo pipefail
cat >/dev/null
printf '%s\\n' '{"type":"executor.phase_timing","phase":"wrapper_bootstrap","duration_ms":17,"mode":"new"}' >&2
printf '%s\\n' '{"type":"executor.phase_timing","phase":"codex_exec","duration_ms":1234,"mode":"new"}' >&2
printf '%s\\n' '{"type":"thread.started","thread_id":"thread-123"}'
printf '%s\\n' '{"type":"item.completed","item":{"type":"agent_message","status":"completed","text":"done"}}'
""",
            )

            config = SimpleNamespace(
                executor_cmd=[str(fake_executor)],
                exec_timeout_seconds=5,
            )

            with mock.patch.object(executor, "emit_event") as emit_mock:
                result = executor.run_executor(
                    config=config,
                    prompt="hello",
                    thread_id=None,
                    session_key="tg:test",
                    channel_name="telegram",
                    actor_chat_id=123,
                    actor_user_id=456,
                )

            self.assertEqual(result.returncode, 0)
            timing_calls = [
                call.kwargs["fields"]
                for call in emit_mock.call_args_list
                if call.args and call.args[0] == "bridge.executor_phase_timing"
            ]
            self.assertEqual(len(timing_calls), 2)
            self.assertEqual(
                [fields["phase"] for fields in timing_calls],
                ["wrapper_bootstrap", "codex_exec"],
            )
            self.assertEqual(timing_calls[0]["chat_id"], 123)
            self.assertEqual(timing_calls[0]["actor_user_id"], 456)
            self.assertEqual(timing_calls[0]["session_key"], "tg:test")
            self.assertEqual(timing_calls[0]["channel_name"], "telegram")
            self.assertEqual(timing_calls[1]["duration_ms"], 1234)

    def test_extract_executor_phase_timing_rejects_invalid_payload(self) -> None:
        self.assertIsNone(executor.extract_executor_phase_timing({}))
        self.assertIsNone(
            executor.extract_executor_phase_timing(
                {"type": "executor.phase_timing", "phase": "", "duration_ms": 1}
            )
        )
        self.assertIsNone(
            executor.extract_executor_phase_timing(
                {"type": "executor.phase_timing", "phase": "x", "duration_ms": "1"}
            )
        )
        self.assertEqual(
            executor.extract_executor_phase_timing(
                {"type": "executor.phase_timing", "phase": "codex_exec", "duration_ms": 42}
            ),
            {"phase": "codex_exec", "duration_ms": 42},
        )


if __name__ == "__main__":
    unittest.main()
