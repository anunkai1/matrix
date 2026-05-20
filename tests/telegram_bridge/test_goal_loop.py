import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from tests.telegram_bridge.helpers import FakeTelegramClient, make_config

import telegram_bridge.goal_loop as goal_loop
from telegram_bridge.state_store import State


class GoalLoopTests(unittest.TestCase):
    def _make_state(self, tmpdir: str) -> State:
        return State(
            chat_goal_path=str(Path(tmpdir) / "chat_goals.json"),
        )

    def test_goal_command_prefers_topic_scope_over_chat_scope(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state = self._make_state(tmpdir)
            client = FakeTelegramClient()

            with mock.patch.object(
                goal_loop,
                "maybe_start_goal_continuation",
                return_value=True,
            ) as start_continuation:
                handled = goal_loop.handle_goal_command(
                    state=state,
                    config=make_config(),
                    client=client,
                    scope_key="tg:-1003894351534",
                    chat_id=-1003894351534,
                    message_thread_id=1853,
                    message_id=10,
                    raw_text="/goal build the thing",
                )

            self.assertTrue(handled)
            self.assertIn("tg:-1003894351534:topic:1853", state.chat_goals)
            self.assertNotIn("tg:-1003894351534", state.chat_goals)
            start_continuation.assert_called_once()
            self.assertEqual(start_continuation.call_args.kwargs["scope_key"], "tg:-1003894351534:topic:1853")

    def test_goal_command_starts_with_continuation_template(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state = self._make_state(tmpdir)
            client = FakeTelegramClient()

            with mock.patch.object(
                goal_loop,
                "maybe_start_goal_continuation",
                return_value=True,
            ) as start_continuation:
                handled = goal_loop.handle_goal_command(
                    state=state,
                    config=make_config(),
                    client=client,
                    scope_key="tg:-1003894351534:topic:1853",
                    chat_id=-1003894351534,
                    message_thread_id=1853,
                    message_id=10,
                    raw_text="/goal build the thing",
                )

            self.assertTrue(handled)
            start_continuation.assert_called_once()
            prompt = start_continuation.call_args.kwargs["continuation_prompt"]
            self.assertEqual(
                prompt,
                goal_loop.build_continuation_prompt(goal_loop.GoalState(goal="build the thing")),
            )
            self.assertIn("[Continuing toward your standing goal]", prompt)
            self.assertIn("If you believe the goal is complete, state so explicitly and stop.", prompt)
            stored = state.chat_goals["tg:-1003894351534:topic:1853"]
            self.assertEqual(stored.anchor_message_id, 10)

    def test_subgoal_command_reads_topic_scoped_goal(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state = self._make_state(tmpdir)
            client = FakeTelegramClient()
            state.chat_goals["tg:-1003894351534:topic:1853"] = goal_loop.GoalState(
                goal="build the thing",
            )

            handled = goal_loop.handle_subgoal_command(
                state=state,
                client=client,
                scope_key="tg:-1003894351534",
                chat_id=-1003894351534,
                message_thread_id=1853,
                message_id=11,
                raw_text="/subgoal include tests",
            )

            self.assertTrue(handled)
            stored = state.chat_goals["tg:-1003894351534:topic:1853"]
            self.assertEqual(stored.subgoals, ["include tests"])
            self.assertEqual(client.messages[-1][1], "✓ Added subgoal 1: include tests")

    def test_subgoal_remove_zero_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state = self._make_state(tmpdir)
            client = FakeTelegramClient()
            state.chat_goals["tg:-1003894351534:topic:1853"] = goal_loop.GoalState(
                goal="build the thing",
                subgoals=["include tests", "update docs"],
            )

            handled = goal_loop.handle_subgoal_command(
                state=state,
                client=client,
                scope_key="tg:-1003894351534",
                chat_id=-1003894351534,
                message_thread_id=1853,
                message_id=11,
                raw_text="/subgoal remove 0",
            )

            self.assertTrue(handled)
            stored = state.chat_goals["tg:-1003894351534:topic:1853"]
            self.assertEqual(stored.subgoals, ["include tests", "update docs"])
            self.assertEqual(client.messages[-1][1], "/subgoal remove: invalid index")

    def test_goal_continuation_start_failure_clears_busy_and_in_flight_state(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state = self._make_state(tmpdir)
            client = FakeTelegramClient()
            state.chat_goals["tg:-1003894351534:topic:1853"] = goal_loop.GoalState(
                goal="build the thing",
            )

            with mock.patch(
                "telegram_bridge.request_starts.resolve_engine_for_scope",
                return_value=mock.Mock(),
            ), mock.patch(
                "telegram_bridge.request_starts.start_message_worker",
                side_effect=RuntimeError("worker launch failed"),
            ):
                with self.assertRaisesRegex(RuntimeError, "worker launch failed"):
                    goal_loop.maybe_start_goal_continuation(
                        state=state,
                        config=make_config(),
                        client=client,
                        scope_key="tg:-1003894351534:topic:1853",
                        chat_id=-1003894351534,
                        message_thread_id=1853,
                        continuation_prompt="continue",
                    )

            self.assertNotIn("tg:-1003894351534:topic:1853", state.busy_chats)
            self.assertNotIn("tg:-1003894351534:topic:1853", state.in_flight_requests)
            self.assertNotIn("tg:-1003894351534:topic:1853", state.cancel_events)

    def test_goal_continuation_uses_anchor_message_id_for_replies(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state = self._make_state(tmpdir)
            client = FakeTelegramClient()
            state.chat_goals["tg:-1003894351534:topic:1853"] = goal_loop.GoalState(
                goal="build the thing",
                anchor_message_id=6248,
            )

            with mock.patch(
                "telegram_bridge.request_starts.resolve_engine_for_scope",
                return_value=mock.Mock(),
            ), mock.patch(
                "telegram_bridge.request_starts.start_message_worker",
            ) as start_message_worker:
                started = goal_loop.maybe_start_goal_continuation(
                    state=state,
                    config=make_config(),
                    client=client,
                    scope_key="tg:-1003894351534:topic:1853",
                    chat_id=-1003894351534,
                    message_thread_id=1853,
                    continuation_prompt="continue",
                )

            self.assertTrue(started)
            self.assertEqual(start_message_worker.call_args.kwargs["message_id"], 6248)
            self.assertEqual(start_message_worker.call_args.kwargs["message_thread_id"], 1853)

    def test_goal_resume_refreshes_anchor_message_id(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state = self._make_state(tmpdir)
            client = FakeTelegramClient()
            state.chat_goals["tg:-1003894351534:topic:1853"] = goal_loop.GoalState(
                goal="build the thing",
                status="paused",
                anchor_message_id=6248,
            )

            with mock.patch.object(
                goal_loop,
                "maybe_start_goal_continuation",
                return_value=True,
            ) as start_continuation:
                handled = goal_loop.handle_goal_command(
                    state=state,
                    config=make_config(),
                    client=client,
                    scope_key="tg:-1003894351534",
                    chat_id=-1003894351534,
                    message_thread_id=1853,
                    message_id=6300,
                    raw_text="/goal resume",
                )

            self.assertTrue(handled)
            stored = state.chat_goals["tg:-1003894351534:topic:1853"]
            self.assertEqual(stored.anchor_message_id, 6300)
            self.assertEqual(start_continuation.call_args.kwargs["scope_key"], "tg:-1003894351534:topic:1853")

    def test_post_turn_goal_hook_evaluates_topic_scoped_goal(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state = self._make_state(tmpdir)
            client = FakeTelegramClient()
            state.chat_goals["tg:-1003894351534:topic:1853"] = goal_loop.GoalState(
                goal="build the thing",
                anchor_message_id=6248,
            )

            with mock.patch.object(
                goal_loop,
                "evaluate_goal_after_turn",
                return_value={
                    "should_continue": False,
                    "message": "✓ Goal achieved: done",
                    "continuation_prompt": None,
                    "status": "done",
                },
            ) as evaluate_after_turn:
                goal_loop.maybe_handle_goal_post_turn(
                    state=state,
                    config=make_config(),
                    client=client,
                    scope_key="tg:-1003894351534",
                    chat_id=-1003894351534,
                    message_thread_id=1853,
                    delivered_output="completed",
                )

            self.assertEqual(
                evaluate_after_turn.call_args.kwargs["scope_key"],
                "tg:-1003894351534:topic:1853",
            )
            self.assertEqual(client.messages[-1][1], "✓ Goal achieved: done")
            self.assertEqual(client.messages[-1][2], 6248)

    def test_load_chat_goals_prunes_legacy_chat_scope_when_topic_scope_exists(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "chat_goals.json"
            path.write_text(
                (
                    '{'
                    '"tg:-1003894351534":{"goal":"legacy chat scope"},'
                    '"tg:-1003894351534:topic:1853":{"goal":"topic scope"}'
                    '}'
                ),
                encoding="utf-8",
            )

            loaded = goal_loop.load_chat_goals(str(path))

            self.assertNotIn("tg:-1003894351534", loaded)
            self.assertIn("tg:-1003894351534:topic:1853", loaded)

    def test_setting_topic_goal_prunes_legacy_chat_scope_from_state_and_disk(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state = self._make_state(tmpdir)
            state.chat_goals["tg:-1003894351534"] = goal_loop.GoalState(goal="legacy chat scope")

            with mock.patch.object(
                goal_loop,
                "maybe_start_goal_continuation",
                return_value=True,
            ):
                goal_loop.handle_goal_command(
                    state=state,
                    config=make_config(),
                    client=FakeTelegramClient(),
                    scope_key="tg:-1003894351534",
                    chat_id=-1003894351534,
                    message_thread_id=1853,
                    message_id=12,
                    raw_text="/goal topic scope",
                )

            self.assertNotIn("tg:-1003894351534", state.chat_goals)
            self.assertIn("tg:-1003894351534:topic:1853", state.chat_goals)

            persisted = Path(state.chat_goal_path).read_text(encoding="utf-8")
            self.assertNotIn('"tg:-1003894351534"', persisted)
            self.assertIn('"tg:-1003894351534:topic:1853"', persisted)

    def test_judge_done_requires_explicit_goal_complete_wording(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state = self._make_state(tmpdir)
            client = FakeTelegramClient()

            with mock.patch.object(
                goal_loop,
                "build_engine_runtime_config",
                return_value=object(),
            ), mock.patch.object(
                goal_loop,
                "parse_executor_output",
                return_value=("", '{"done": true, "reason": "looks complete"}'),
            ):
                engine = mock.Mock()
                engine.run.return_value = mock.Mock(returncode=0, stdout="ignored")
                with mock.patch(
                    "telegram_bridge.request_starts.resolve_engine_for_scope",
                    return_value=engine,
                ):
                    verdict, reason, parse_failed = goal_loop._run_goal_judge(
                        state=state,
                        config=make_config(),
                        client=client,
                        scope_key="tg:-1003894351534:topic:1853",
                        chat_id=-1003894351534,
                        message_thread_id=1853,
                        goal_state=goal_loop.GoalState(goal="build the thing"),
                        last_response="I checked a few things and it looks promising.",
                    )

            self.assertEqual(verdict, "continue")
            self.assertIn("did not explicitly say the goal is complete or blocked", reason)
            self.assertFalse(parse_failed)

    def test_judge_done_accepts_explicit_goal_complete_wording(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state = self._make_state(tmpdir)
            client = FakeTelegramClient()

            with mock.patch.object(
                goal_loop,
                "build_engine_runtime_config",
                return_value=object(),
            ), mock.patch.object(
                goal_loop,
                "parse_executor_output",
                return_value=("", '{"done": true, "reason": "explicit completion"}'),
            ):
                engine = mock.Mock()
                engine.run.return_value = mock.Mock(returncode=0, stdout="ignored")
                with mock.patch(
                    "telegram_bridge.request_starts.resolve_engine_for_scope",
                    return_value=engine,
                ):
                    verdict, reason, parse_failed = goal_loop._run_goal_judge(
                        state=state,
                        config=make_config(),
                        client=client,
                        scope_key="tg:-1003894351534:topic:1853",
                        chat_id=-1003894351534,
                        message_thread_id=1853,
                        goal_state=goal_loop.GoalState(goal="build the thing"),
                        last_response="Goal complete. I verified the final state and I am stopping here.",
                    )

            self.assertEqual(verdict, "done")
            self.assertEqual(reason, "explicit completion")
            self.assertFalse(parse_failed)

    def test_judge_done_accepts_goal_is_complete_stopping_wording(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state = self._make_state(tmpdir)
            client = FakeTelegramClient()

            with mock.patch.object(
                goal_loop,
                "build_engine_runtime_config",
                return_value=object(),
            ), mock.patch.object(
                goal_loop,
                "parse_executor_output",
                return_value=("", '{"done": true, "reason": "explicit completion"}'),
            ):
                engine = mock.Mock()
                engine.run.return_value = mock.Mock(returncode=0, stdout="ignored")
                with mock.patch(
                    "telegram_bridge.request_starts.resolve_engine_for_scope",
                    return_value=engine,
                ):
                    verdict, reason, parse_failed = goal_loop._run_goal_judge(
                        state=state,
                        config=make_config(),
                        client=client,
                        scope_key="tg:-1003894351534:topic:1853",
                        chat_id=-1003894351534,
                        message_thread_id=1853,
                        goal_state=goal_loop.GoalState(goal="build the thing"),
                        last_response="Goal is complete. Stopping.",
                    )

            self.assertEqual(verdict, "done")
            self.assertEqual(reason, "explicit completion")
            self.assertFalse(parse_failed)


if __name__ == "__main__":
    unittest.main()
