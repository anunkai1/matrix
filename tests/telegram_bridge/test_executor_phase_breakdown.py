import importlib.util
import json
import os
import stat
import subprocess
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
import telegram_bridge.prompt_runtime as prompt_runtime
from telegram_bridge.state_models import State


def make_executable_script(path: Path, contents: str) -> None:
    path.write_text(contents, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


class ExecutorPhaseBreakdownTests(unittest.TestCase):
    def test_run_executor_passes_codex_model_and_effort_env_overrides(self) -> None:
        with tempfile.TemporaryDirectory(prefix="executor-env-") as tmpdir:
            tmp_path = Path(tmpdir)
            fake_executor = tmp_path / "fake_executor.sh"
            make_executable_script(
                fake_executor,
                """#!/usr/bin/env bash
set -euo pipefail
cat >/dev/null
printf '%s|%s\n' "${CODEX_MODEL:-missing}" "${CODEX_REASONING_EFFORT:-missing}"
""",
            )
            config = SimpleNamespace(
                executor_cmd=[str(fake_executor)],
                exec_timeout_seconds=5,
                codex_model="gpt-5.5",
                codex_reasoning_effort="high",
            )

            result = executor.run_executor(
                config=config,
                prompt="hello",
                thread_id=None,
            )

        self.assertEqual(result.returncode, 0)
        self.assertIn("gpt-5.5", result.stdout)
        self.assertIn("high", result.stdout)

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

    def test_run_executor_caches_thread_id_and_output_from_json_stream(self) -> None:
        with tempfile.TemporaryDirectory(prefix="executor-output-cache-") as tmpdir:
            tmp_path = Path(tmpdir)
            fake_executor = tmp_path / "fake_executor.sh"
            make_executable_script(
                fake_executor,
                """#!/usr/bin/env bash
set -euo pipefail
cat >/dev/null
printf '%s\\n' '{"type":"thread.started","thread_id":"thread-123"}'
printf '%s\\n' '{"type":"item.completed","item":{"type":"agent_message","status":"completed","text":"done"}}'
""",
            )
            config = SimpleNamespace(
                executor_cmd=[str(fake_executor)],
                exec_timeout_seconds=5,
            )

            result = executor.run_executor(
                config=config,
                prompt="hello",
                thread_id=None,
            )

        self.assertEqual(executor.cached_executor_result_output(result), ("thread-123", "done"))

    def test_finalize_prompt_success_uses_cached_executor_output(self) -> None:
        state = State()
        state_repo = prompt_runtime.StateRepository(state)
        result = subprocess.CompletedProcess(args=["executor"], returncode=0, stdout="{}", stderr="")
        setattr(result, executor._EXECUTOR_RESULT_THREAD_ID_ATTR, "thread-123")
        setattr(result, executor._EXECUTOR_RESULT_OUTPUT_ATTR, "done")

        runtime_hooks = prompt_runtime.PromptRuntimeHooks(
            build_scope_key_fn=lambda chat_id, message_thread_id=None: f"tg:{chat_id}",
            emit_event_fn=lambda *args, **kwargs: None,
            emit_phase_timing_fn=lambda *args, **kwargs: None,
            send_canceled_response_fn=lambda *args, **kwargs: None,
            send_executor_failure_message_fn=lambda *args, **kwargs: None,
            extract_executor_failure_message_fn=lambda *args, **kwargs: "",
            should_reset_thread_after_resume_failure_fn=lambda *_args, **_kwargs: False,
            resume_retry_phase_fn=lambda _config: "retry",
            parse_executor_output_fn=mock.Mock(side_effect=AssertionError("parse should not run")),
            output_contains_control_directive_fn=lambda output: False,
            trim_output_fn=lambda output, _limit: output,
            deliver_output_and_emit_success_fn=lambda **kwargs: kwargs["output"],
            retry_with_new_session_phase="retry",
        )

        class FakeProgress:
            def __init__(self) -> None:
                self.marked_success = False

            def mark_success(self) -> None:
                self.marked_success = True

        progress = FakeProgress()
        client = object()
        config = SimpleNamespace(empty_output_message="(empty)", max_output_chars=1000)

        new_thread_id, output = prompt_runtime.finalize_prompt_success(
            state_repo=state_repo,
            config=config,
            client=client,
            chat_id=1,
            message_id=2,
            result=result,
            progress=progress,
            runtime_hooks=runtime_hooks,
        )

        self.assertEqual(new_thread_id, "thread-123")
        self.assertEqual(output, "done")
        self.assertEqual(state.chat_threads["tg:1"], "thread-123")
        self.assertTrue(progress.marked_success)


if __name__ == "__main__":
    unittest.main()
