import json
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
from telegram_bridge.state_models import CanonicalSession, WorkerSession
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

    def test_goal_command_uses_configured_goal_turn_budget(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state = self._make_state(tmpdir)
            client = FakeTelegramClient()
            config = make_config()
            config.goal_max_turns = 33

            with mock.patch.object(
                goal_loop,
                "maybe_start_goal_continuation",
                return_value=True,
            ):
                handled = goal_loop.handle_goal_command(
                    state=state,
                    config=config,
                    client=client,
                    scope_key="tg:-1003894351534:topic:1853",
                    chat_id=-1003894351534,
                    message_thread_id=1853,
                    message_id=10,
                    raw_text="/goal build the thing",
                )

            self.assertTrue(handled)
            stored = state.chat_goals["tg:-1003894351534:topic:1853"]
            self.assertEqual(stored.max_turns, 33)
            self.assertIn("⊙ Goal set (33 turns): build the thing", client.messages[-1][1])

    def test_goal_command_uses_canonical_scope_goal_storage_when_enabled(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state = State(
                chat_goal_path=str(Path(tmpdir) / "chat_goals.json"),
                chat_sessions_path=str(Path(tmpdir) / "chat_sessions.json"),
                canonical_sessions_enabled=True,
            )
            client = FakeTelegramClient()

            with mock.patch.object(
                goal_loop,
                "maybe_start_goal_continuation",
                return_value=True,
            ):
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
            self.assertIn("tg:-1003894351534:topic:1853", state.chat_sessions)
            self.assertEqual(
                state.chat_sessions["tg:-1003894351534:topic:1853"].goal_state["goal"],
                "build the thing",
            )
            persisted = json.loads(Path(state.chat_sessions_path).read_text(encoding="utf-8"))
            self.assertEqual(
                persisted["tg:-1003894351534:topic:1853"]["goal_state"]["goal"],
                "build the thing",
            )

    def test_scope_goal_manager_lifecycle(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state = self._make_state(tmpdir)
            manager = goal_loop.ScopeGoalManager(state, "tg:-1003894351534:topic:1853")

            created = manager.set("build the thing", anchor_message_id=10)
            self.assertEqual(created.goal, "build the thing")
            self.assertTrue(manager.is_active())
            self.assertTrue(manager.has_goal())

            paused = manager.pause()
            self.assertIsNotNone(paused)
            self.assertEqual(paused.status, "paused")
            self.assertFalse(manager.is_active())

            resumed = manager.resume(anchor_message_id=11)
            self.assertIsNotNone(resumed)
            self.assertEqual(resumed.status, "active")
            self.assertEqual(resumed.anchor_message_id, 11)
            self.assertEqual(resumed.turns_used, 0)

            cleared = manager.clear()
            self.assertTrue(cleared)
            self.assertFalse(manager.has_goal())
            self.assertIn("tg:-1003894351534:topic:1853", state.chat_goals)
            self.assertEqual(state.chat_goals["tg:-1003894351534:topic:1853"].status, "cleared")
            self.assertEqual(manager.status_line(), "No active goal. Set one with /goal <text>.")

    def test_clear_preserves_cleared_goal_state_in_canonical_session(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state = State(
                chat_goal_path=str(Path(tmpdir) / "chat_goals.json"),
                chat_sessions_path=str(Path(tmpdir) / "chat_sessions.json"),
                canonical_sessions_enabled=True,
            )
            manager = goal_loop.ScopeGoalManager(state, "tg:-1003894351534:topic:1853")
            manager.set("build the thing", anchor_message_id=10)

            cleared = manager.clear()

            self.assertTrue(cleared)
            session = state.chat_sessions["tg:-1003894351534:topic:1853"]
            self.assertEqual(session.goal_state["status"], "cleared")
            persisted = json.loads(Path(state.chat_sessions_path).read_text(encoding="utf-8"))
            self.assertEqual(
                persisted["tg:-1003894351534:topic:1853"]["goal_state"]["status"],
                "cleared",
            )

    def test_goal_status_hides_cleared_goal_as_inactive(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state = self._make_state(tmpdir)
            client = FakeTelegramClient()
            state.chat_goals["tg:-1003894351534:topic:1853"] = goal_loop.GoalState(
                goal="build the thing",
                status="cleared",
            )

            handled = goal_loop.handle_goal_command(
                state=state,
                config=make_config(),
                client=client,
                scope_key="tg:-1003894351534",
                chat_id=-1003894351534,
                message_thread_id=1853,
                message_id=11,
                raw_text="/goal status",
            )

            self.assertTrue(handled)
            self.assertEqual(client.messages[-1][1], "No active goal. Set one with /goal <text>.")

    def test_goal_resume_rejects_cleared_goal(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state = self._make_state(tmpdir)
            client = FakeTelegramClient()
            state.chat_goals["tg:-1003894351534:topic:1853"] = goal_loop.GoalState(
                goal="build the thing",
                status="cleared",
            )

            handled = goal_loop.handle_goal_command(
                state=state,
                config=make_config(),
                client=client,
                scope_key="tg:-1003894351534",
                chat_id=-1003894351534,
                message_thread_id=1853,
                message_id=11,
                raw_text="/goal resume",
            )

            self.assertTrue(handled)
            self.assertEqual(client.messages[-1][1], "No paused goal to resume.")

    def test_subgoal_rejects_cleared_goal(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state = self._make_state(tmpdir)
            client = FakeTelegramClient()
            state.chat_goals["tg:-1003894351534:topic:1853"] = goal_loop.GoalState(
                goal="build the thing",
                status="cleared",
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
            self.assertEqual(client.messages[-1][1], "No active goal. Set one with /goal <text>.")

    def test_goal_status_shows_canonical_thread_and_in_flight_details(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state = State(
                chat_goal_path=str(Path(tmpdir) / "chat_goals.json"),
                chat_sessions_path=str(Path(tmpdir) / "chat_sessions.json"),
                canonical_sessions_enabled=True,
            )
            client = FakeTelegramClient()
            created_at = 1760000000.0
            last_turn_at = created_at + 60
            state.chat_sessions["tg:-1003894351534:topic:1853"] = CanonicalSession(
                thread_id="thread-xyz",
                in_flight_started_at=created_at + 30,
                in_flight_message_id=77,
                goal_state=goal_loop.GoalState(
                    goal="build the thing",
                    anchor_message_id=10,
                    turns_used=2,
                    created_at=created_at,
                    last_turn_at=last_turn_at,
                    last_verdict="continue",
                    last_reason="more work needed",
                    subgoals=["include tests"],
                ).to_dict(),
            )
            state.worker_sessions["tg:-1003894351534:topic:1853"] = WorkerSession(
                created_at=created_at,
                last_used_at=last_turn_at,
                thread_id="thread-xyz",
                policy_fingerprint="policy-1",
            )
            state.in_flight_requests["tg:-1003894351534:topic:1853"] = {
                "started_at": created_at + 30,
                "message_id": 77,
            }
            state.busy_chats.add("tg:-1003894351534:topic:1853")

            handled = goal_loop.handle_goal_command(
                state=state,
                config=make_config(),
                client=client,
                scope_key="tg:-1003894351534",
                chat_id=-1003894351534,
                message_thread_id=1853,
                message_id=11,
                raw_text="/goal status",
            )

            self.assertTrue(handled)
            text = client.messages[-1][1]
            self.assertIn("Goal: build the thing", text)
            self.assertIn("Lifecycle: active", text)
            self.assertIn("Canonical session: linked", text)
            self.assertIn("Worker thread: thread-xyz", text)
            self.assertIn("In-flight: running since", text)
            self.assertIn("(message 77)", text)
            self.assertIn("Last judge verdict: continue", text)
            self.assertIn("Last judge reason: more work needed", text)

    def test_goal_status_reports_waiting_when_goal_active_without_running_request(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state = self._make_state(tmpdir)
            client = FakeTelegramClient()
            state.chat_goals["tg:-1003894351534:topic:1853"] = goal_loop.GoalState(
                goal="build the thing",
                anchor_message_id=10,
            )

            handled = goal_loop.handle_goal_command(
                state=state,
                config=make_config(),
                client=client,
                scope_key="tg:-1003894351534",
                chat_id=-1003894351534,
                message_thread_id=1853,
                message_id=11,
                raw_text="/goal status",
            )

            self.assertTrue(handled)
            text = client.messages[-1][1]
            self.assertIn("Lifecycle: waiting", text)
            self.assertIn("In-flight: idle", text)
            self.assertIn("Worker thread: none", text)

    def test_goal_status_classifies_preempted_and_canceled_pause_reasons(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state = self._make_state(tmpdir)
            client = FakeTelegramClient()
            state.chat_goals["tg:-1003894351534:topic:1853"] = goal_loop.GoalState(
                goal="build the thing",
                status="paused",
                paused_reason="user-follow-up preempted the active goal turn",
            )

            handled = goal_loop.handle_goal_command(
                state=state,
                config=make_config(),
                client=client,
                scope_key="tg:-1003894351534",
                chat_id=-1003894351534,
                message_thread_id=1853,
                message_id=11,
                raw_text="/goal status",
            )

            self.assertTrue(handled)
            self.assertIn("Lifecycle: preempted", client.messages[-1][1])
            self.assertIn("Pause reason: user-follow-up preempted the active goal turn", client.messages[-1][1])

            state.chat_goals["tg:-1003894351534:topic:1853"] = goal_loop.GoalState(
                goal="build the thing",
                status="paused",
                paused_reason="active goal turn was canceled or interrupted by the user",
            )

            handled = goal_loop.handle_goal_command(
                state=state,
                config=make_config(),
                client=client,
                scope_key="tg:-1003894351534",
                chat_id=-1003894351534,
                message_thread_id=1853,
                message_id=12,
                raw_text="/goal status",
            )

            self.assertTrue(handled)
            self.assertIn("Lifecycle: canceled", client.messages[-1][1])

    def test_reconcile_goal_state_imports_legacy_goals_into_canonical_sessions(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state = State(
                chat_goal_path=str(Path(tmpdir) / "chat_goals.json"),
                chat_sessions_path=str(Path(tmpdir) / "chat_sessions.json"),
                canonical_sessions_enabled=True,
            )
            state.chat_goals["tg:-1003894351534:topic:1853"] = goal_loop.GoalState(goal="build the thing")

            changed = goal_loop.reconcile_goal_state_with_canonical_sessions(state)

            self.assertTrue(changed)
            self.assertEqual(
                state.chat_sessions["tg:-1003894351534:topic:1853"].goal_state["goal"],
                "build the thing",
            )
            self.assertIn("tg:-1003894351534:topic:1853", state.chat_goals)

    def test_scope_goal_manager_evaluate_after_turn_marks_done(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state = self._make_state(tmpdir)
            manager = goal_loop.ScopeGoalManager(state, "tg:-1003894351534:topic:1853")
            manager.set("build the thing", anchor_message_id=10)

            with mock.patch.object(
                goal_loop,
                "_run_goal_judge",
                return_value=("done", "explicit completion", False),
            ):
                decision = manager.evaluate_after_turn(
                    config=make_config(),
                    client=FakeTelegramClient(),
                    chat_id=-1003894351534,
                    message_thread_id=1853,
                    last_response="Goal complete. Done.",
                )

            self.assertFalse(decision.should_continue)
            self.assertEqual(decision.status, "done")
            self.assertEqual(manager.goal_state.status, "done")

    def test_scope_goal_manager_evaluate_after_turn_returns_continuation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state = self._make_state(tmpdir)
            manager = goal_loop.ScopeGoalManager(state, "tg:-1003894351534:topic:1853")
            manager.set("build the thing", anchor_message_id=10)

            with mock.patch.object(
                goal_loop,
                "_run_goal_judge",
                return_value=("continue", "more work needed", False),
            ):
                decision = manager.evaluate_after_turn(
                    config=make_config(),
                    client=FakeTelegramClient(),
                    chat_id=-1003894351534,
                    message_thread_id=1853,
                    last_response="I started the work.",
                )

            self.assertTrue(decision.should_continue)
            self.assertEqual(decision.status, "active")
            self.assertIn("[Continuing toward your standing goal]", decision.continuation_prompt)
            self.assertEqual(manager.goal_state.turns_used, 1)

    def test_scope_goal_manager_builds_continuation_request(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state = self._make_state(tmpdir)
            manager = goal_loop.ScopeGoalManager(state, "tg:-1003894351534:topic:1853")
            manager.set("build the thing", anchor_message_id=10)

            request = manager.build_continuation_request(
                chat_id=-1003894351534,
                message_thread_id=1853,
            )

            self.assertIsNotNone(request)
            self.assertEqual(request.anchor_message_id, 10)
            self.assertEqual(request.scope_key, "tg:-1003894351534:topic:1853")
            self.assertIn("[Continuing toward your standing goal]", request.prompt)

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
                goal_loop.ScopeGoalManager,
                "evaluate_after_turn",
                return_value=goal_loop.GoalPostTurnDecision(
                    status="done",
                    should_continue=False,
                    message="✓ Goal achieved: done",
                ),
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
                evaluate_after_turn.call_args.kwargs["chat_id"],
                -1003894351534,
            )
            self.assertEqual(client.messages[-1][1], "✓ Goal achieved: done")
            self.assertEqual(client.messages[-1][2], 6248)

    def test_post_turn_goal_hook_pauses_preempted_goal_continuation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state = self._make_state(tmpdir)
            client = FakeTelegramClient()
            state.chat_goals["tg:-1003894351534:topic:1853"] = goal_loop.GoalState(
                goal="build the thing",
                anchor_message_id=6248,
            )

            with mock.patch.object(goal_loop, "evaluate_goal_after_turn") as evaluate_after_turn:
                goal_loop.maybe_handle_goal_post_turn(
                    state=state,
                    config=make_config(),
                    client=client,
                    scope_key="tg:-1003894351534",
                    chat_id=-1003894351534,
                    message_thread_id=1853,
                    delivered_output="completed",
                    sender_name="Goal Continuation",
                    steered_follow_up_count=1,
                )

            evaluate_after_turn.assert_not_called()
            stored = state.chat_goals["tg:-1003894351534:topic:1853"]
            self.assertEqual(stored.status, "paused")
            self.assertEqual(stored.paused_reason, "user-follow-up preempted the active goal turn")
            self.assertIn("Goal paused - a real user follow-up arrived", client.messages[-1][1])
            self.assertEqual(client.messages[-1][2], 6248)

    def test_cancelled_goal_continuation_pauses_goal(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state = self._make_state(tmpdir)
            client = FakeTelegramClient()
            state.chat_goals["tg:-1003894351534:topic:1853"] = goal_loop.GoalState(
                goal="build the thing",
                anchor_message_id=6248,
            )

            goal_loop.maybe_handle_goal_turn_cancelled(
                state=state,
                client=client,
                scope_key="tg:-1003894351534",
                chat_id=-1003894351534,
                message_thread_id=1853,
                sender_name="Goal Continuation",
            )

            stored = state.chat_goals["tg:-1003894351534:topic:1853"]
            self.assertEqual(stored.status, "paused")
            self.assertEqual(stored.paused_reason, "active goal turn was canceled or interrupted by the user")
            self.assertIn("active goal turn was canceled or interrupted", client.messages[-1][1])
            self.assertEqual(client.messages[-1][2], 6248)

    def test_run_goal_judge_uses_hermes_style_prompt_sections(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state = self._make_state(tmpdir)
            client = FakeTelegramClient()
            fake_engine = mock.Mock()
            fake_engine.engine_name = "codex"
            fake_engine.run.return_value = mock.Mock(returncode=0, stdout='{"done": false, "reason": "keep going"}')

            with mock.patch(
                "telegram_bridge.request_starts.resolve_engine_for_scope",
                return_value=fake_engine,
            ):
                config = make_config()
                config.goal_judge_timeout_seconds = 9
                config.goal_judge_max_output_chars = 2222
                verdict, reason, parse_failed = goal_loop._run_goal_judge(
                    state=state,
                    config=config,
                    client=client,
                    scope_key="tg:-1003894351534:topic:1853",
                    chat_id=-1003894351534,
                    message_thread_id=1853,
                    goal_state=goal_loop.GoalState(goal="build the thing", subgoals=["include tests"]),
                    last_response="Still working on it.",
                )

            self.assertEqual((verdict, reason, parse_failed), ("continue", "keep going", False))
            judge_prompt = fake_engine.run.call_args.kwargs["prompt"]
            self.assertIn("[System Instructions]", judge_prompt)
            self.assertIn("[User Input]", judge_prompt)
            self.assertIn("Decision rule:", judge_prompt)
            engine_config = fake_engine.run.call_args.kwargs["config"]
            self.assertEqual(engine_config.exec_timeout_seconds, 9.0)
            self.assertEqual(engine_config.max_output_chars, 2222)

    def test_run_goal_judge_can_use_dedicated_judge_engine_and_overrides(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state = self._make_state(tmpdir)
            client = FakeTelegramClient()
            active_engine = mock.Mock()
            active_engine.engine_name = "codex"
            judge_engine = mock.Mock()
            judge_engine.engine_name = "gemma"
            judge_engine.run.return_value = mock.Mock(returncode=0, stdout='{"done": false, "reason": "keep going"}')
            registry = mock.Mock()
            registry.build_engine.return_value = judge_engine
            config = make_config()
            config.goal_judge_engine_plugin = "gemma"
            config.goal_judge_gemma_model = "judge-gemma"
            config.goal_judge_timeout_seconds = 12
            config.goal_judge_max_output_chars = 1337

            with mock.patch(
                "telegram_bridge.request_starts.resolve_engine_for_scope",
                return_value=active_engine,
            ), mock.patch.object(
                goal_loop,
                "build_default_plugin_registry",
                return_value=registry,
            ):
                verdict, reason, parse_failed = goal_loop._run_goal_judge(
                    state=state,
                    config=config,
                    client=client,
                    scope_key="tg:-1003894351534:topic:1853",
                    chat_id=-1003894351534,
                    message_thread_id=1853,
                    goal_state=goal_loop.GoalState(goal="build the thing"),
                    last_response="Still working on it.",
                )

            self.assertEqual((verdict, reason, parse_failed), ("continue", "keep going", False))
            registry.build_engine.assert_called_once_with("gemma")
            engine_config = judge_engine.run.call_args.kwargs["config"]
            self.assertEqual(engine_config.gemma_model, "judge-gemma")
            self.assertEqual(engine_config.exec_timeout_seconds, 12.0)
            self.assertEqual(engine_config.max_output_chars, 1337)

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
