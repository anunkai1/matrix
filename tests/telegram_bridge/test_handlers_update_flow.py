import tempfile
import unittest
from unittest import mock

from tests.telegram_bridge.test_bridge_core import (
    FakeTelegramClient,
    bridge,
    bridge_handlers,
    make_config,
)


class HandleUpdateHelperTests(unittest.TestCase):
    def _make_flow(self, **overrides):
        base = {
            "state": bridge.State(),
            "config": make_config(),
            "client": FakeTelegramClient(),
            "engine": None,
            "ctx": bridge_handlers.IncomingUpdateContext(
                update={},
                message={"text": "hello"},
                chat_id=1,
                message_thread_id=None,
                scope_key="tg:1",
                message_id=95,
                actor_user_id=1,
                is_private_chat=True,
                update_id=200,
            ),
            "prompt_input": "hello",
            "photo_file_ids": [],
            "voice_file_id": None,
            "document": None,
            "reply_context_prompt": "",
            "telegram_context_prompt": "",
            "enforce_voice_prefix_from_transcript": False,
            "sender_name": "User",
            "command": None,
            "stateless": False,
            "priority_keyword_mode": False,
            "youtube_route_url": None,
        }
        base.update(overrides)
        return bridge_handlers.UpdateFlowState(**base)

    def test_allow_update_chat_denies_non_allowlisted_group(self):
        ctx = bridge_handlers.IncomingUpdateContext(
            update={},
            message={"chat": {"id": 9, "type": "group"}},
            chat_id=9,
            message_thread_id=None,
            scope_key="tg:9",
            message_id=90,
            actor_user_id=None,
            is_private_chat=False,
            update_id=123,
        )
        config = make_config(
            allowed_chat_ids={1},
            allow_private_chats_unlisted=False,
            allow_group_chats_unlisted=False,
            denied_message="nope",
            channel_plugin="telegram",
        )
        client = FakeTelegramClient()

        allowed = bridge_handlers.allow_update_chat(ctx, config, client)

        self.assertFalse(allowed)
        self.assertEqual(client.messages[-1][:3], (9, "nope", 90))

    def test_allow_update_chat_allows_private_chat_when_unlisted_private_enabled(self):
        ctx = bridge_handlers.IncomingUpdateContext(
            update={},
            message={"chat": {"id": 9, "type": "private"}},
            chat_id=9,
            message_thread_id=None,
            scope_key="tg:9",
            message_id=91,
            actor_user_id=None,
            is_private_chat=True,
            update_id=124,
        )
        config = make_config(
            allowed_chat_ids={1},
            allow_private_chats_unlisted=True,
            allow_group_chats_unlisted=False,
        )
        client = FakeTelegramClient()

        allowed = bridge_handlers.allow_update_chat(ctx, config, client)

        self.assertTrue(allowed)
        self.assertEqual(client.messages, [])

    def test_prepare_update_request_ignores_missing_required_prefix(self):
        config = make_config(
            required_prefixes=["architect"],
            require_prefix_in_private=True,
            allow_private_chats_unlisted=True,
        )
        client = FakeTelegramClient()
        ctx = bridge_handlers.IncomingUpdateContext(
            update={},
            message={
                "message_id": 92,
                "chat": {"id": 1, "type": "private"},
                "from": {"id": 1, "first_name": "User"},
                "text": "hello there",
            },
            chat_id=1,
            message_thread_id=None,
            scope_key="tg:1",
            message_id=92,
            actor_user_id=1,
            is_private_chat=True,
            update_id=125,
        )

        prepared = bridge_handlers.prepare_update_request(bridge.State(), config, client, ctx)

        self.assertIsNone(prepared)
        self.assertEqual(client.messages, [])

    def test_maybe_handle_diary_update_flow_queues_capture_when_no_command_handled(self):
        flow = bridge_handlers.UpdateFlowState(
            state=bridge.State(),
            config=make_config(diary_mode_enabled=True),
            client=FakeTelegramClient(),
            engine=None,
            ctx=bridge_handlers.IncomingUpdateContext(
                update={},
                message={"text": "Diary note"},
                chat_id=1,
                message_thread_id=None,
                scope_key="tg:1",
                message_id=93,
                actor_user_id=7,
                is_private_chat=True,
                update_id=126,
            ),
            prompt_input="Diary note",
            photo_file_ids=[],
            voice_file_id=None,
            document=None,
            reply_context_prompt="",
            telegram_context_prompt="",
            enforce_voice_prefix_from_transcript=False,
            sender_name="User",
            command=None,
        )

        with mock.patch.object(bridge_handlers, "handle_known_command", return_value=False) as known:
            with mock.patch.object(bridge_handlers, "queue_diary_capture") as queue_capture:
                handled = bridge_handlers.maybe_handle_diary_update_flow(flow)

        self.assertTrue(handled)
        known.assert_called_once()
        queue_capture.assert_called_once()

    def test_prepare_update_dispatch_request_handles_memory_recall_without_dispatch(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            memory_engine = bridge.MemoryEngine(f"{tmpdir}/memory.sqlite3")
            flow = bridge_handlers.UpdateFlowState(
                state=bridge.State(memory_engine=memory_engine),
                config=make_config(shared_memory_key="shared:architect:main"),
                client=FakeTelegramClient(),
                engine=None,
                ctx=bridge_handlers.IncomingUpdateContext(
                    update={},
                    message={"text": "what do you remember"},
                    chat_id=1,
                    message_thread_id=None,
                    scope_key="tg:1",
                    message_id=94,
                    actor_user_id=1,
                    is_private_chat=True,
                    update_id=127,
                ),
                prompt_input="what do you remember",
                photo_file_ids=[],
                voice_file_id=None,
                document=None,
                reply_context_prompt="",
                telegram_context_prompt="",
                enforce_voice_prefix_from_transcript=False,
                sender_name="User",
                command=None,
            )

            with mock.patch.object(
                bridge_handlers,
                "handle_natural_language_memory_query",
                return_value="Memory reply",
            ) as recall:
                dispatch = bridge_handlers.prepare_update_dispatch_request(flow, 10.0)

        self.assertIsNone(dispatch)
        recall.assert_called_once()
        self.assertEqual(flow.client.messages[-1][:3], (1, "Memory reply", 94))

    def test_prepare_update_dispatch_request_routes_youtube_keyword_mode(self):
        flow = self._make_flow(
            prompt_input="watch this",
            command="/yt",
        )

        keyword_result = mock.Mock(
            rejection_reason=None,
            rejection_message=None,
            prompt_input="watch this",
            command="/yt",
            priority_keyword_mode=True,
            stateless=True,
            route_kind="youtube_link",
            route_value="https://youtube.example/watch?v=1",
            routed_event="bridge.keyword_routed",
        )

        with mock.patch.object(
            bridge_handlers,
            "apply_priority_keyword_routing",
            return_value=keyword_result,
        ):
            dispatch = bridge_handlers.prepare_update_dispatch_request(flow, 11.0)

        self.assertIsNotNone(dispatch)
        self.assertTrue(dispatch.stateless)
        self.assertEqual(dispatch.youtube_route_url, "https://youtube.example/watch?v=1")

    def test_prepare_update_dispatch_request_omits_context_when_raw_prompt_fits_limit(self):
        flow = self._make_flow(
            config=make_config(max_input_chars=20),
            prompt_input="short prompt",
            telegram_context_prompt="telegram context",
            reply_context_prompt="reply context",
        )

        with mock.patch.object(bridge_handlers, "emit_event") as emit_event:
            dispatch = bridge_handlers.prepare_update_dispatch_request(flow, 12.0)

        self.assertIsNotNone(dispatch)
        self.assertEqual(dispatch.prompt, "short prompt")
        self.assertEqual(dispatch.raw_prompt, "short prompt")
        self.assertTrue(
            any(
                call.args and call.args[0] == "bridge.telegram_context_omitted"
                for call in emit_event.call_args_list
            )
        )

    def test_prepare_update_dispatch_request_rejects_rate_limited_request(self):
        flow = self._make_flow()

        with mock.patch.object(bridge_handlers, "is_rate_limited", return_value=True):
            dispatch = bridge_handlers.prepare_update_dispatch_request(flow, 13.0)

        self.assertIsNone(dispatch)
        self.assertEqual(flow.client.messages[-1][:3], (1, bridge_handlers.RATE_LIMIT_MESSAGE, 95))

    def test_start_standard_dispatch_routes_to_message_worker(self):
        flow = self._make_flow(prompt_input="hello")
        dispatch = bridge_handlers.UpdateDispatchRequest(
            state=flow.state,
            config=flow.config,
            client=flow.client,
            engine=None,
            scope_key=flow.ctx.scope_key,
            chat_id=flow.ctx.chat_id,
            message_thread_id=flow.ctx.message_thread_id,
            message_id=flow.ctx.message_id,
            prompt="hello",
            raw_prompt="hello",
            photo_file_ids=[],
            voice_file_id=None,
            document=None,
            actor_user_id=flow.ctx.actor_user_id,
            sender_name=flow.sender_name,
            stateless=False,
            enforce_voice_prefix_from_transcript=False,
            youtube_route_url=None,
            handle_update_started_at=14.0,
        )

        with mock.patch.object(bridge_handlers, "resolve_engine_for_scope", return_value=object()):
            with mock.patch.object(bridge_handlers, "ensure_chat_worker_session", return_value=True):
                with mock.patch.object(bridge_handlers, "start_message_worker") as start_message_worker:
                    started = bridge_handlers.start_standard_dispatch(dispatch)

        self.assertTrue(started)
        start_message_worker.assert_called_once()

    def test_start_dishframed_dispatch_uses_recent_scope_photos(self):
        flow = self._make_flow()
        dispatch = bridge_handlers.UpdateDispatchRequest(
            state=flow.state,
            config=flow.config,
            client=flow.client,
            engine=None,
            scope_key=flow.ctx.scope_key,
            chat_id=flow.ctx.chat_id,
            message_thread_id=flow.ctx.message_thread_id,
            message_id=flow.ctx.message_id,
            prompt="",
            raw_prompt="",
            photo_file_ids=[],
            voice_file_id=None,
            document=None,
            actor_user_id=flow.ctx.actor_user_id,
            sender_name=flow.sender_name,
            stateless=True,
            enforce_voice_prefix_from_transcript=False,
            youtube_route_url=None,
            handle_update_started_at=15.0,
        )

        with mock.patch.object(bridge_handlers, "get_recent_scope_photos", return_value=["photo-1"]) as recent:
            with mock.patch.object(bridge_handlers, "start_dishframed_worker") as start_worker:
                started = bridge_handlers.start_dishframed_dispatch(dispatch)

        self.assertTrue(started)
        recent.assert_called_once()
        start_worker.assert_called_once()


if __name__ == "__main__":
    unittest.main()
