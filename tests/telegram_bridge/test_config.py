"""Tests for Config — auto-split from test_bridge_core.py."""

import io
import json
import logging
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))
from types import SimpleNamespace
from unittest import mock

from tests.telegram_bridge.helpers import (
    FakeDownloadClient,
    FakeProgressEditClient,
    FakeSignalProgressClient,
    FakeTelegramClient,
    make_config,
)

import telegram_bridge.auth_state as bridge_auth_state
import telegram_bridge.bridge_runtime_setup as bridge_runtime_setup
import telegram_bridge.bridge_state_bootstrap as bridge_state_bootstrap
import telegram_bridge.channel_adapter as bridge_channel_adapter
import telegram_bridge.command_routing as bridge_command_routing
import telegram_bridge.control_commands as bridge_control_commands
import telegram_bridge.engine_adapter as bridge_engine_adapter
import telegram_bridge.engine_health as bridge_engine_health
import telegram_bridge.executor as bridge_executor
import telegram_bridge.handlers as bridge_handlers
import telegram_bridge.http_channel as bridge_http_channel
import telegram_bridge.main as bridge
import telegram_bridge.plugin_registry as bridge_plugin_registry
import telegram_bridge.prompt_execution as bridge_prompt_execution
import telegram_bridge.runtime_routing as bridge_runtime_routing
import telegram_bridge.runtime_config as bridge_runtime_config
import telegram_bridge.session_manager as bridge_session_manager
import telegram_bridge.signal_channel as bridge_signal_channel
import telegram_bridge.special_request_processing as bridge_special_request_processing
import telegram_bridge.structured_logging as bridge_structured_logging
import telegram_bridge.transport as bridge_transport
import telegram_bridge.voice_alias_commands as bridge_voice_alias_commands
import telegram_bridge.whatsapp_channel as bridge_whatsapp_channel


class TestConfig(unittest.TestCase):
    def test_config_accepts_grouped_submodels_with_flat_access(self):
        config = bridge.Config(
            core=bridge_runtime_config.CoreConfig(
                token="token",
                allowed_chat_ids={1},
                api_base="https://api.telegram.org",
                poll_timeout_seconds=30,
                retry_sleep_seconds=3.0,
                exec_timeout_seconds=60,
                max_input_chars=4096,
                max_output_chars=20000,
                max_image_bytes=1024,
                max_voice_bytes=1024,
                max_document_bytes=1024,
                attachment_retention_seconds=60,
                attachment_max_total_bytes=1024 * 1024,
                rate_limit_per_minute=12,
                executor_cmd=["/bin/echo"],
                state_dir="/tmp/state",
            ),
            voice=bridge_runtime_config.VoiceConfig(
                voice_transcribe_cmd=[],
                voice_transcribe_timeout_seconds=120,
                voice_alias_replacements=[],
                voice_alias_learning_enabled=True,
                voice_alias_learning_path="/tmp/voice.json",
                voice_alias_learning_min_examples=2,
                voice_alias_learning_confirmation_window_seconds=900,
                voice_low_confidence_confirmation_enabled=True,
                voice_low_confidence_threshold=0.45,
                voice_low_confidence_message="low confidence",
            ),
            session=bridge_runtime_config.SessionConfig(
                persistent_workers_enabled=False,
                persistent_workers_max=4,
                persistent_workers_idle_timeout_seconds=60,
                persistent_workers_policy_files=[],
                canonical_sessions_enabled=False,
                canonical_legacy_mirror_enabled=False,
                canonical_sqlite_enabled=False,
                canonical_sqlite_path="/tmp/chat_sessions.sqlite3",
                canonical_json_mirror_enabled=False,
                required_prefixes=["@architect"],
                required_prefix_ignore_case=True,
                require_prefix_in_private=True,
                allow_private_chats_unlisted=False,
                allow_group_chats_unlisted=False,
            ),
            identity=bridge_runtime_config.IdentityConfig(
                assistant_name="Architect",
                channel_plugin="telegram",
            ),
            engines=bridge_runtime_config.EngineConfig(
                engine_plugin="codex",
                selectable_engine_plugins=["codex", "pi"],
                codex_sandbox_mode="off",
                codex_model="gpt-5.5",
                codex_reasoning_effort="medium",
                gemma_provider="ollama_ssh",
                gemma_model="gemma4:26b",
                gemma_base_url="http://127.0.0.1:11434",
                gemma_ssh_host="server4-beast",
                gemma_request_timeout_seconds=180,
                venice_api_key="",
                venice_base_url="https://api.venice.ai/api/v1",
                venice_model="mistral-31-24b",
                venice_temperature=0.2,
                venice_request_timeout_seconds=180,
                pi_provider="ollama",
                pi_model="qwen3-coder:30b",
                pi_runner="ssh",
                pi_bin="pi",
                pi_ssh_host="server4-beast",
                pi_local_cwd="/tmp",
                pi_remote_cwd="/tmp",
                pi_session_mode="none",
                pi_session_dir="",
                pi_session_max_bytes=2 * 1024 * 1024,
                pi_session_max_age_seconds=7 * 24 * 60 * 60,
                pi_session_archive_retention_seconds=14 * 24 * 60 * 60,
                pi_session_archive_dir="",
                pi_tools_mode="default",
                pi_tools_allowlist="",
                pi_extra_args="",
                pi_ollama_tunnel_enabled=True,
                pi_ollama_tunnel_local_port=11435,
                pi_ollama_tunnel_remote_host="127.0.0.1",
                pi_ollama_tunnel_remote_port=11434,
                pi_request_timeout_seconds=180,
            ),
            transport=bridge_runtime_config.TransportConfig(
                whatsapp_plugin_enabled=False,
                whatsapp_bridge_api_base="http://127.0.0.1:8787",
                whatsapp_bridge_auth_token="",
                whatsapp_poll_timeout_seconds=20,
                signal_plugin_enabled=False,
                signal_bridge_api_base="http://127.0.0.1:18797",
                signal_bridge_auth_token="",
                signal_poll_timeout_seconds=20,
                keyword_routing_enabled=True,
            ),
            diary=bridge_runtime_config.DiaryConfig(),
            affective=bridge_runtime_config.AffectiveConfig(),
            messages=bridge_runtime_config.MessageConfig(),
        )

        self.assertEqual(config.core.token, "token")
        self.assertEqual(config.token, "token")
        self.assertEqual(config.required_prefixes, ["@architect"])
        config.codex_model = "gpt-5.4-mini"
        self.assertEqual(config.engines.codex_model, "gpt-5.4-mini")

    def test_config_accepts_flat_kwargs_and_exposes_grouped_submodels(self):
        config = bridge.Config(
            token="token",
            allowed_chat_ids={1},
            api_base="https://api.telegram.org",
            poll_timeout_seconds=30,
            retry_sleep_seconds=3.0,
            exec_timeout_seconds=60,
            max_input_chars=4096,
            max_output_chars=20000,
            max_image_bytes=1024,
            max_voice_bytes=1024,
            max_document_bytes=1024,
            attachment_retention_seconds=60,
            attachment_max_total_bytes=1024 * 1024,
            rate_limit_per_minute=12,
            executor_cmd=["/bin/echo"],
            state_dir="/tmp/state",
            voice_transcribe_cmd=[],
            voice_transcribe_timeout_seconds=120,
            voice_alias_replacements=[],
            voice_alias_learning_enabled=True,
            voice_alias_learning_path="/tmp/voice.json",
            voice_alias_learning_min_examples=2,
            voice_alias_learning_confirmation_window_seconds=900,
            voice_low_confidence_confirmation_enabled=True,
            voice_low_confidence_threshold=0.45,
            voice_low_confidence_message="low confidence",
            persistent_workers_enabled=False,
            persistent_workers_max=4,
            persistent_workers_idle_timeout_seconds=60,
            persistent_workers_policy_files=[],
            canonical_sessions_enabled=False,
            canonical_legacy_mirror_enabled=False,
            canonical_sqlite_enabled=False,
            canonical_sqlite_path="/tmp/chat_sessions.sqlite3",
            canonical_json_mirror_enabled=False,
            required_prefixes=[],
            required_prefix_ignore_case=True,
            require_prefix_in_private=True,
            allow_private_chats_unlisted=False,
            allow_group_chats_unlisted=False,
            assistant_name="Architect",
            channel_plugin="telegram",
            engine_plugin="codex",
            selectable_engine_plugins=["codex", "pi"],
            codex_model="gpt-5.5",
            codex_reasoning_effort="medium",
            gemma_provider="ollama_ssh",
            gemma_model="gemma4:26b",
            gemma_base_url="http://127.0.0.1:11434",
            gemma_ssh_host="server4-beast",
            gemma_request_timeout_seconds=180,
            venice_api_key="",
            venice_base_url="https://api.venice.ai/api/v1",
            venice_model="mistral-31-24b",
            venice_temperature=0.2,
            venice_request_timeout_seconds=180,
            pi_provider="ollama",
            pi_model="qwen3-coder:30b",
            pi_runner="ssh",
            pi_bin="pi",
            pi_ssh_host="server4-beast",
            pi_local_cwd="/tmp",
            pi_remote_cwd="/tmp",
            pi_session_mode="none",
            pi_session_dir="",
            pi_session_max_bytes=2 * 1024 * 1024,
            pi_session_max_age_seconds=7 * 24 * 60 * 60,
            pi_session_archive_retention_seconds=14 * 24 * 60 * 60,
            pi_session_archive_dir="",
            pi_tools_mode="default",
            pi_tools_allowlist="",
            pi_extra_args="",
            pi_ollama_tunnel_enabled=True,
            pi_ollama_tunnel_local_port=11435,
            pi_ollama_tunnel_remote_host="127.0.0.1",
            pi_ollama_tunnel_remote_port=11434,
            pi_request_timeout_seconds=180,
            whatsapp_plugin_enabled=False,
            whatsapp_bridge_api_base="http://127.0.0.1:8787",
            whatsapp_bridge_auth_token="",
            whatsapp_poll_timeout_seconds=20,
            signal_plugin_enabled=False,
            signal_bridge_api_base="http://127.0.0.1:18797",
            signal_bridge_auth_token="",
            signal_poll_timeout_seconds=20,
            keyword_routing_enabled=True,
        )

        self.assertEqual(config.core.state_dir, "/tmp/state")
        self.assertEqual(config.voice.voice_low_confidence_message, "low confidence")
        self.assertEqual(config.engines.codex_model, "gpt-5.5")

    def test_build_help_and_status_text_accept_grouped_only_config(self):
        config = SimpleNamespace(
            core=SimpleNamespace(allowed_chat_ids={1}),
            session=SimpleNamespace(
                required_prefixes=["@architect"],
                persistent_workers_enabled=True,
                persistent_workers_max=4,
            ),
            identity=SimpleNamespace(
                assistant_name="Architect",
                channel_plugin="telegram",
            ),
            engines=SimpleNamespace(
                engine_plugin="codex",
                selectable_engine_plugins=["codex", "pi"],
            ),
            transport=SimpleNamespace(keyword_routing_enabled=True),
        )
        state = bridge.State()

        help_text = bridge_handlers.build_help_text(config)
        status_text = bridge_handlers.build_status_text(state, config, chat_id=1)

        self.assertIn("Use `HA ...`", help_text)
        self.assertIn("Allowed chats: 1", status_text)
        self.assertIn("Required prefixes: @architect", status_text)
        self.assertIn("Default engine: codex", status_text)

    def test_check_pi_health_accepts_grouped_only_config(self):
        config = SimpleNamespace(
            engines=SimpleNamespace(
                pi_model="gemma4:26b",
                pi_runner="ssh",
                pi_ssh_host="server4-beast",
            )
        )

        def fake_run_pi_command(_config, command):
            if command == "pi --version":
                return subprocess.CompletedProcess(
                    args=["pi", "--version"],
                    returncode=0,
                    stdout="pi 1.2.3\n",
                    stderr="",
                )
            self.assertEqual(command, "pi --list-models")
            return subprocess.CompletedProcess(
                args=["pi", "--list-models"],
                returncode=0,
                stdout="ollama gemma4:26b\n",
                stderr="",
            )

        health = bridge_engine_health.check_pi_health(
            config,
            provider="ollama",
            run_pi_command_fn=fake_run_pi_command,
            parse_pi_model_rows_fn=lambda rows: [tuple(rows.strip().split(maxsplit=1))],
        )

        self.assertTrue(health["ok"])
        self.assertEqual(health["version"], "pi 1.2.3")
        self.assertTrue(health["model_available"])

    def test_runtime_routing_and_polling_accept_grouped_only_config(self):
        config = SimpleNamespace(
            core=SimpleNamespace(allowed_chat_ids={1}, state_dir="/tmp/state"),
            session=SimpleNamespace(
                required_prefixes=["@helper"],
                required_prefix_ignore_case=True,
                require_prefix_in_private=True,
                allow_private_chats_unlisted=False,
                allow_group_chats_unlisted=False,
            ),
            identity=SimpleNamespace(channel_plugin="whatsapp"),
            transport=SimpleNamespace(keyword_routing_enabled=True),
        )

        prefix_result = bridge_runtime_routing.apply_required_prefix_gate(
            client=SimpleNamespace(channel_name="telegram"),
            config=config,
            prompt_input="@helper summarize this",
            has_reply_context=False,
            voice_file_id=None,
            document=None,
            is_private_chat=True,
            normalize_command=lambda _text: None,
            strip_required_prefix=bridge_handlers.strip_required_prefix,
        )

        self.assertEqual(prefix_result.prompt_input, "summarize this")
        self.assertTrue(bridge.should_resume_saved_update_offset(config))
        self.assertFalse(bridge.should_discard_startup_backlog(config))

    def test_allow_update_and_callback_query_accept_grouped_only_config(self):
        config = SimpleNamespace(
            core=SimpleNamespace(allowed_chat_ids={1}),
            session=SimpleNamespace(
                allow_private_chats_unlisted=False,
                allow_group_chats_unlisted=False,
            ),
            identity=SimpleNamespace(channel_plugin="telegram"),
            denied_message="Denied",
        )
        client = FakeTelegramClient()
        ctx = bridge_handlers.IncomingUpdateContext(
            update={},
            message={},
            chat_id=1,
            message_thread_id=None,
            scope_key="tg:1",
            message_id=9,
            actor_user_id=None,
            is_private_chat=True,
            update_id=1,
        )

        self.assertTrue(bridge_handlers.allow_update_chat(ctx, config, client))

    def test_build_runtime_bootstrap_accepts_grouped_only_config(self):
        config = SimpleNamespace(
            core=SimpleNamespace(
                state_dir="/tmp/architect-state",
                attachment_retention_seconds=60,
                attachment_max_total_bytes=1024 * 1024,
            ),
            session=SimpleNamespace(
                persistent_workers_enabled=False,
                persistent_workers_policy_files=[],
                canonical_sessions_enabled=False,
                canonical_legacy_mirror_enabled=False,
                canonical_sqlite_enabled=False,
                canonical_sqlite_path="/tmp/chat_sessions.sqlite3",
                canonical_json_mirror_enabled=False,
            ),
            voice=SimpleNamespace(
                voice_alias_learning_enabled=True,
                voice_alias_learning_path="/tmp/voice-aliases.json",
                voice_alias_learning_min_examples=2,
                voice_alias_learning_confirmation_window_seconds=900,
            ),
        )

        with (
            mock.patch.object(bridge_runtime_setup, "ensure_state_dir"),
            mock.patch.object(bridge_runtime_setup, "AttachmentStore", return_value=mock.sentinel.attachment_store),
            mock.patch.object(bridge_runtime_setup, "build_affective_runtime", return_value=mock.sentinel.affective_runtime),
            mock.patch.object(bridge_runtime_setup, "build_bridge_state_paths", return_value={}),
            mock.patch.object(
                bridge_runtime_setup,
                "load_bridge_state_mappings",
                return_value={"threads": {}, "engines": {}, "codex_models": {}, "codex_efforts": {}, "pi_models": {}, "pi_providers": {}, "worker_sessions": {}, "in_flight": {}},
            ),
            mock.patch.object(
                bridge_runtime_setup,
                "load_canonical_session_bootstrap",
                return_value=({}, "none"),
            ),
            mock.patch.object(bridge_runtime_setup, "compute_current_auth_fingerprint", return_value="auth-fp"),
            mock.patch.object(
                bridge_runtime_setup,
                "apply_auth_change_thread_reset",
                return_value={"applied": False, "counts": {}},
            ),
            mock.patch.object(
                bridge_runtime_setup,
                "initialize_voice_alias_learning_store",
                return_value=None,
            ),
        ):
            bootstrap = bridge.build_runtime_bootstrap(config)

        self.assertIsNotNone(bootstrap.state.attachment_store)

    def test_close_runtime_bootstrap_closes_distinct_runtime_resources_once(self):
        attachment_store = mock.Mock()
        affective_runtime = mock.Mock()
        voice_store = mock.Mock()
        bootstrap = bridge.RuntimeBootstrap(
            state=bridge.State(
                attachment_store=attachment_store,
                affective_runtime=affective_runtime,
                voice_alias_learning_store=voice_store,
            ),
            state_paths={},
            loaded_threads={},
            loaded_worker_sessions={},
            loaded_in_flight={},
            canonical_bootstrap_source="none",
            affective_runtime=affective_runtime,
            voice_alias_learning_store=voice_store,
        )

        bridge.close_runtime_bootstrap(bootstrap)

        voice_store.close.assert_called_once_with()
        attachment_store.close.assert_called_once_with()
        affective_runtime.close.assert_called_once_with()

    def test_run_bridge_closes_runtime_bootstrap_when_plugin_selection_fails(self):
        bootstrap = bridge.RuntimeBootstrap(
            state=bridge.State(
                attachment_store=mock.Mock(),
                affective_runtime=mock.Mock(),
            ),
            state_paths={},
            loaded_threads={},
            loaded_worker_sessions={},
            loaded_in_flight={},
            canonical_bootstrap_source="none",
            affective_runtime=None,
            voice_alias_learning_store=None,
        )
        registry = mock.Mock()
        registry.build_channel.side_effect = RuntimeError("bad channel")
        registry.list_channels.return_value = ["telegram"]
        registry.list_engines.return_value = ["codex"]
        config = make_config()

        with (
            mock.patch.object(bridge, "build_runtime_bootstrap", return_value=bootstrap),
            mock.patch.object(bridge, "build_default_plugin_registry", return_value=registry),
        ):
            result = bridge.run_bridge(config)

        self.assertEqual(result, 1)
        bootstrap.state.attachment_store.close.assert_called_once_with()
        bootstrap.state.affective_runtime.close.assert_called_once_with()

    def test_run_bridge_closes_runtime_bootstrap_on_keyboard_interrupt(self):
        attachment_store = mock.Mock()
        affective_runtime = mock.Mock()
        bootstrap = bridge.RuntimeBootstrap(
            state=bridge.State(
                attachment_store=attachment_store,
                affective_runtime=affective_runtime,
            ),
            state_paths={
                "chat_threads": "/tmp/chat_threads.json",
                "in_flight_requests": "/tmp/in_flight_requests.json",
                "chat_sessions": "/tmp/chat_sessions.json",
            },
            loaded_threads={},
            loaded_worker_sessions={},
            loaded_in_flight={},
            canonical_bootstrap_source="none",
            affective_runtime=affective_runtime,
            voice_alias_learning_store=None,
        )
        client = mock.Mock()
        client.get_updates.side_effect = KeyboardInterrupt()
        registry = mock.Mock()
        registry.build_channel.return_value = client
        registry.build_engine.return_value = mock.Mock()
        config = make_config()

        with (
            mock.patch.object(bridge, "build_runtime_bootstrap", return_value=bootstrap),
            mock.patch.object(bridge, "build_default_plugin_registry", return_value=registry),
            mock.patch.object(bridge, "persist_bootstrap_state"),
            mock.patch.object(bridge, "pop_interrupted_requests", return_value=[]),
            mock.patch.object(bridge, "should_discard_startup_backlog", return_value=False),
            mock.patch.object(bridge, "compute_initial_update_offset", return_value=(0, "/tmp/update_offset.json")),
            mock.patch.object(bridge, "persist_saved_update_offset"),
            mock.patch.object(bridge, "expire_idle_worker_sessions"),
            mock.patch.object(bridge, "flush_ready_media_group_updates", return_value=[]),
            mock.patch.object(bridge, "flush_ready_text_batch_updates", return_value=[]),
            mock.patch.object(bridge, "compute_poll_timeout_seconds", return_value=1),
        ):
            with self.assertRaises(KeyboardInterrupt):
                bridge.run_bridge(config)

        attachment_store.close.assert_called_once_with()
        affective_runtime.close.assert_called_once_with()

    def test_load_config_reads_allow_private_chats_unlisted_override(self):
        with mock.patch.dict(
            os.environ,
            {
                "TELEGRAM_BOT_TOKEN": "token",
                "TELEGRAM_ALLOWED_CHAT_IDS": "1",
                "TELEGRAM_ALLOW_PRIVATE_CHATS_UNLISTED": "true",
            },
            clear=True,
        ):
            config = bridge.load_config()
        self.assertTrue(config.allow_private_chats_unlisted)

    def test_load_config_reads_busy_message_override(self):
        with mock.patch.dict(
            os.environ,
            {
                "TELEGRAM_BOT_TOKEN": "token",
                "TELEGRAM_ALLOWED_CHAT_IDS": "1",
                "TELEGRAM_BUSY_MESSAGE": "Даю справку: уже занят предыдущим запросом.",
            },
            clear=True,
        ):
            config = bridge.load_config()
        self.assertEqual(
            config.busy_message,
            "Даю справку: уже занят предыдущим запросом.",
        )

    def test_load_config_expands_state_dir_and_derived_state_paths(self):
        home_dir = Path.home()
        with tempfile.TemporaryDirectory(dir=home_dir) as tmpdir:
            state_dir = Path(tmpdir) / "bridge-state"
            voice_path = Path(tmpdir) / "voice-aliases.json"
            env = {
                "TELEGRAM_BOT_TOKEN": "token",
                "TELEGRAM_ALLOWED_CHAT_IDS": "1",
                "TELEGRAM_BRIDGE_STATE_DIR": f"~/{state_dir.relative_to(home_dir)}",
                "TELEGRAM_CANONICAL_SQLITE_PATH": f"~/{(state_dir / 'custom-canonical.sqlite3').relative_to(home_dir)}",
                "TELEGRAM_VOICE_ALIAS_LEARNING_PATH": f"~/{voice_path.relative_to(home_dir)}",
            }
            with mock.patch.dict(os.environ, env, clear=True):
                config = bridge.load_config()

        self.assertEqual(config.state_dir, str(state_dir))
        self.assertEqual(
            config.canonical_sqlite_path,
            str(state_dir / "custom-canonical.sqlite3"),
        )
        self.assertEqual(config.voice_alias_learning_path, str(voice_path))
        self.assertEqual(config.affective_runtime_db_path, str(state_dir / "affective_state.sqlite3"))
        self.assertEqual(config.diary_local_root, str(state_dir / "diary"))

    def test_load_config_enables_codex_app_server_by_default_for_architect(self):
        with mock.patch.dict(
            os.environ,
            {
                "TELEGRAM_BOT_TOKEN": "token",
                "TELEGRAM_ALLOWED_CHAT_IDS": "1",
            },
            clear=True,
        ):
            config = bridge.load_config()
        self.assertTrue(config.codex_app_server_enabled)
        self.assertEqual(config.codex_sandbox_mode, "danger-full-access")

    def test_load_config_keeps_codex_app_server_opt_in_for_non_architect(self):
        with mock.patch.dict(
            os.environ,
            {
                "TELEGRAM_BOT_TOKEN": "token",
                "TELEGRAM_ALLOWED_CHAT_IDS": "1",
                "TELEGRAM_ASSISTANT_NAME": "Tank",
            },
            clear=True,
        ):
            config = bridge.load_config()
        self.assertFalse(config.codex_app_server_enabled)
        self.assertEqual(config.codex_sandbox_mode, "danger-full-access")

    def test_load_config_enables_codex_app_server_by_default_for_govorun(self):
        with mock.patch.dict(
            os.environ,
            {
                "TELEGRAM_BOT_TOKEN": "token",
                "TELEGRAM_ALLOWED_CHAT_IDS": "1",
                "TELEGRAM_ASSISTANT_NAME": "Govorun",
            },
            clear=True,
        ):
            config = bridge.load_config()
        self.assertTrue(config.codex_app_server_enabled)
        self.assertEqual(config.codex_sandbox_mode, "danger-full-access")

    def test_load_config_reads_codex_app_server_override(self):
        with mock.patch.dict(
            os.environ,
            {
                "TELEGRAM_BOT_TOKEN": "token",
                "TELEGRAM_ALLOWED_CHAT_IDS": "1",
                "TELEGRAM_CODEX_APP_SERVER_ENABLED": "true",
            },
            clear=True,
        ):
            config = bridge.load_config()
        self.assertTrue(config.codex_app_server_enabled)

    def test_load_config_ignores_codex_sandbox_mode_override(self):
        with mock.patch.dict(
            os.environ,
            {
                "TELEGRAM_BOT_TOKEN": "token",
                "TELEGRAM_ALLOWED_CHAT_IDS": "1",
                "TELEGRAM_CODEX_SANDBOX_MODE": "off",
                "TELEGRAM_ASSISTANT_NAME": "Tank",
            },
            clear=True,
        ):
            config = bridge.load_config()
        self.assertEqual(config.codex_sandbox_mode, "danger-full-access")

    def test_parse_outbound_media_directive_extracts_media_and_voice_flag(self):
        text, directive = bridge_handlers.parse_outbound_media_directive(
            "[[media:/tmp/note.ogg]] [[audio_as_voice]] hello there"
        )
        self.assertEqual(text, "hello there")
        self.assertIsNotNone(directive)
        self.assertEqual(directive.media_ref, "/tmp/note.ogg")
        self.assertTrue(directive.as_voice)

    def test_parse_structured_outbound_payload_extracts_media_and_text(self):
        parsed, error = bridge_handlers.parse_structured_outbound_payload(
            json.dumps(
                {
                    "telegram_outbound": {
                        "text": "caption one",
                        "media_ref": "https://example.com/note.ogg",
                        "as_voice": True,
                    }
                }
            )
        )
        self.assertIsNone(error)
        self.assertIsNotNone(parsed)
        rendered_text, directive = parsed
        self.assertEqual(rendered_text, "caption one")
        self.assertIsNotNone(directive)
        self.assertEqual(directive.media_ref, "https://example.com/note.ogg")
        self.assertTrue(directive.as_voice)

    def test_parse_structured_outbound_payload_reports_schema_error(self):
        parsed, error = bridge_handlers.parse_structured_outbound_payload(
            '{"telegram_outbound":"bad"}'
        )
        self.assertIsNone(parsed)
        self.assertEqual(error, "invalid_schema:telegram_outbound_not_object")

    def test_parse_voice_confidence(self):
        self.assertEqual(
            bridge_handlers.parse_voice_confidence("VOICE_CONFIDENCE=0.723\n"),
            0.723,
        )
        self.assertIsNone(bridge_handlers.parse_voice_confidence("no marker"))

    def test_load_config_preserves_blank_progress_elapsed_fields(self):
        env = {
            "TELEGRAM_BOT_TOKEN": "token",
            "TELEGRAM_ALLOWED_CHAT_IDS": "1",
            "TELEGRAM_PROGRESS_ELAPSED_PREFIX": "",
            "TELEGRAM_PROGRESS_ELAPSED_SUFFIX": "",
        }
        with mock.patch.dict(os.environ, env, clear=False):
            cfg = bridge.load_config()
        self.assertEqual(cfg.progress_elapsed_prefix, "")
        self.assertEqual(cfg.progress_elapsed_suffix, "")

    def test_build_low_confidence_voice_message_uses_configured_text(self):
        config = make_config(voice_low_confidence_message="Voice transcript confidence is low, resend")
        message = bridge_handlers.build_low_confidence_voice_message(
            config,
            transcript="govorun test",
            confidence=0.2,
        )
        self.assertEqual(message, "Voice transcript confidence is low, resend")

    def test_policy_fingerprint_cache_reuses_value_within_ttl(self):
        bridge_session_manager._policy_fingerprint_cache.clear()
        with mock.patch.object(
            bridge_session_manager,
            "compute_policy_fingerprint",
            side_effect=["fp-a", "fp-b"],
        ) as compute:
            first = bridge_session_manager.get_cached_policy_fingerprint(
                ["/tmp/policy-a"],
                now=100.0,
            )
            second = bridge_session_manager.get_cached_policy_fingerprint(
                ["/tmp/policy-a"],
                now=105.0,
            )
            third = bridge_session_manager.get_cached_policy_fingerprint(
                ["/tmp/policy-a"],
                now=111.0,
            )
        self.assertEqual(first, "fp-a")
        self.assertEqual(second, "fp-a")
        self.assertEqual(third, "fp-b")
        self.assertEqual(compute.call_count, 2)

    def test_policy_fingerprint_cache_normalizes_order_and_duplicates(self):
        bridge_session_manager._policy_fingerprint_cache.clear()
        with mock.patch.object(
            bridge_session_manager,
            "compute_policy_fingerprint",
            return_value="fp-stable",
        ) as compute:
            first = bridge_session_manager.get_cached_policy_fingerprint(
                ["/tmp/policy-b", "/tmp/policy-a", "/tmp/policy-a"],
                now=100.0,
            )
            second = bridge_session_manager.get_cached_policy_fingerprint(
                ["/tmp/policy-a", "/tmp/policy-b"],
                now=105.0,
            )

        self.assertEqual(first, "fp-stable")
        self.assertEqual(second, "fp-stable")
        compute.assert_called_once_with(["/tmp/policy-a", "/tmp/policy-b"])

    def test_policy_fingerprint_is_stable_across_tilde_and_absolute_paths(self):
        home_dir = Path.home()
        with tempfile.TemporaryDirectory(dir=home_dir) as tmpdir:
            policy_path = Path(tmpdir) / "policy.txt"
            policy_path.write_text("policy-v1\n", encoding="utf-8")
            tilde_path = f"~/{policy_path.relative_to(home_dir)}"

            absolute_fingerprint = bridge_session_manager.compute_policy_fingerprint([str(policy_path)])
            tilde_fingerprint = bridge_session_manager.compute_policy_fingerprint([tilde_path])

        self.assertEqual(absolute_fingerprint, tilde_fingerprint)

    def test_policy_fingerprint_cache_normalizes_tilde_and_absolute_paths(self):
        bridge_session_manager._policy_fingerprint_cache.clear()
        home_dir = Path.home()
        with tempfile.TemporaryDirectory(dir=home_dir) as tmpdir:
            policy_path = Path(tmpdir) / "policy.txt"
            policy_path.write_text("policy-v1\n", encoding="utf-8")
            tilde_path = f"~/{policy_path.relative_to(home_dir)}"

            with mock.patch.object(
                bridge_session_manager,
                "compute_policy_fingerprint",
                return_value="fp-stable",
            ) as compute:
                first = bridge_session_manager.get_cached_policy_fingerprint(
                    [tilde_path],
                    now=100.0,
                )
                second = bridge_session_manager.get_cached_policy_fingerprint(
                    [str(policy_path)],
                    now=105.0,
                )

        self.assertEqual(first, "fp-stable")
        self.assertEqual(second, "fp-stable")
        compute.assert_called_once_with([str(policy_path)])

    def test_apply_policy_change_thread_reset_clears_stale_threads_and_persists_fingerprint(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state_dir = Path(tmpdir)
            fingerprint_path = Path(bridge.build_policy_fingerprint_state_path(str(state_dir)))
            fingerprint_path.write_text("old-fingerprint\n", encoding="utf-8")
            loaded_threads = {1: "thread-1", 2: "thread-2"}
            loaded_worker_sessions = {
                2: bridge.WorkerSession(
                    created_at=1.0,
                    last_used_at=2.0,
                    thread_id="thread-2",
                    policy_fingerprint="old-fingerprint",
                )
            }
            loaded_canonical_sessions = {
                1: bridge.CanonicalSession(thread_id="thread-1"),
                2: bridge.CanonicalSession(
                    thread_id="thread-2",
                    worker_created_at=10.0,
                    worker_last_used_at=20.0,
                    worker_policy_fingerprint="old-fingerprint",
                ),
                3: bridge.CanonicalSession(in_flight_started_at=30.0, in_flight_message_id=300),
            }

            result = bridge.apply_policy_change_thread_reset(
                state_dir=str(state_dir),
                current_policy_fingerprint="new-fingerprint",
                loaded_threads=loaded_threads,
                loaded_worker_sessions=loaded_worker_sessions,
                loaded_canonical_sessions=loaded_canonical_sessions,
            )

            self.assertTrue(result["applied"])
            self.assertEqual(result["counts"]["threads"], 2)
            self.assertEqual(result["counts"]["worker_sessions"], 1)
            self.assertEqual(result["counts"]["canonical_sessions"], 2)
            self.assertEqual(loaded_threads, {})
            self.assertEqual(loaded_worker_sessions, {})
            self.assertNotIn(1, loaded_canonical_sessions)
            self.assertNotIn(2, loaded_canonical_sessions)
            self.assertIn(3, loaded_canonical_sessions)
            self.assertEqual(
                fingerprint_path.read_text(encoding="utf-8").strip(),
                "new-fingerprint",
            )

    def test_build_runtime_bootstrap_keeps_loaded_runtime_state(self):
        config = make_config(
            state_dir="/tmp/architect-state",
            canonical_sessions_enabled=True,
            canonical_sqlite_enabled=True,
            canonical_json_mirror_enabled=True,
        )
        attachment_store = object()
        affective_runtime = object()
        voice_store = object()
        loaded_worker_sessions = {
            1: bridge.WorkerSession(
                created_at=1.0,
                last_used_at=2.0,
                thread_id="thread-1",
                policy_fingerprint="policy-fp",
            )
        }
        loaded_canonical_sessions = {"tg:1": bridge.CanonicalSession(thread_id="canonical-thread")}
        state_paths = {
            "chat_threads": "/tmp/chat_threads.json",
            "chat_engines": "/tmp/chat_engines.json",
            "chat_codex_models": "/tmp/chat_codex_models.json",
            "chat_codex_efforts": "/tmp/chat_codex_efforts.json",
            "chat_pi_models": "/tmp/chat_pi_models.json",
            "chat_pi_providers": "/tmp/chat_pi_providers.json",
            "worker_sessions": "/tmp/worker_sessions.json",
            "in_flight_requests": "/tmp/in_flight_requests.json",
            "chat_sessions": "/tmp/chat_sessions.json",
        }
        loaded_state = {
            "threads": {1: "thread-1"},
            "engines": {"tg:1": "pi"},
            "codex_models": {"tg:1": "gpt-5.5"},
            "codex_efforts": {"tg:1": "medium"},
            "pi_models": {"tg:1": "qwen3-coder:30b"},
            "pi_providers": {"tg:1": "ollama"},
            "worker_sessions": loaded_worker_sessions,
            "in_flight": {1: {"message_id": 99}},
        }

        with (
            mock.patch.object(bridge_runtime_setup, "ensure_state_dir"),
            mock.patch.object(bridge_runtime_setup, "AttachmentStore", return_value=attachment_store),
            mock.patch.object(bridge_runtime_setup, "build_affective_runtime", return_value=affective_runtime),
            mock.patch.object(bridge_runtime_setup, "build_bridge_state_paths", return_value=state_paths),
            mock.patch.object(bridge_runtime_setup, "load_bridge_state_mappings", return_value=loaded_state),
            mock.patch.object(
                bridge_runtime_setup,
                "load_canonical_session_bootstrap",
                return_value=(loaded_canonical_sessions, "canonical-json"),
            ),
            mock.patch.object(bridge_runtime_setup, "compute_current_auth_fingerprint", return_value="auth-fp"),
            mock.patch.object(
                bridge_runtime_setup,
                "apply_auth_change_thread_reset",
                return_value={"applied": False, "counts": {}},
            ),
            mock.patch.object(
                bridge_runtime_setup,
                "initialize_voice_alias_learning_store",
                return_value=voice_store,
            ),
        ):
            bootstrap = bridge.build_runtime_bootstrap(config)

        self.assertEqual(bootstrap.canonical_bootstrap_source, "canonical-json")
        self.assertIs(bootstrap.affective_runtime, affective_runtime)
        self.assertIs(bootstrap.voice_alias_learning_store, voice_store)
        self.assertEqual(bootstrap.state.chat_threads, {})
        self.assertEqual(bootstrap.state.worker_sessions, {})
        self.assertEqual(bootstrap.state.chat_sessions, loaded_canonical_sessions)
        self.assertEqual(bootstrap.state.chat_engines, {"tg:1": "pi"})
        self.assertEqual(bootstrap.state.auth_fingerprint, "auth-fp")
        self.assertIs(bootstrap.state.attachment_store, attachment_store)
        self.assertIs(bootstrap.state.affective_runtime, affective_runtime)
        self.assertIs(bootstrap.state.voice_alias_learning_store, voice_store)

    def test_persist_bootstrap_state_backfills_canonical_sessions_from_legacy(self):
        config = make_config(
            canonical_sessions_enabled=True,
            persistent_workers_enabled=True,
        )
        bootstrap = bridge.RuntimeBootstrap(
            state=bridge.State(canonical_sessions_enabled=True, chat_sessions={}),
            state_paths={},
            loaded_threads={1: "thread-1"},
            loaded_worker_sessions={
                1: bridge.WorkerSession(
                    created_at=1.0,
                    last_used_at=2.0,
                    thread_id="thread-1",
                    policy_fingerprint="policy-fp",
                )
            },
            loaded_in_flight={1: {"message_id": 42}},
            canonical_bootstrap_source="legacy",
            affective_runtime=None,
            voice_alias_learning_store=None,
        )
        built_sessions = {"tg:1": bridge.CanonicalSession(thread_id="thread-1")}

        with (
            mock.patch.object(
                bridge_runtime_setup,
                "build_canonical_sessions_from_legacy",
                return_value=built_sessions,
            ) as build_sessions,
            mock.patch.object(bridge_runtime_setup, "persist_canonical_sessions") as persist_canonical,
        ):
            bridge.persist_bootstrap_state(config, bootstrap)

        build_sessions.assert_called_once_with(
            bootstrap.loaded_threads,
            bootstrap.loaded_worker_sessions,
            bootstrap.loaded_in_flight,
        )
        self.assertIs(bootstrap.state.chat_sessions, built_sessions)
        persist_canonical.assert_called_once_with(bootstrap.state)

    def test_build_runtime_bootstrap_backfills_worker_sessions_from_threads(self):
        config = make_config(
            canonical_sessions_enabled=False,
            persistent_workers_enabled=True,
            persistent_workers_policy_files=["/tmp/policy-a.txt"],
        )
        state_paths = {
            "chat_threads": "/tmp/chat_threads.json",
            "chat_engines": "/tmp/chat_engines.json",
            "chat_codex_models": "/tmp/chat_codex_models.json",
            "chat_codex_efforts": "/tmp/chat_codex_efforts.json",
            "chat_pi_models": "/tmp/chat_pi_models.json",
            "chat_pi_providers": "/tmp/chat_pi_providers.json",
            "worker_sessions": "/tmp/worker_sessions.json",
            "in_flight_requests": "/tmp/in_flight_requests.json",
            "chat_sessions": "/tmp/chat_sessions.json",
        }
        loaded_threads = {1: "thread-1"}
        loaded_state = {
            "threads": loaded_threads,
            "engines": {},
            "codex_models": {},
            "codex_efforts": {},
            "pi_models": {},
            "pi_providers": {},
            "worker_sessions": {},
            "in_flight": {},
        }

        with (
            mock.patch.object(bridge_runtime_setup, "ensure_state_dir"),
            mock.patch.object(bridge_runtime_setup, "AttachmentStore", return_value=mock.sentinel.attachment_store),
            mock.patch.object(bridge_runtime_setup, "build_affective_runtime", return_value=mock.sentinel.affective_runtime),
            mock.patch.object(bridge_runtime_setup, "build_bridge_state_paths", return_value=state_paths),
            mock.patch.object(bridge_runtime_setup, "load_bridge_state_mappings", return_value=loaded_state),
            mock.patch.object(
                bridge_runtime_setup,
                "load_canonical_session_bootstrap",
                return_value=({}, "none"),
            ),
            mock.patch.object(bridge_runtime_setup, "compute_policy_fingerprint", return_value="policy-fp"),
            mock.patch.object(
                bridge_runtime_setup,
                "apply_policy_change_thread_reset",
                return_value={"applied": False, "counts": {}},
            ),
            mock.patch.object(bridge_runtime_setup, "compute_current_auth_fingerprint", return_value="auth-fp"),
            mock.patch.object(
                bridge_runtime_setup,
                "apply_auth_change_thread_reset",
                return_value={"applied": False, "counts": {}},
            ),
            mock.patch.object(
                bridge_runtime_setup,
                "initialize_voice_alias_learning_store",
                return_value=None,
            ),
            mock.patch.object(bridge_runtime_setup.time, "time", return_value=123.0),
        ):
            bootstrap = bridge.build_runtime_bootstrap(config)

        self.assertEqual(bootstrap.state.chat_threads, loaded_threads)
        self.assertEqual(set(bootstrap.state.worker_sessions.keys()), {1})
        self.assertEqual(bootstrap.state.worker_sessions[1].thread_id, "thread-1")
        self.assertEqual(bootstrap.state.worker_sessions[1].policy_fingerprint, "policy-fp")
        self.assertEqual(bootstrap.state.worker_sessions[1].created_at, 123.0)
        self.assertEqual(bootstrap.state.worker_sessions[1].last_used_at, 123.0)

    def test_apply_policy_change_thread_reset_clears_loaded_state_on_change(self):
        loaded_threads = {1: "thread-1"}
        loaded_worker_sessions = {
            1: bridge.WorkerSession(
                created_at=1.0,
                last_used_at=2.0,
                thread_id="thread-1",
                policy_fingerprint="old-fp",
            )
        }
        loaded_canonical_sessions = {"tg:1": bridge.CanonicalSession(thread_id="thread-1")}

        with (
            mock.patch.object(
                bridge_runtime_setup,
                "load_saved_policy_fingerprint",
                return_value="old-fp",
            ),
            mock.patch.object(
                bridge_runtime_setup,
                "clear_thread_state_for_policy_change",
                return_value={"threads": 1, "worker_sessions": 1, "canonical_sessions": 1},
            ) as clear_state,
            mock.patch.object(bridge_runtime_setup, "persist_saved_policy_fingerprint") as persist_fp,
        ):
            result = bridge.apply_policy_change_thread_reset(
                state_dir="/tmp/bridge-state",
                current_policy_fingerprint="new-fp",
                loaded_threads=loaded_threads,
                loaded_worker_sessions=loaded_worker_sessions,
                loaded_canonical_sessions=loaded_canonical_sessions,
            )

        self.assertEqual(result["previous_policy_fingerprint"], "old-fp")
        self.assertTrue(result["applied"])
        self.assertEqual(
            result["counts"],
            {"threads": 1, "worker_sessions": 1, "canonical_sessions": 1},
        )
        clear_state.assert_called_once_with(
            loaded_threads,
            loaded_worker_sessions,
            loaded_canonical_sessions,
        )
        persist_fp.assert_called_once()

    def test_initialize_voice_alias_learning_store_returns_none_on_failure(self):
        config = make_config(
            voice_alias_learning_enabled=True,
            voice_alias_learning_path="/tmp/voice-aliases.json",
        )

        with mock.patch.object(
            bridge_runtime_setup,
            "VoiceAliasLearningStore",
            side_effect=RuntimeError("boom"),
        ):
            store = bridge_runtime_setup.initialize_voice_alias_learning_store(config)

        self.assertIsNone(store)

    def test_load_bridge_state_mappings_collects_all_expected_sections(self):
        state_paths = {
            "chat_threads": "/tmp/chat_threads.json",
            "chat_engines": "/tmp/chat_engines.json",
            "chat_codex_models": "/tmp/chat_codex_models.json",
            "chat_codex_efforts": "/tmp/chat_codex_efforts.json",
            "chat_pi_models": "/tmp/chat_pi_models.json",
            "chat_pi_providers": "/tmp/chat_pi_providers.json",
            "worker_sessions": "/tmp/worker_sessions.json",
            "in_flight_requests": "/tmp/in_flight_requests.json",
        }

        def fake_load_state_mapping_or_empty(path, _loader, *, description):
            return {"path": path, "description": description}

        with mock.patch.object(
            bridge_state_bootstrap,
            "load_state_mapping_or_empty",
            side_effect=fake_load_state_mapping_or_empty,
        ) as load_mapping:
            loaded = bridge_state_bootstrap.load_bridge_state_mappings(state_paths)

        self.assertEqual(
            set(loaded.keys()),
            {
                "threads",
                "engines",
                "codex_models",
                "codex_efforts",
                "pi_models",
                "pi_providers",
                "worker_sessions",
                "in_flight",
            },
        )
        self.assertEqual(load_mapping.call_count, 8)
        self.assertEqual(loaded["threads"]["path"], state_paths["chat_threads"])
        self.assertEqual(loaded["in_flight"]["path"], state_paths["in_flight_requests"])

    def test_load_saved_update_offset_ignores_invalid_and_negative_values(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            offset_path = Path(tmpdir) / "telegram_update_offset.txt"

            offset_path.write_text("not-a-number\n", encoding="utf-8")
            self.assertEqual(
                bridge_state_bootstrap.load_saved_update_offset(str(offset_path)),
                0,
            )

            offset_path.write_text("-9\n", encoding="utf-8")
            self.assertEqual(
                bridge_state_bootstrap.load_saved_update_offset(str(offset_path)),
                0,
            )

    def test_persist_saved_update_offset_writes_sanitized_value(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            offset_path = Path(tmpdir) / "telegram_update_offset.txt"

            bridge_state_bootstrap.persist_saved_update_offset(str(offset_path), -4)

            self.assertEqual(offset_path.read_text(encoding="utf-8"), "0\n")

    def test_load_state_mapping_or_empty_quarantines_and_emits_on_failure(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "chat_threads.json"
            state_path.write_text("{}", encoding="utf-8")

            with (
                mock.patch.object(
                    bridge_state_bootstrap,
                    "quarantine_corrupt_state_file",
                    return_value=f"{state_path}.corrupt",
                ) as quarantine,
                mock.patch.object(bridge_state_bootstrap, "emit_event") as emit_event,
            ):
                loaded = bridge_state_bootstrap.load_state_mapping_or_empty(
                    str(state_path),
                    mock.Mock(side_effect=RuntimeError("boom")),
                    description="chat thread mappings",
                )

            self.assertEqual(loaded, {})
            quarantine.assert_called_once_with(str(state_path))
            emit_event.assert_called_once_with(
                "bridge.state_load_failed",
                level=logging.WARNING,
                fields={"state_file": str(state_path)},
            )

    def test_load_canonical_session_bootstrap_returns_disabled_when_feature_off(self):
        config = make_config(canonical_sessions_enabled=False)

        loaded, source = bridge_state_bootstrap.load_canonical_session_bootstrap(
            config,
            {"chat_sessions": "/tmp/chat_sessions.json"},
            loaded_threads={1: "thread-1"},
            loaded_worker_sessions={},
            loaded_in_flight={},
        )

        self.assertEqual(loaded, {})
        self.assertEqual(source, "disabled")

    def test_load_canonical_session_bootstrap_uses_json_when_sqlite_disabled(self):
        config = make_config(
            canonical_sessions_enabled=True,
            canonical_sqlite_enabled=False,
        )
        state_paths = {"chat_sessions": "/tmp/chat_sessions.json"}
        sessions = {"tg:1": bridge.CanonicalSession(thread_id="thread-1")}

        with mock.patch.object(
            bridge_state_bootstrap,
            "_load_canonical_json_with_fallback",
            return_value=(sessions, "canonical_json"),
        ) as load_json:
            loaded, source = bridge_state_bootstrap.load_canonical_session_bootstrap(
                config,
                state_paths,
                loaded_threads={},
                loaded_worker_sessions={},
                loaded_in_flight={},
            )

        self.assertIs(loaded, sessions)
        self.assertEqual(source, "canonical_json")
        load_json.assert_called_once_with(
            state_paths["chat_sessions"],
            failure_source="canonical_json_reset_after_load_failure",
            empty_source="legacy_json_snapshot",
        )

    def test_load_canonical_session_bootstrap_imports_legacy_sessions_into_sqlite(self):
        config = make_config(
            canonical_sessions_enabled=True,
            canonical_sqlite_enabled=True,
            canonical_sqlite_path="/tmp/canonical.sqlite3",
        )
        state_paths = {"chat_sessions": "/tmp/chat_sessions.json"}
        legacy_sessions = {"tg:1": bridge.CanonicalSession(thread_id="legacy-thread")}

        with (
            mock.patch.object(
                bridge_state_bootstrap,
                "load_canonical_sessions_sqlite",
                return_value={},
            ),
            mock.patch.object(
                bridge_state_bootstrap,
                "_load_canonical_json_with_fallback",
                return_value=({}, "none"),
            ),
            mock.patch.object(
                bridge_state_bootstrap,
                "build_canonical_sessions_from_legacy",
                return_value=legacy_sessions,
            ) as build_legacy,
            mock.patch.object(
                bridge_state_bootstrap,
                "load_or_import_canonical_sessions_sqlite",
                return_value=(legacy_sessions, True),
            ) as load_or_import,
        ):
            loaded, source = bridge_state_bootstrap.load_canonical_session_bootstrap(
                config,
                state_paths,
                loaded_threads={1: "thread-1"},
                loaded_worker_sessions={},
                loaded_in_flight={1: {"message_id": 7}},
            )

        build_legacy.assert_called_once_with(
            {1: "thread-1"},
            {},
            {1: {"message_id": 7}},
        )
        load_or_import.assert_called_once_with(
            config.canonical_sqlite_path,
            import_sessions=legacy_sessions,
        )
        self.assertIs(loaded, legacy_sessions)
        self.assertEqual(source, "sqlite_imported_from_legacy_json")

    def test_load_canonical_session_bootstrap_uses_existing_sqlite_sessions(self):
        config = make_config(
            canonical_sessions_enabled=True,
            canonical_sqlite_enabled=True,
            canonical_sqlite_path="/tmp/canonical.sqlite3",
        )
        state_paths = {"chat_sessions": "/tmp/chat_sessions.json"}
        sqlite_sessions = {"tg:1": bridge.CanonicalSession(thread_id="sqlite-thread")}

        with mock.patch.object(
            bridge_state_bootstrap,
            "load_canonical_sessions_sqlite",
            return_value=sqlite_sessions,
        ):
            loaded, source = bridge_state_bootstrap.load_canonical_session_bootstrap(
                config,
                state_paths,
                loaded_threads={},
                loaded_worker_sessions={},
                loaded_in_flight={},
            )

        self.assertIs(loaded, sqlite_sessions)
        self.assertEqual(source, "sqlite")

    def test_load_canonical_session_bootstrap_returns_reset_source_after_sqlite_load_failure(self):
        config = make_config(
            canonical_sessions_enabled=True,
            canonical_sqlite_enabled=True,
            canonical_sqlite_path="/tmp/canonical.sqlite3",
        )
        state_paths = {"chat_sessions": "/tmp/chat_sessions.json"}

        with (
            mock.patch.object(
                bridge_state_bootstrap,
                "load_canonical_sessions_sqlite",
                side_effect=RuntimeError("sqlite failed"),
            ),
            mock.patch.object(
                bridge_state_bootstrap,
                "_load_canonical_json_with_fallback",
                return_value=({}, "none"),
            ),
            mock.patch.object(
                bridge_state_bootstrap,
                "build_canonical_sessions_from_legacy",
                return_value={},
            ),
            mock.patch.object(
                bridge_state_bootstrap,
                "load_or_import_canonical_sessions_sqlite",
                return_value=({}, False),
            ),
            mock.patch.object(
                bridge_state_bootstrap,
                "quarantine_corrupt_state_file",
                return_value="/tmp/canonical.sqlite3.corrupt",
            ),
            mock.patch.object(bridge_state_bootstrap, "emit_event"),
        ):
            loaded, source = bridge_state_bootstrap.load_canonical_session_bootstrap(
                config,
                state_paths,
                loaded_threads={},
                loaded_worker_sessions={},
                loaded_in_flight={},
            )

        self.assertEqual(loaded, {})
        self.assertEqual(source, "sqlite_reset_after_load_failure")

    def test_load_canonical_session_bootstrap_returns_reset_source_after_import_failure(self):
        config = make_config(
            canonical_sessions_enabled=True,
            canonical_sqlite_enabled=True,
            canonical_sqlite_path="/tmp/canonical.sqlite3",
        )
        state_paths = {"chat_sessions": "/tmp/chat_sessions.json"}

        with (
            mock.patch.object(
                bridge_state_bootstrap,
                "load_canonical_sessions_sqlite",
                return_value={},
            ),
            mock.patch.object(
                bridge_state_bootstrap,
                "_load_canonical_json_with_fallback",
                return_value=({}, "none"),
            ),
            mock.patch.object(
                bridge_state_bootstrap,
                "build_canonical_sessions_from_legacy",
                return_value={},
            ),
            mock.patch.object(
                bridge_state_bootstrap,
                "load_or_import_canonical_sessions_sqlite",
                side_effect=RuntimeError("import failed"),
            ),
            mock.patch.object(
                bridge_state_bootstrap,
                "quarantine_corrupt_state_file",
                return_value="/tmp/canonical.sqlite3.corrupt",
            ),
            mock.patch.object(bridge_state_bootstrap, "emit_event"),
        ):
            loaded, source = bridge_state_bootstrap.load_canonical_session_bootstrap(
                config,
                state_paths,
                loaded_threads={},
                loaded_worker_sessions={},
                loaded_in_flight={},
            )

        self.assertEqual(loaded, {})
        self.assertEqual(source, "sqlite_reset_after_import_failure")
