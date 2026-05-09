import unittest
from unittest import mock

from telegram_bridge.executor import ExecutorProgressEvent
from telegram_bridge import handler_progress


class FakeClient:
    supports_message_edits = True
    channel_name = "telegram"

    def __init__(self):
        self.edits = []
        self.actions = []

    def edit_message(self, chat_id, message_id, text):
        self.edits.append((chat_id, message_id, text))

    def send_chat_action(self, chat_id, action, message_thread_id=None):
        self.actions.append((chat_id, action, message_thread_id))


class HandlerProgressTests(unittest.TestCase):
    def test_handle_executor_event_tracks_command_counts_and_success_text(self):
        reporter = handler_progress.ProgressReporter(
            client=FakeClient(),
            chat_id=1,
            reply_to_message_id=5,
            message_thread_id=None,
            assistant_name="Architect",
        )

        reporter.handle_executor_event(
            ExecutorProgressEvent(kind="command_started", detail="pytest", exit_code=None)
        )
        reporter.handle_executor_event(
            ExecutorProgressEvent(kind="command_completed", detail=None, exit_code=0)
        )

        self.assertEqual(reporter.commands_started, 1)
        self.assertEqual(reporter.commands_completed, 1)
        self.assertEqual(reporter.phase, "A command finished successfully.")

    def test_handle_executor_event_uses_reasoning_fallback_text(self):
        reporter = handler_progress.ProgressReporter(
            client=FakeClient(),
            chat_id=1,
            reply_to_message_id=5,
            message_thread_id=None,
            assistant_name="Oracle",
        )

        reporter.handle_executor_event(
            ExecutorProgressEvent(kind="reasoning", detail="", exit_code=None)
        )

        self.assertEqual(reporter.phase, "Oracle is reasoning.")

    def test_maybe_edit_clears_pending_update_when_text_is_unchanged(self):
        reporter = handler_progress.ProgressReporter(
            client=FakeClient(),
            chat_id=1,
            reply_to_message_id=5,
            message_thread_id=None,
            assistant_name="Architect",
        )
        reporter.progress_message_id = 101
        reporter.pending_update = True
        reporter.last_edit_at = 0.0
        reporter.last_rendered_text = "same"

        with mock.patch.object(reporter, "_render_progress_text", return_value="same"):
            reporter._maybe_edit(force=False)

        self.assertFalse(reporter.pending_update)
        self.assertEqual(reporter.edit_attempts, 0)

    def test_maybe_edit_clears_pending_update_when_forced_text_is_unchanged(self):
        reporter = handler_progress.ProgressReporter(
            client=FakeClient(),
            chat_id=1,
            reply_to_message_id=5,
            message_thread_id=None,
            assistant_name="Architect",
        )
        reporter.progress_message_id = 101
        reporter.pending_update = True
        reporter.last_rendered_text = "same"

        with mock.patch.object(reporter, "_render_progress_text", return_value="same"):
            reporter._maybe_edit(force=True)

        self.assertFalse(reporter.pending_update)
        self.assertEqual(reporter.edit_attempts, 0)

    def test_maybe_edit_counts_not_modified_runtime_error_as_400(self):
        client = FakeClient()
        client.edit_message = mock.Mock(side_effect=RuntimeError("Message is not modified"))
        reporter = handler_progress.ProgressReporter(
            client=client,
            chat_id=1,
            reply_to_message_id=5,
            message_thread_id=None,
            assistant_name="Architect",
        )
        reporter.progress_message_id = 101
        reporter.pending_update = True

        reporter._maybe_edit(force=True)

        self.assertEqual(reporter.edit_failures_400, 1)
        self.assertFalse(reporter.pending_update)
        self.assertEqual(reporter.edit_failures_other, 0)

    def test_compact_progress_uses_bucketed_elapsed_and_slower_cadence(self):
        reporter = handler_progress.ProgressReporter(
            client=FakeClient(),
            chat_id=1,
            reply_to_message_id=5,
            message_thread_id=None,
            assistant_name="Architect",
            progress_label="Architect is thinking",
        )
        reporter.started_at = 100.0

        with mock.patch.object(handler_progress.time, "time", return_value=112.0):
            self.assertEqual(
                reporter._render_progress_text(),
                "Architect is thinking... Already 10s",
            )

        self.assertEqual(
            reporter._edit_min_interval_seconds,
            handler_progress.COMPACT_PROGRESS_EDIT_MIN_INTERVAL_SECONDS,
        )
        self.assertEqual(
            reporter._heartbeat_edit_seconds,
            handler_progress.COMPACT_PROGRESS_HEARTBEAT_EDIT_SECONDS,
        )

    def test_close_emits_stats_after_forced_final_edit(self):
        reporter = handler_progress.ProgressReporter(
            client=FakeClient(),
            chat_id=1,
            reply_to_message_id=5,
            message_thread_id=None,
            assistant_name="Architect",
        )
        reporter.progress_message_id = 202
        reporter._worker = mock.Mock()

        with mock.patch.object(reporter, "_maybe_edit") as maybe_edit, mock.patch.object(
            handler_progress,
            "emit_event",
        ) as emit_event:
            reporter.close()

        reporter._worker.join.assert_called_once_with(timeout=2.0)
        maybe_edit.assert_called_once_with(force=True)
        emit_event.assert_called_once()
        self.assertEqual(emit_event.call_args.args[0], "bridge.progress_edit_stats")


if __name__ == "__main__":
    unittest.main()
