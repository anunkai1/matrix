import tempfile
import unittest
from unittest import mock

from tests.telegram_bridge.helpers import (
    FakeTelegramClient,
    make_config,
)

import telegram_bridge.handlers as bridge_handlers
import telegram_bridge.bridge_runtime_setup as bridge_runtime_setup
import telegram_bridge.main as bridge
import telegram_bridge.update_preparation as update_preparation
import telegram_bridge.update_flow as update_flow
from telegram_bridge.handler_models import TelegramDeliveryMetadata


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

    def test_prepare_update_request_bootstraps_telegram_context_for_fresh_codex_scope(self):
        state = bridge.State()
        config = make_config()
        client = FakeTelegramClient()
        ctx = bridge_handlers.IncomingUpdateContext(
            update={},
            message={
                "message_id": 120,
                "chat": {"id": 1, "type": "private"},
                "from": {"id": 1, "first_name": "User"},
                "text": "hello there",
            },
            chat_id=1,
            message_thread_id=None,
            scope_key="tg:1",
            message_id=120,
            actor_user_id=1,
            is_private_chat=True,
            update_id=220,
        )

        prepared = bridge_handlers.prepare_update_request(state, config, client, ctx)

        self.assertIsNotNone(prepared)
        self.assertIn("Current Telegram Context:", prepared.telegram_context_prompt)
        self.assertIn("use this chat/topic only", prepared.telegram_context_prompt)
        self.assertEqual(prepared.delivery_metadata.chat_id, 1)
        self.assertEqual(prepared.delivery_metadata.scope_key, "tg:1")
        self.assertEqual(prepared.delivery_metadata.current_message_id, 120)
        self.assertIsNone(prepared.delivery_metadata.reply_to_message_id)

    def test_prepare_update_request_skips_bootstrap_reinjection_for_continuation_codex_turn(self):
        state = bridge.State()
        state.chat_threads["tg:1"] = "thread-1"
        config = make_config()
        client = FakeTelegramClient()
        ctx = bridge_handlers.IncomingUpdateContext(
            update={},
            message={
                "message_id": 121,
                "chat": {"id": 1, "type": "private"},
                "from": {"id": 1, "first_name": "User"},
                "text": "hello again",
            },
            chat_id=1,
            message_thread_id=None,
            scope_key="tg:1",
            message_id=121,
            actor_user_id=1,
            is_private_chat=True,
            update_id=221,
        )

        prepared = bridge_handlers.prepare_update_request(state, config, client, ctx)

        self.assertIsNotNone(prepared)
        self.assertEqual(prepared.telegram_context_prompt, "")

    def test_prepare_update_request_reinjects_after_thread_reset(self):
        state = bridge.State()
        state.chat_threads["tg:1"] = "thread-1"
        del state.chat_threads["tg:1"]
        config = make_config()
        client = FakeTelegramClient()
        ctx = bridge_handlers.IncomingUpdateContext(
            update={},
            message={
                "message_id": 122,
                "chat": {"id": 1, "type": "private"},
                "from": {"id": 1, "first_name": "User"},
                "text": "new thread now",
            },
            chat_id=1,
            message_thread_id=None,
            scope_key="tg:1",
            message_id=122,
            actor_user_id=1,
            is_private_chat=True,
            update_id=222,
        )

        prepared = bridge_handlers.prepare_update_request(state, config, client, ctx)

        self.assertIsNotNone(prepared)
        self.assertIn("Current Telegram Context:", prepared.telegram_context_prompt)
        self.assertIn("use this chat/topic only", prepared.telegram_context_prompt)

    def test_prepare_update_request_captures_reply_anchor_metadata(self):
        state = bridge.State()
        config = make_config()
        client = FakeTelegramClient()
        ctx = bridge_handlers.IncomingUpdateContext(
            update={},
            message={
                "message_id": 124,
                "chat": {"id": 1, "type": "private"},
                "from": {"id": 1, "first_name": "User"},
                "reply_to_message": {"message_id": 777},
                "text": "continue there",
            },
            chat_id=1,
            message_thread_id=None,
            scope_key="tg:1",
            message_id=124,
            actor_user_id=1,
            is_private_chat=True,
            update_id=224,
        )

        prepared = bridge_handlers.prepare_update_request(state, config, client, ctx)

        self.assertIsNotNone(prepared)
        self.assertEqual(prepared.delivery_metadata.current_message_id, 124)
        self.assertEqual(prepared.delivery_metadata.reply_to_message_id, 777)

    def test_prepare_update_request_reinjects_delivery_sensitive_continuation(self):
        state = bridge.State()
        state.chat_threads["tg:1"] = "thread-1"
        config = make_config()
        client = FakeTelegramClient()
        ctx = bridge_handlers.IncomingUpdateContext(
            update={},
            message={
                "message_id": 123,
                "chat": {"id": 1, "type": "private"},
                "from": {"id": 1, "first_name": "User"},
                "text": "send it here",
            },
            chat_id=1,
            message_thread_id=None,
            scope_key="tg:1",
            message_id=123,
            actor_user_id=1,
            is_private_chat=True,
            update_id=223,
        )

        prepared = bridge_handlers.prepare_update_request(state, config, client, ctx)

        self.assertIsNotNone(prepared)
        self.assertIn("Current Telegram Context:", prepared.telegram_context_prompt)
        self.assertIn("use this chat/topic only", prepared.telegram_context_prompt)

    def test_prepare_update_request_includes_referenced_message_context_for_explicit_message_id(self):
        state = bridge.State()
        config = make_config()
        client = FakeTelegramClient()
        prior_ctx = bridge_handlers.IncomingUpdateContext(
            update={},
            message={
                "message_id": 777,
                "chat": {"id": 1, "type": "private"},
                "from": {"id": 9, "first_name": "Alice"},
                "text": "Please send the report tomorrow.",
            },
            chat_id=1,
            message_thread_id=None,
            scope_key="tg:1",
            message_id=777,
            actor_user_id=9,
            is_private_chat=True,
            update_id=300,
        )
        bridge_handlers.prepare_update_request(state, config, client, prior_ctx)

        ctx = bridge_handlers.IncomingUpdateContext(
            update={},
            message={
                "message_id": 123,
                "chat": {"id": 1, "type": "private"},
                "from": {"id": 1, "first_name": "User"},
                "text": "use message id 777",
            },
            chat_id=1,
            message_thread_id=None,
            scope_key="tg:1",
            message_id=123,
            actor_user_id=1,
            is_private_chat=True,
            update_id=301,
        )

        prepared = bridge_handlers.prepare_update_request(state, config, client, ctx)

        self.assertIsNotNone(prepared)
        self.assertIn("Referenced Telegram Message:", prepared.reply_context_prompt)
        self.assertIn("Referenced Telegram Message ID: 777", prepared.reply_context_prompt)
        self.assertIn("Referenced Message Author: Alice", prepared.reply_context_prompt)
        self.assertIn("Please send the report tomorrow.", prepared.reply_context_prompt)

    def test_prepare_update_request_keeps_referenced_message_lookup_scope_local_to_topic(self):
        state = bridge.State()
        config = make_config()
        client = FakeTelegramClient()
        prior_ctx = bridge_handlers.IncomingUpdateContext(
            update={},
            message={
                "message_id": 777,
                "chat": {"id": 1, "type": "supergroup"},
                "message_thread_id": 498,
                "is_topic_message": True,
                "from": {"id": 9, "first_name": "Alice"},
                "text": "Topic-local message.",
            },
            chat_id=1,
            message_thread_id=498,
            scope_key="tg:1:topic:498",
            message_id=777,
            actor_user_id=9,
            is_private_chat=False,
            update_id=310,
        )
        bridge_handlers.prepare_update_request(state, config, client, prior_ctx)

        ctx = bridge_handlers.IncomingUpdateContext(
            update={},
            message={
                "message_id": 124,
                "chat": {"id": 1, "type": "supergroup"},
                "message_thread_id": 499,
                "is_topic_message": True,
                "from": {"id": 1, "first_name": "User"},
                "text": "use message id 777",
            },
            chat_id=1,
            message_thread_id=499,
            scope_key="tg:1:topic:499",
            message_id=124,
            actor_user_id=1,
            is_private_chat=False,
            update_id=311,
        )

        prepared = bridge_handlers.prepare_update_request(state, config, client, ctx)

        self.assertIsNotNone(prepared)
        self.assertNotIn("Referenced Telegram Message:", prepared.reply_context_prompt)

    def test_prepare_update_request_keeps_always_policy_for_non_codex_scope(self):
        state = bridge.State()
        state.chat_threads["tg:1"] = "thread-1"
        state.chat_engines["tg:1"] = "pi"
        config = make_config()
        client = FakeTelegramClient()
        ctx = bridge_handlers.IncomingUpdateContext(
            update={},
            message={
                "message_id": 124,
                "chat": {"id": 1, "type": "private"},
                "from": {"id": 1, "first_name": "User"},
                "text": "hello pi",
            },
            chat_id=1,
            message_thread_id=None,
            scope_key="tg:1",
            message_id=124,
            actor_user_id=1,
            is_private_chat=True,
            update_id=224,
        )

        prepared = bridge_handlers.prepare_update_request(state, config, client, ctx)

        self.assertIsNotNone(prepared)
        self.assertIn("Current Telegram Context:", prepared.telegram_context_prompt)
        self.assertNotIn("use this chat/topic only", prepared.telegram_context_prompt)

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

        with mock.patch.object(bridge_runtime_setup, "handle_known_command", return_value=False) as known:
            with mock.patch.object(bridge_runtime_setup, "queue_diary_capture") as queue_capture:
                handled = bridge_handlers.maybe_handle_diary_update_flow(flow)

        self.assertTrue(handled)
        known.assert_called_once()
        queue_capture.assert_called_once()

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
            update_preparation,
            "apply_priority_keyword_routing",
            return_value=keyword_result,
        ):
            dispatch = bridge_handlers.prepare_update_dispatch_request(flow, 11.0)

        self.assertIsNotNone(dispatch)
        self.assertTrue(dispatch.stateless)
        self.assertEqual(dispatch.youtube_route_url, "https://youtube.example/watch?v=1")

    def test_prepare_update_dispatch_request_preserves_telegram_context_and_drops_lower_priority_sections(self):
        flow = self._make_flow(
            config=make_config(max_input_chars=20),
            prompt_input="short prompt",
            telegram_context_prompt="telegram context",
            reply_context_prompt="reply context",
            sender_name="Tank",
        )

        with mock.patch.object(update_preparation, "emit_event") as emit_event:
            dispatch = bridge_handlers.prepare_update_dispatch_request(flow, 12.0)

        self.assertIsNotNone(dispatch)
        self.assertEqual(dispatch.prompt, "telegram context")
        self.assertEqual(dispatch.raw_prompt, "short prompt")
        self.assertEqual(dispatch.prompt_diagnostics["dropped_sections"], ["current_sender", "reply_context"])
        self.assertEqual(dispatch.prompt_diagnostics["trimmed_user_chars"], len("short prompt"))
        self.assertEqual(flow.client.messages[-1][:3], (1, mock.ANY, 95))
        self.assertIn("Dropped sections: current_sender, reply_context", flow.client.messages[-1][1])
        self.assertIn("User-message chars trimmed: 12", flow.client.messages[-1][1])
        self.assertTrue(
            any(
                call.args and call.args[0] == "bridge.prompt_trimmed"
                for call in emit_event.call_args_list
            )
        )

    def test_prepare_update_dispatch_request_includes_current_sender_name(self):
        flow = self._make_flow(
            prompt_input="hello",
            sender_name="Tank",
            telegram_context_prompt="Current Telegram Context:\n- Chat ID: 1",
        )

        dispatch = bridge_handlers.prepare_update_dispatch_request(flow, 12.5)

        self.assertIsNotNone(dispatch)
        self.assertIn("Author: Tank", dispatch.prompt)
        self.assertIn("Current User Message:\nhello", dispatch.prompt)

    def test_prepare_update_dispatch_request_preserves_delivery_metadata(self):
        delivery_metadata = TelegramDeliveryMetadata(
            chat_id=1,
            scope_key="tg:1",
            message_thread_id=None,
            current_message_id=95,
            reply_to_message_id=90,
        )
        flow = self._make_flow(delivery_metadata=delivery_metadata)

        dispatch = bridge_handlers.prepare_update_dispatch_request(flow, 12.5)

        self.assertIsNotNone(dispatch)
        self.assertIs(dispatch.delivery_metadata, delivery_metadata)

    def test_build_prompt_with_diagnostics_reports_section_lengths(self):
        details = update_preparation._build_prompt_with_diagnostics(
            raw_prompt="hello",
            telegram_context_prompt="Current Telegram Context:\n- Chat ID: 1",
            reply_context_prompt="Reply Context:\nOriginal Telegram Message ID: 90",
            sender_name="Tank",
            max_input_chars=4096,
        )

        self.assertEqual(details["telegram_context_length"], len("Current Telegram Context:\n- Chat ID: 1"))
        self.assertEqual(
            details["reply_context_length"],
            len("Reply Context:\nOriginal Telegram Message ID: 90"),
        )
        self.assertEqual(details["sender_prompt_length"], len("Author: Tank"))
        self.assertEqual(details["user_message_label_length"], len("Current User Message:\n"))
        self.assertEqual(
            details["wrapper_overhead"],
            len("Current User Message:\n") + 8,
        )
        self.assertFalse(details["trimmed"])

    def test_prepare_update_dispatch_request_rejects_rate_limited_request(self):
        flow = self._make_flow()

        with mock.patch.object(update_preparation, "is_rate_limited", return_value=True):
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

        with mock.patch.object(bridge_runtime_setup, "resolve_engine_for_scope", return_value=object()):
            with mock.patch.object(bridge_runtime_setup, "ensure_chat_worker_session", return_value=True):
                with mock.patch.object(bridge_runtime_setup, "start_message_worker") as start_message_worker:
                    started = bridge_handlers.start_standard_dispatch(dispatch)

        self.assertTrue(started)
        start_message_worker.assert_called_once()

    def test_start_standard_dispatch_rejects_when_engine_resolution_fails(self):
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
            handle_update_started_at=17.0,
        )

        with mock.patch.object(
            bridge_runtime_setup,
            "resolve_engine_for_scope",
            side_effect=RuntimeError("boom"),
        ):
            started = bridge_handlers.start_standard_dispatch(dispatch)

        self.assertFalse(started)
        self.assertIn("Engine selection failed", flow.client.messages[-1][1])

    def test_start_standard_dispatch_rejects_when_worker_capacity_unavailable(self):
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
            handle_update_started_at=18.0,
        )

        with mock.patch.object(bridge_runtime_setup, "resolve_engine_for_scope", return_value=object()):
            with mock.patch.object(bridge_runtime_setup, "ensure_chat_worker_session", return_value=False):
                started = bridge_handlers.start_standard_dispatch(dispatch)

        self.assertFalse(started)
        self.assertEqual(flow.client.messages, [])

    def test_start_standard_dispatch_waits_out_stale_busy_after_live_codex_turn(self):
        flow = self._make_flow(prompt_input="hello")
        flow.state.busy_chats.add(flow.ctx.scope_key)
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
            handle_update_started_at=18.5,
        )

        active_engine = mock.Mock()
        active_engine.engine_name = "codex"

        def clear_busy_after_short_wait(_seconds):
            flow.state.busy_chats.discard(flow.ctx.scope_key)

        with mock.patch.object(bridge_runtime_setup, "resolve_engine_for_scope", return_value=active_engine):
            with mock.patch.object(bridge_runtime_setup, "ensure_chat_worker_session", return_value=True):
                with mock.patch.object(bridge_runtime_setup, "live_codex_turn_is_active", return_value=False):
                    with mock.patch.object(bridge_runtime_setup, "start_message_worker") as start_message_worker:
                        with mock.patch("telegram_bridge.update_flow.time.sleep", side_effect=clear_busy_after_short_wait):
                            started = bridge_handlers.start_standard_dispatch(dispatch)

        self.assertTrue(started)
        start_message_worker.assert_called_once()
        self.assertEqual(flow.client.messages, [])

    def test_start_standard_dispatch_cancels_stale_busy_request_and_continues(self):
        flow = self._make_flow(prompt_input="hello")
        flow.state.busy_chats.add(flow.ctx.scope_key)
        flow.state.in_flight_requests[flow.ctx.scope_key] = {"started_at": 1.0, "message_id": 94}
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
            handle_update_started_at=18.75,
        )

        active_engine = mock.Mock()
        active_engine.engine_name = "codex"

        def clear_busy_after_cancel(_seconds):
            flow.state.busy_chats.discard(flow.ctx.scope_key)

        with mock.patch.object(bridge_runtime_setup, "resolve_engine_for_scope", return_value=active_engine):
            with mock.patch.object(bridge_runtime_setup, "ensure_chat_worker_session", return_value=True):
                with mock.patch.object(bridge_runtime_setup, "live_codex_turn_is_active", return_value=None):
                    with mock.patch.object(bridge_runtime_setup, "request_chat_cancel", return_value="requested") as request_chat_cancel:
                        with mock.patch.object(bridge_runtime_setup, "start_message_worker") as start_message_worker:
                            with mock.patch("telegram_bridge.update_flow.time.time", return_value=305.0):
                                with mock.patch("telegram_bridge.update_flow.time.sleep", side_effect=clear_busy_after_cancel):
                                    started = bridge_handlers.start_standard_dispatch(dispatch)

        self.assertTrue(started)
        request_chat_cancel.assert_called_once_with(flow.state, flow.ctx.scope_key)
        start_message_worker.assert_called_once()
        self.assertEqual(flow.client.messages, [])

    def test_start_standard_dispatch_steers_active_live_codex_turn_for_direct_scope(self):
        self._assert_busy_live_codex_follow_up(
            scope_key="tg:1",
            chat_id=1,
            message_thread_id=None,
            expect_thread_id=None,
        )

    def test_start_standard_dispatch_steers_active_live_codex_turn_for_group_scope(self):
        self._assert_busy_live_codex_follow_up(
            scope_key="tg:-1001",
            chat_id=-1001,
            message_thread_id=None,
            expect_thread_id=None,
        )

    def test_start_standard_dispatch_steers_active_live_codex_turn_for_topic_scope(self):
        self._assert_busy_live_codex_follow_up(
            scope_key="tg:-1001:topic:77",
            chat_id=-1001,
            message_thread_id=77,
            expect_thread_id=77,
        )

    def test_start_standard_dispatch_rejects_non_text_follow_up_during_active_live_codex_turn(self):
        flow = self._make_flow(
            prompt_input="",
            photo_file_ids=["photo-1"],
            ctx=bridge_handlers.IncomingUpdateContext(
                update={},
                message={"photo": [{"file_id": "photo-1"}]},
                chat_id=-1001,
                message_thread_id=77,
                scope_key="tg:-1001:topic:77",
                message_id=96,
                actor_user_id=1,
                is_private_chat=False,
                update_id=201,
            ),
        )
        flow.state.busy_chats.add(flow.ctx.scope_key)
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
            photo_file_ids=["photo-1"],
            voice_file_id=None,
            document=None,
            actor_user_id=flow.ctx.actor_user_id,
            sender_name=flow.sender_name,
            stateless=False,
            enforce_voice_prefix_from_transcript=False,
            youtube_route_url=None,
            handle_update_started_at=19.1,
        )

        active_engine = mock.Mock()
        active_engine.engine_name = "codex"

        with mock.patch.object(bridge_runtime_setup, "resolve_engine_for_scope", return_value=active_engine):
            with mock.patch.object(bridge_runtime_setup, "live_codex_turn_is_active", return_value=True):
                with mock.patch.object(bridge_runtime_setup, "try_steer_live_codex_turn") as try_steer:
                    with mock.patch.object(bridge_runtime_setup, "start_message_worker") as start_message_worker:
                        started = bridge_handlers.start_standard_dispatch(dispatch)

        self.assertTrue(started)
        try_steer.assert_not_called()
        start_message_worker.assert_not_called()
        self.assertEqual(
            flow.client.messages[-1],
            (
                -1001,
                update_flow.LIVE_CODEX_STEER_UNSUPPORTED_MESSAGE,
                96,
                None,
            ),
        )

    def test_start_standard_dispatch_surfaces_failed_text_steer_without_busy_reply(self):
        flow = self._make_flow(prompt_input="follow up")
        flow.state.busy_chats.add(flow.ctx.scope_key)
        dispatch = bridge_handlers.UpdateDispatchRequest(
            state=flow.state,
            config=flow.config,
            client=flow.client,
            engine=None,
            scope_key=flow.ctx.scope_key,
            chat_id=flow.ctx.chat_id,
            message_thread_id=flow.ctx.message_thread_id,
            message_id=flow.ctx.message_id,
            prompt="follow up",
            raw_prompt="follow up",
            photo_file_ids=[],
            voice_file_id=None,
            document=None,
            actor_user_id=flow.ctx.actor_user_id,
            sender_name=flow.sender_name,
            stateless=False,
            enforce_voice_prefix_from_transcript=False,
            youtube_route_url=None,
            handle_update_started_at=19.2,
        )

        active_engine = mock.Mock()
        active_engine.engine_name = "codex"

        with mock.patch.object(bridge_runtime_setup, "resolve_engine_for_scope", return_value=active_engine):
            with mock.patch.object(bridge_runtime_setup, "try_steer_live_codex_turn", return_value=False):
                with mock.patch.object(bridge_runtime_setup, "live_codex_turn_is_active", return_value=True):
                    started = bridge_handlers.start_standard_dispatch(dispatch)

        self.assertTrue(started)
        self.assertEqual(
            flow.client.messages[-1],
            (1, update_flow.LIVE_CODEX_STEER_FAILED_MESSAGE, 95, None),
        )
        self.assertNotEqual(flow.client.messages[-1][1], flow.config.busy_message)

    def test_start_standard_dispatch_steers_with_raw_follow_up_not_wrapped_prompt(self):
        flow = self._make_flow(prompt_input="follow up")
        flow.state.busy_chats.add(flow.ctx.scope_key)
        dispatch = bridge_handlers.UpdateDispatchRequest(
            state=flow.state,
            config=flow.config,
            client=flow.client,
            engine=None,
            scope_key=flow.ctx.scope_key,
            chat_id=flow.ctx.chat_id,
            message_thread_id=flow.ctx.message_thread_id,
            message_id=flow.ctx.message_id,
            prompt="Current Telegram Context:\n- Chat ID: 1\n\nCurrent User Message:\nfollow up",
            raw_prompt="follow up",
            photo_file_ids=[],
            voice_file_id=None,
            document=None,
            actor_user_id=flow.ctx.actor_user_id,
            sender_name=flow.sender_name,
            stateless=False,
            enforce_voice_prefix_from_transcript=False,
            youtube_route_url=None,
            handle_update_started_at=19.25,
        )

        active_engine = mock.Mock()
        active_engine.engine_name = "codex"

        with mock.patch.object(bridge_runtime_setup, "resolve_engine_for_scope", return_value=active_engine):
            with mock.patch.object(bridge_runtime_setup, "try_steer_live_codex_turn", return_value=True) as try_steer:
                started = bridge_handlers.start_standard_dispatch(dispatch)

        self.assertTrue(started)
        try_steer.assert_called_once_with(flow.config, flow.ctx.scope_key, "follow up")

    def test_start_standard_dispatch_allows_multiple_follow_ups_during_same_busy_live_turn(self):
        flow = self._make_flow(prompt_input="first follow up")
        flow.state.busy_chats.add(flow.ctx.scope_key)
        first_dispatch = bridge_handlers.UpdateDispatchRequest(
            state=flow.state,
            config=flow.config,
            client=flow.client,
            engine=None,
            scope_key=flow.ctx.scope_key,
            chat_id=flow.ctx.chat_id,
            message_thread_id=flow.ctx.message_thread_id,
            message_id=95,
            prompt="first follow up",
            raw_prompt="first follow up",
            photo_file_ids=[],
            voice_file_id=None,
            document=None,
            actor_user_id=flow.ctx.actor_user_id,
            sender_name=flow.sender_name,
            stateless=False,
            enforce_voice_prefix_from_transcript=False,
            youtube_route_url=None,
            handle_update_started_at=20.0,
        )
        second_dispatch = bridge_handlers.UpdateDispatchRequest(
            state=flow.state,
            config=flow.config,
            client=flow.client,
            engine=None,
            scope_key=flow.ctx.scope_key,
            chat_id=flow.ctx.chat_id,
            message_thread_id=flow.ctx.message_thread_id,
            message_id=96,
            prompt="second follow up",
            raw_prompt="second follow up",
            photo_file_ids=[],
            voice_file_id=None,
            document=None,
            actor_user_id=flow.ctx.actor_user_id,
            sender_name=flow.sender_name,
            stateless=False,
            enforce_voice_prefix_from_transcript=False,
            youtube_route_url=None,
            handle_update_started_at=20.1,
        )

        active_engine = mock.Mock()
        active_engine.engine_name = "codex"

        with mock.patch.object(bridge_runtime_setup, "resolve_engine_for_scope", return_value=active_engine):
            with mock.patch.object(bridge_runtime_setup, "try_steer_live_codex_turn", side_effect=[True, True]) as try_steer:
                with mock.patch.object(bridge_runtime_setup, "start_message_worker") as start_message_worker:
                    first_started = bridge_handlers.start_standard_dispatch(first_dispatch)
                    second_started = bridge_handlers.start_standard_dispatch(second_dispatch)

        self.assertTrue(first_started)
        self.assertTrue(second_started)
        self.assertEqual(
            try_steer.call_args_list,
            [
                mock.call(flow.config, flow.ctx.scope_key, "first follow up"),
                mock.call(flow.config, flow.ctx.scope_key, "second follow up"),
            ],
        )
        start_message_worker.assert_not_called()
        self.assertEqual(flow.client.messages, [])

    def _assert_busy_live_codex_follow_up(
        self,
        *,
        scope_key,
        chat_id,
        message_thread_id,
        expect_thread_id,
    ):
        flow = self._make_flow(
            ctx=bridge_handlers.IncomingUpdateContext(
                update={},
                message={"text": "follow up"},
                chat_id=chat_id,
                message_thread_id=message_thread_id,
                scope_key=scope_key,
                message_id=95,
                actor_user_id=1,
                is_private_chat=message_thread_id is None and chat_id > 0,
                update_id=200,
            ),
            prompt_input="follow up",
        )
        flow.state.busy_chats.add(scope_key)
        dispatch = bridge_handlers.UpdateDispatchRequest(
            state=flow.state,
            config=flow.config,
            client=flow.client,
            engine=None,
            scope_key=scope_key,
            chat_id=chat_id,
            message_thread_id=message_thread_id,
            message_id=95,
            prompt="follow up",
            raw_prompt="follow up",
            photo_file_ids=[],
            voice_file_id=None,
            document=None,
            actor_user_id=1,
            sender_name=flow.sender_name,
            stateless=False,
            enforce_voice_prefix_from_transcript=False,
            youtube_route_url=None,
            handle_update_started_at=19.0,
        )

        active_engine = mock.Mock()
        active_engine.engine_name = "codex"

        with mock.patch.object(bridge_runtime_setup, "resolve_engine_for_scope", return_value=active_engine):
            with mock.patch.object(bridge_runtime_setup, "try_steer_live_codex_turn", return_value=True) as try_steer:
                with mock.patch.object(bridge_runtime_setup, "start_message_worker") as start_message_worker:
                    started = bridge_handlers.start_standard_dispatch(dispatch)

        self.assertTrue(started)
        try_steer.assert_called_once_with(flow.config, scope_key, "follow up")
        start_message_worker.assert_not_called()
        self.assertEqual(flow.client.messages, [])

    def test_start_standard_dispatch_routes_to_youtube_worker_when_route_present(self):
        flow = self._make_flow(prompt_input="watch this")
        dispatch = bridge_handlers.UpdateDispatchRequest(
            state=flow.state,
            config=flow.config,
            client=flow.client,
            engine=None,
            scope_key=flow.ctx.scope_key,
            chat_id=flow.ctx.chat_id,
            message_thread_id=flow.ctx.message_thread_id,
            message_id=flow.ctx.message_id,
            prompt="watch this",
            raw_prompt="watch this",
            photo_file_ids=[],
            voice_file_id=None,
            document=None,
            actor_user_id=flow.ctx.actor_user_id,
            sender_name=flow.sender_name,
            stateless=True,
            enforce_voice_prefix_from_transcript=False,
            youtube_route_url="https://youtube.example/watch?v=1",
            handle_update_started_at=19.0,
        )

        with mock.patch.object(bridge_runtime_setup, "resolve_engine_for_scope", return_value=object()):
            with mock.patch.object(bridge_runtime_setup, "start_youtube_worker") as start_youtube_worker:
                started = bridge_handlers.start_standard_dispatch(dispatch)

        self.assertTrue(started)
        start_youtube_worker.assert_called_once()


if __name__ == "__main__":
    unittest.main()
