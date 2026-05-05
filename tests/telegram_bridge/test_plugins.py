"""Tests for Plugins — auto-split from test_bridge_core.py."""

import io
import json
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
import telegram_bridge.channel_adapter as bridge_channel_adapter
import telegram_bridge.command_routing as bridge_command_routing
import telegram_bridge.control_commands as bridge_control_commands
import telegram_bridge.engine_adapter as bridge_engine_adapter
import telegram_bridge.executor as bridge_executor
import telegram_bridge.handlers as bridge_handlers
import telegram_bridge.http_channel as bridge_http_channel
import telegram_bridge.main as bridge
import telegram_bridge.plugin_registry as bridge_plugin_registry
import telegram_bridge.prompt_execution as bridge_prompt_execution
import telegram_bridge.session_manager as bridge_session_manager
import telegram_bridge.signal_channel as bridge_signal_channel
import telegram_bridge.special_request_processing as bridge_special_request_processing
import telegram_bridge.structured_logging as bridge_structured_logging
import telegram_bridge.transport as bridge_transport
import telegram_bridge.voice_alias_commands as bridge_voice_alias_commands
import telegram_bridge.whatsapp_channel as bridge_whatsapp_channel


class TestPlugins(unittest.TestCase):
    def test_normalize_command_and_trim_output_helpers(self):
        self.assertEqual(bridge_handlers.normalize_command("/h@architect_bot now"), "/h")
        self.assertIsNone(bridge_handlers.normalize_command("hello"))
        trimmed = bridge_handlers.trim_output("x" * 40, 20)
        self.assertTrue(trimmed.endswith("[output truncated]"))
        self.assertLessEqual(len(trimmed), 20)

    def test_helper_text_uses_configured_assistant_name(self):
        cfg = make_config(assistant_name="HelperBot")
        self.assertIn("HelperBot", bridge_handlers.start_command_message(cfg))
        self.assertIn("HelperBot", bridge_handlers.build_help_text(cfg))

    def test_help_text_includes_pi_provider_commands(self):
        cfg = make_config()
        text = bridge_handlers.build_help_text(cfg)
        self.assertIn(
            "/engine status|codex|gemma|pi|reset - show or select this chat's engine",
            text,
        )
        self.assertNotIn("|venice|", text)
        self.assertIn("/model - show this chat's current model for the active engine", text)
        self.assertIn("/model list - list model choices/help for the active engine", text)
        self.assertIn("/model <name> - set this chat's model for the active engine", text)
        self.assertIn("/model reset - clear this chat's model override for the active engine", text)
        self.assertIn("/effort - show this chat's current Codex reasoning effort", text)
        self.assertIn("/effort list - list effort choices/help for the active model", text)
        self.assertIn("/effort <low|medium|high|xhigh> - set this chat's Codex reasoning effort", text)
        self.assertIn("/effort reset - clear this chat's Codex reasoning effort override", text)
        self.assertIn("/pi - show Pi provider/model status for this chat", text)
        self.assertIn("/pi providers - list available Pi providers", text)
        self.assertIn("/pi provider <name> - set this chat's Pi provider", text)
        self.assertIn("/pi reset - clear this chat's Pi provider and model overrides", text)
        self.assertIn("/dishframed - turn a menu photo into a DishFramed preview", text)

    def test_default_plugin_registry_exposes_telegram_and_codex(self):
        registry = bridge_plugin_registry.build_default_plugin_registry()
        self.assertEqual(registry.list_channels(), ["signal", "telegram", "whatsapp"])
        self.assertEqual(registry.list_engines(), ["chatgptweb", "codex", "gemma", "mavali_eth", "pi", "venice"])

    def test_default_plugin_registry_builds_default_plugins(self):
        registry = bridge_plugin_registry.build_default_plugin_registry()
        cfg = make_config()
        channel = registry.build_channel("telegram", cfg)
        engine = registry.build_engine("codex")
        self.assertIsInstance(channel, bridge_channel_adapter.TelegramChannelAdapter)
        self.assertIsInstance(engine, bridge_engine_adapter.CodexEngineAdapter)
        self.assertIsInstance(registry.build_engine("chatgptweb"), bridge_engine_adapter.ChatGPTWebEngineAdapter)
        self.assertIsInstance(registry.build_engine("chatgpt_web"), bridge_engine_adapter.ChatGPTWebEngineAdapter)
        self.assertIsInstance(registry.build_engine("gemma"), bridge_engine_adapter.GemmaEngineAdapter)
        self.assertIsInstance(registry.build_engine("pi"), bridge_engine_adapter.PiEngineAdapter)
        self.assertIsInstance(registry.build_engine("venice"), bridge_engine_adapter.VeniceEngineAdapter)

    def test_parse_plugin_name_env_uses_default_for_empty(self):
        with mock.patch.dict(os.environ, {"PLUGIN_TEST": "   "}):
            self.assertEqual(
                bridge.parse_plugin_name_env("PLUGIN_TEST", "telegram"),
                "telegram",
            )

    def test_parse_plugin_name_env_normalizes_case(self):
        with mock.patch.dict(os.environ, {"PLUGIN_TEST": "  WhAtSaPp  "}):
            self.assertEqual(
                bridge.parse_plugin_name_env("PLUGIN_TEST", "telegram"),
                "whatsapp",
            )

    def test_load_config_defaults_plugin_selection(self):
        with mock.patch.dict(
            os.environ,
            {
                "TELEGRAM_BOT_TOKEN": "token",
                "TELEGRAM_ALLOWED_CHAT_IDS": "1,2",
            },
            clear=True,
        ):
            config = bridge.load_config()
        self.assertEqual(config.channel_plugin, "telegram")
        self.assertEqual(config.engine_plugin, "codex")
        self.assertEqual(config.selectable_engine_plugins, ["codex", "gemma", "pi"])
        self.assertEqual(config.gemma_provider, "ollama_ssh")
        self.assertEqual(config.gemma_model, "gemma4:26b")
        self.assertEqual(config.pi_provider, "ollama")
        self.assertEqual(config.pi_model, "qwen3-coder:30b")
        self.assertEqual(config.pi_runner, "ssh")
        self.assertEqual(config.pi_ssh_host, "server4-beast")
        self.assertEqual(config.pi_session_mode, "none")
        self.assertEqual(config.pi_session_dir, "")
        self.assertEqual(config.pi_session_max_bytes, 2 * 1024 * 1024)
        self.assertEqual(config.pi_session_max_age_seconds, 7 * 24 * 60 * 60)
        self.assertEqual(config.pi_session_archive_retention_seconds, 14 * 24 * 60 * 60)
        self.assertEqual(config.pi_session_archive_dir, "")
        self.assertEqual(config.venice_api_key, "")
        self.assertEqual(config.venice_base_url, "https://api.venice.ai/api/v1")
        self.assertEqual(config.venice_model, "mistral-31-24b")
        self.assertEqual(config.venice_temperature, 0.2)
        self.assertEqual(config.venice_request_timeout_seconds, 180)
        self.assertEqual(config.chatgpt_web_python_bin, "python3")
        self.assertEqual(config.chatgpt_web_browser_brain_url, "http://127.0.0.1:47831")
        self.assertEqual(config.chatgpt_web_browser_brain_service, "server3-browser-brain.service")
        self.assertEqual(config.chatgpt_web_url, "https://chatgpt.com/")
        self.assertFalse(config.chatgpt_web_start_service)
        self.assertEqual(config.chatgpt_web_request_timeout_seconds, 30)
        self.assertEqual(config.chatgpt_web_ready_timeout_seconds, 45)
        self.assertEqual(config.chatgpt_web_response_timeout_seconds, 180)
        self.assertEqual(config.chatgpt_web_poll_seconds, 3.0)

    def test_load_config_reads_plugin_selection_overrides(self):
        with mock.patch.dict(
            os.environ,
            {
                "TELEGRAM_BOT_TOKEN": "token",
                "TELEGRAM_ALLOWED_CHAT_IDS": "1,2",
                "TELEGRAM_CHANNEL_PLUGIN": "  whatsapp ",
                "TELEGRAM_ENGINE_PLUGIN": "  codex ",
                "TELEGRAM_SELECTABLE_ENGINE_PLUGINS": "codex,gemma,pi,venice,chatgptweb",
                "GEMMA_PROVIDER": "ollama_http",
                "GEMMA_MODEL": "gemma-test",
                "GEMMA_BASE_URL": "http://beast:11434",
                "GEMMA_SSH_HOST": "server4-test",
                "GEMMA_REQUEST_TIMEOUT_SECONDS": "55",
                "VENICE_API_KEY": "venice-key",
                "VENICE_BASE_URL": "https://api.venice.ai/api/v1",
                "VENICE_MODEL": "venice-uncensored-1-2",
                "VENICE_TEMPERATURE": "0.4",
                "VENICE_REQUEST_TIMEOUT_SECONDS": "77",
                "CHATGPT_WEB_BRIDGE_SCRIPT": "/srv/chatgpt_web_bridge.py",
                "CHATGPT_WEB_PYTHON_BIN": "/usr/bin/python3",
                "CHATGPT_WEB_BROWSER_BRAIN_URL": "http://127.0.0.1:47831",
                "CHATGPT_WEB_BROWSER_BRAIN_SERVICE": "browser-brain-test.service",
                "CHATGPT_WEB_URL": "https://chatgpt.com/g/g-test",
                "CHATGPT_WEB_START_SERVICE": "false",
                "CHATGPT_WEB_REQUEST_TIMEOUT_SECONDS": "11",
                "CHATGPT_WEB_READY_TIMEOUT_SECONDS": "22",
                "CHATGPT_WEB_RESPONSE_TIMEOUT_SECONDS": "33",
                "CHATGPT_WEB_POLL_SECONDS": "0.5",
                "PI_PROVIDER": "ollama",
                "PI_MODEL": "pi-model",
                "PI_RUNNER": "local",
                "PI_BIN": "/usr/local/bin/pi",
                "PI_SSH_HOST": "pi-host",
                "PI_LOCAL_CWD": "/srv/local-pi",
                "PI_REMOTE_CWD": "/srv/pi",
                "PI_SESSION_MODE": "telegram_scope",
                "PI_SESSION_DIR": "/srv/pi-sessions",
                "PI_TOOLS_MODE": "allowlist",
                "PI_TOOLS_ALLOWLIST": "read,bash",
                "PI_EXTRA_ARGS": "--thinking low",
                "PI_OLLAMA_TUNNEL_ENABLED": "true",
                "PI_OLLAMA_TUNNEL_LOCAL_PORT": "19091",
                "PI_OLLAMA_TUNNEL_REMOTE_HOST": "127.0.0.2",
                "PI_OLLAMA_TUNNEL_REMOTE_PORT": "11435",
                "PI_REQUEST_TIMEOUT_SECONDS": "66",
            },
            clear=True,
        ):
            config = bridge.load_config()
        self.assertEqual(config.channel_plugin, "whatsapp")
        self.assertEqual(config.engine_plugin, "codex")
        self.assertEqual(config.selectable_engine_plugins, ["codex", "gemma", "pi", "venice", "chatgptweb"])
        self.assertEqual(config.gemma_provider, "ollama_http")
        self.assertEqual(config.gemma_model, "gemma-test")
        self.assertEqual(config.gemma_base_url, "http://beast:11434")
        self.assertEqual(config.gemma_ssh_host, "server4-test")
        self.assertEqual(config.gemma_request_timeout_seconds, 55)
        self.assertEqual(config.venice_api_key, "venice-key")
        self.assertEqual(config.venice_base_url, "https://api.venice.ai/api/v1")
        self.assertEqual(config.venice_model, "venice-uncensored-1-2")
        self.assertEqual(config.venice_temperature, 0.4)
        self.assertEqual(config.venice_request_timeout_seconds, 77)
        self.assertEqual(config.chatgpt_web_bridge_script, "/srv/chatgpt_web_bridge.py")
        self.assertEqual(config.chatgpt_web_python_bin, "/usr/bin/python3")
        self.assertEqual(config.chatgpt_web_browser_brain_url, "http://127.0.0.1:47831")
        self.assertEqual(config.chatgpt_web_browser_brain_service, "browser-brain-test.service")
        self.assertEqual(config.chatgpt_web_url, "https://chatgpt.com/g/g-test")
        self.assertFalse(config.chatgpt_web_start_service)
        self.assertEqual(config.chatgpt_web_request_timeout_seconds, 11)
        self.assertEqual(config.chatgpt_web_ready_timeout_seconds, 22)
        self.assertEqual(config.chatgpt_web_response_timeout_seconds, 33)
        self.assertEqual(config.chatgpt_web_poll_seconds, 0.5)
        self.assertEqual(config.pi_provider, "ollama")
        self.assertEqual(config.pi_model, "pi-model")
        self.assertEqual(config.pi_runner, "local")
        self.assertEqual(config.pi_bin, "/usr/local/bin/pi")
        self.assertEqual(config.pi_ssh_host, "pi-host")
        self.assertEqual(config.pi_local_cwd, "/srv/local-pi")
        self.assertEqual(config.pi_remote_cwd, "/srv/pi")
        self.assertEqual(config.pi_session_mode, "telegram_scope")
        self.assertEqual(config.pi_session_dir, "/srv/pi-sessions")
        self.assertEqual(config.pi_session_max_bytes, 2 * 1024 * 1024)
        self.assertEqual(config.pi_session_max_age_seconds, 7 * 24 * 60 * 60)
        self.assertEqual(config.pi_session_archive_retention_seconds, 14 * 24 * 60 * 60)
        self.assertEqual(config.pi_session_archive_dir, "")
        self.assertEqual(config.pi_tools_mode, "allowlist")
        self.assertEqual(config.pi_tools_allowlist, "read,bash")
        self.assertEqual(config.pi_extra_args, "--thinking low")
        self.assertTrue(config.pi_ollama_tunnel_enabled)
        self.assertEqual(config.pi_ollama_tunnel_local_port, 19091)
        self.assertEqual(config.pi_ollama_tunnel_remote_host, "127.0.0.2")
        self.assertEqual(config.pi_ollama_tunnel_remote_port, 11435)
        self.assertEqual(config.pi_request_timeout_seconds, 66)

    def test_engine_status_includes_live_gemma_health(self):
        state = bridge.State(chat_engines={"tg:1": "gemma"})
        config = make_config(engine_plugin="codex", gemma_ssh_host="server4-test")
        completed = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=json.dumps({"models": [{"name": "gemma4:26b"}]}),
            stderr="",
        )

        with (
            mock.patch.object(
                bridge_handlers.subprocess,
                "run",
                return_value=completed,
            ) as run_mock,
            mock.patch.object(
                bridge_handlers.time,
                "monotonic",
                side_effect=[100.0, 100.123],
            ),
        ):
            text = bridge_handlers.build_engine_status_text(state, config, "tg:1")

        self.assertIn("This chat engine: gemma", text)
        self.assertIn("Gemma health: ok", text)
        self.assertIn("Gemma response time: 123ms", text)
        self.assertIn("Gemma model available: yes", text)
        self.assertIn("Gemma last check error: (none)", text)
        run_mock.assert_called_once()
        self.assertIn("server4-test", run_mock.call_args.args[0])

    def test_engine_status_reports_gemma_health_error(self):
        state = bridge.State(chat_engines={"tg:1": "gemma"})
        config = make_config(engine_plugin="codex", gemma_ssh_host="server4-test")
        completed = subprocess.CompletedProcess(
            args=[],
            returncode=255,
            stdout="",
            stderr="ssh failed\nmore detail",
        )

        with (
            mock.patch.object(bridge_handlers.subprocess, "run", return_value=completed),
            mock.patch.object(
                bridge_handlers.time,
                "monotonic",
                side_effect=[200.0, 200.051],
            ),
        ):
            text = bridge_handlers.build_engine_status_text(state, config, "tg:1")

        self.assertIn("Gemma health: error", text)
        self.assertIn("Gemma response time: 50ms", text)
        self.assertIn("Gemma model available: no", text)
        self.assertIn("Gemma last check error: ssh failed more detail", text)

    def test_engine_status_includes_live_venice_health(self):
        state = bridge.State(chat_engines={"tg:1": "venice"})
        config = make_config(
            engine_plugin="codex",
            venice_api_key="venice-key",
            venice_model="mistral-31-24b",
        )
        completed = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=json.dumps({"data": [{"id": "mistral-31-24b"}], "object": "list", "type": "text"}),
            stderr="",
        )

        with (
            mock.patch.object(
                bridge_handlers.urllib_request,
                "urlopen",
                return_value=mock.MagicMock(
                    __enter__=mock.MagicMock(
                        return_value=mock.MagicMock(read=mock.MagicMock(return_value=completed.stdout.encode("utf-8")))
                    ),
                    __exit__=mock.MagicMock(return_value=False),
                ),
            ) as urlopen_mock,
            mock.patch.object(
                bridge_handlers.time,
                "monotonic",
                side_effect=[250.0, 250.05],
            ),
        ):
            text = bridge_handlers.build_engine_status_text(state, config, "tg:1")

        self.assertIn("This chat engine: venice", text)
        self.assertIn("Venice health: ok", text)
        self.assertIn("Venice response time: 50ms", text)
        self.assertIn("Venice model available: yes", text)
        self.assertIn("Venice last check error: (none)", text)
        urlopen_mock.assert_called_once()

    def test_engine_status_includes_live_chatgpt_web_health(self):
        state = bridge.State(chat_engines={"tg:1": "chatgptweb"})
        config = make_config(
            engine_plugin="codex",
            chatgpt_web_bridge_script="/srv/chatgpt_web_bridge.py",
            chatgpt_web_browser_brain_url="http://127.0.0.1:47831",
        )
        completed = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=json.dumps(
                {
                    "running": True,
                    "tabs": [{"url": "https://chatgpt.com/c/test", "tab_id": "tab-1"}],
                }
            ),
            stderr="",
        )

        with (
            mock.patch.object(
                bridge_handlers.subprocess,
                "run",
                return_value=completed,
            ) as run_mock,
            mock.patch.object(
                bridge_handlers.time,
                "monotonic",
                side_effect=[300.0, 300.027],
            ),
        ):
            text = bridge_handlers.build_engine_status_text(state, config, "tg:1")

        self.assertIn("This chat engine: chatgptweb", text)
        self.assertIn("ChatGPT web health: ok", text)
        self.assertIn("ChatGPT web response time: 26ms", text)
        self.assertIn("ChatGPT web Browser Brain running: yes", text)
        self.assertIn("ChatGPT web tab visible: yes", text)
        self.assertIn("ChatGPT web last check error: (none)", text)
        run_mock.assert_called_once()
        self.assertIn("/srv/chatgpt_web_bridge.py", run_mock.call_args.args[0])

    def test_engine_status_includes_live_pi_health(self):
        state = bridge.State(chat_engines={"tg:1": "pi"})
        config = make_config(engine_plugin="codex", pi_ssh_host="server4-test")
        version_completed = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="0.70.2\n",
            stderr="",
        )
        models_completed = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=(
                "provider  model                         context  max-out  thinking  images\n"
                "ollama    qwen3-coder:30b              128K     16.4K    no        no\n"
            ),
            stderr="",
        )

        with (
            mock.patch.object(
                bridge_handlers.subprocess,
                "run",
                side_effect=[version_completed, models_completed],
            ) as run_mock,
            mock.patch.object(
                bridge_handlers.time,
                "monotonic",
                side_effect=[300.0, 300.042],
            ),
        ):
            text = bridge_handlers.build_engine_status_text(state, config, "tg:1")

        self.assertIn("This chat engine: pi", text)
        self.assertIn("Pi health: ok", text)
        self.assertIn("Pi response time: 41ms", text)
        self.assertIn("Pi version: 0.70.2", text)
        self.assertIn("Pi model available: yes", text)
        self.assertIn("Pi last check error: (none)", text)
        self.assertIn("Pi selectability: /pi providers, /pi provider <name>, /model list, /model <name>", text)
        self.assertEqual(run_mock.call_count, 2)
        self.assertIn("server4-test", run_mock.call_args_list[0].args[0])

    def test_engine_status_shows_pi_tunnel_for_local_ollama_provider(self):
        state = bridge.State(chat_engines={"tg:1": "pi"})
        config = make_config(
            engine_plugin="codex",
            pi_runner="local",
            pi_provider="ollama",
            pi_local_cwd="/runtime/root",
            pi_ollama_tunnel_enabled=True,
            pi_ollama_tunnel_local_port=19091,
        )
        version_completed = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="0.70.2\n",
            stderr="",
        )
        models_completed = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=(
                "provider  model                         context  max-out  thinking  images\n"
                "ollama    qwen3-coder:30b              128K     16.4K    no        no\n"
            ),
            stderr="",
        )

        with (
            mock.patch.object(
                bridge_handlers.subprocess,
                "run",
                side_effect=[version_completed, models_completed],
            ) as run_mock,
            mock.patch.object(
                bridge_handlers.time,
                "monotonic",
                side_effect=[250.0, 250.05],
            ),
        ):
            text = bridge_handlers.build_engine_status_text(state, config, "tg:1")

        self.assertIn("Pi local cwd: /runtime/root", text)
        self.assertIn("Pi Ollama tunnel: 127.0.0.1:19091", text)
        first_call = run_mock.call_args_list[0]
        self.assertEqual(
            first_call.kwargs["env"]["OLLAMA_HOST"],
            "http://127.0.0.1:19091",
        )

    def test_engine_status_marks_pi_tunnel_unused_for_non_ollama_provider(self):
        state = bridge.State(chat_engines={"tg:1": "pi"})
        config = make_config(
            engine_plugin="codex",
            pi_runner="local",
            pi_provider="venice",
            pi_model="deepseek-v4-flash",
            pi_local_cwd="/runtime/root",
        )
        version_completed = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="0.70.2\n",
            stderr="",
        )
        models_completed = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=(
                "provider  model                         context  max-out  thinking  images\n"
                "venice    deepseek-v4-flash            128K     16.4K    no        no\n"
            ),
            stderr="",
        )

        with (
            mock.patch.object(
                bridge_handlers.subprocess,
                "run",
                side_effect=[version_completed, models_completed],
            ),
            mock.patch.object(
                bridge_handlers.time,
                "monotonic",
                side_effect=[250.0, 250.05],
            ),
        ):
            text = bridge_handlers.build_engine_status_text(state, config, "tg:1")

        self.assertIn("Pi provider: venice", text)
        self.assertIn("Pi local cwd: /runtime/root", text)
        self.assertIn("Pi Ollama tunnel: not used for this provider", text)

    def test_pi_provider_command_sets_provider_and_model(self):
        state = bridge.State()
        config = make_config(engine_plugin="codex", pi_provider="venice", pi_model="mistral-31-24b")
        client = FakeTelegramClient()
        completed = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=(
                "provider  model                         context  max-out  thinking  images\n"
                "deepseek  deepseek-chat               128K     16.4K    no        no\n"
                "deepseek  deepseek-reasoner           128K     16.4K    yes       no\n"
            ),
            stderr="",
        )

        with mock.patch.object(bridge_handlers.subprocess, "run", return_value=completed):
            handled = bridge_handlers.handle_pi_command(
                state=state,
                config=config,
                client=client,
                scope_key="tg:1",
                chat_id=1,
                message_thread_id=None,
                message_id=42,
                raw_text="/pi provider deepseek",
            )

        self.assertTrue(handled)
        self.assertEqual(bridge_handlers.StateRepository(state).get_chat_pi_provider("tg:1"), "deepseek")
        self.assertEqual(bridge_handlers.StateRepository(state).get_chat_pi_model("tg:1"), "deepseek-chat")
        self.assertIn("Pi provider for this chat is now deepseek", client.messages[0][1])

    def test_pi_reset_clears_provider_and_model_overrides(self):
        state = bridge.State()
        repo = bridge_handlers.StateRepository(state)
        repo.set_chat_pi_provider("tg:1", "deepseek")
        repo.set_chat_pi_model("tg:1", "deepseek-chat")
        config = make_config(engine_plugin="codex")
        client = FakeTelegramClient()

        handled = bridge_handlers.handle_pi_command(
            state=state,
            config=config,
            client=client,
            scope_key="tg:1",
            chat_id=1,
            message_thread_id=None,
            message_id=42,
            raw_text="/pi reset",
        )

        self.assertTrue(handled)
        self.assertIsNone(repo.get_chat_pi_provider("tg:1"))
        self.assertIsNone(repo.get_chat_pi_model("tg:1"))
        self.assertIn("Pi provider is now ollama", client.messages[0][1])

    def test_diary_progress_context_uses_selected_engine(self):
        state = bridge.State(chat_engines={"tg:1": "pi"})
        config = make_config(
            engine_plugin="codex",
            pi_provider="venice",
            pi_model="deepseek-v4-flash",
        )

        label = bridge_handlers.build_diary_progress_context_label(state, config, "tg:1")

        self.assertEqual(label, "(pi | venice | deepseek-v4-flash)")

    def test_engine_progress_context_uses_codex_model(self):
        config = make_config(
            engine_plugin="codex",
            codex_model="gpt-5.4-mini",
        )

        self.assertEqual(
            bridge_handlers.build_engine_progress_context_label(config, "codex"),
            "(codex | gpt-5.4-mini)",
        )

    def test_engine_status_includes_codex_model_when_selected(self):
        state = bridge.State(chat_engines={"tg:1": "codex"})
        config = make_config(
            engine_plugin="codex",
            codex_model="gpt-5.4-mini",
            codex_reasoning_effort="high",
        )

        text = bridge_handlers.build_engine_status_text(state, config, "tg:1")

        self.assertIn("This chat engine: codex", text)
        self.assertIn("Codex model: gpt-5.4-mini", text)
        self.assertIn("Codex effort: high", text)

    def test_engine_command_status_includes_inline_picker(self):
        state = bridge.State(chat_engines={"tg:1": "codex"})
        config = make_config(
            engine_plugin="codex",
            selectable_engine_plugins=["codex", "gemma", "pi", "venice"],
        )
        client = FakeTelegramClient()

        handled = bridge_handlers.handle_engine_command(
            state=state,
            config=config,
            client=client,
            scope_key="tg:1",
            chat_id=1,
            message_thread_id=None,
            message_id=42,
            raw_text="/engine",
        )

        self.assertTrue(handled)
        self.assertIn("This chat engine: codex", client.messages[0][1])
        self.assertIsInstance(client.messages[0][3], dict)
        self.assertEqual(
            client.messages[0][3]["inline_keyboard"][0][0]["callback_data"],
            "cfg|engine|codex|set",
        )
        callback_values = [
            button["callback_data"]
            for row in client.messages[0][3]["inline_keyboard"]
            for button in row
        ]
        self.assertIn(
            "cfg|model|codex|menu",
            callback_values,
        )

    def test_help_text_includes_configured_chatgptweb_engine(self):
        cfg = make_config(selectable_engine_plugins=["codex", "gemma", "pi", "chatgptweb"])
        text = bridge_handlers.build_help_text(cfg)
        self.assertIn(
            "/engine status|codex|gemma|pi|chatgptweb|reset - show or select this chat's engine",
            text,
        )

    def test_callback_query_updates_engine_menu(self):
        state = bridge.State(chat_engines={"tg:1": "codex"})
        config = make_config(
            engine_plugin="codex",
            selectable_engine_plugins=["codex", "gemma", "pi"],
        )
        client = FakeTelegramClient()
        update = {
            "update_id": 8,
            "callback_query": {
                "id": "cb-engine-1",
                "data": "cfg|engine|pi|set",
                "message": {
                    "message_id": 56,
                    "chat": {"id": 1, "type": "private"},
                    "text": "/engine",
                },
            },
        }

        bridge_handlers.handle_update(state, config, client, update, engine=None)

        self.assertEqual(bridge_handlers.StateRepository(state).get_chat_engine("tg:1"), "pi")
        self.assertEqual(client.callback_answers[0], ("cb-engine-1", "Updated."))
        self.assertIn("This chat now uses engine: pi", client.edits[0][2])
        callback_values = [
            button["callback_data"]
            for row in client.edits[0][3]["inline_keyboard"]
            for button in row
        ]
        self.assertIn(
            "cfg|model|pi|menu",
            callback_values,
        )
        self.assertIn(
            "cfg|provider|pi|menu",
            callback_values,
        )

    def test_callback_query_from_engine_menu_opens_model_menu(self):
        state = bridge.State(chat_engines={"tg:1": "codex"})
        config = make_config(
            engine_plugin="codex",
            codex_model="gpt-5.4",
        )
        client = FakeTelegramClient()
        update = {
            "update_id": 9,
            "callback_query": {
                "id": "cb-engine-model-1",
                "data": "cfg|model|codex|menu",
                "message": {
                    "message_id": 57,
                    "chat": {"id": 1, "type": "private"},
                    "text": "/engine",
                },
            },
        }

        with mock.patch.object(
            bridge_handlers.engine_controls,
            "_load_codex_model_choices",
            return_value=[("gpt-5.5", "GPT-5.5"), ("gpt-5.4", "gpt-5.4")],
        ):
            bridge_handlers.handle_update(state, config, client, update, engine=None)

        self.assertEqual(client.callback_answers[0], ("cb-engine-model-1", "Updated."))
        self.assertIn("Active engine: codex", client.edits[0][2])
        callback_values = [
            button["callback_data"]
            for row in client.edits[0][3]["inline_keyboard"]
            for button in row
        ]
        self.assertIn(
            "cfg|effort|codex|menu",
            callback_values,
        )
        self.assertIn(
            "cfg|engine|codex|menu",
            callback_values,
        )

    def test_callback_query_from_engine_menu_opens_provider_menu(self):
        state = bridge.State(chat_engines={"tg:1": "pi"})
        config = make_config(
            engine_plugin="codex",
            pi_provider="venice",
            pi_model="deepseek-v4-flash",
        )
        client = FakeTelegramClient()
        update = {
            "update_id": 12,
            "callback_query": {
                "id": "cb-provider-menu-1",
                "data": "cfg|provider|pi|menu",
                "message": {
                    "message_id": 60,
                    "chat": {"id": 1, "type": "private"},
                    "text": "/engine",
                },
            },
        }

        with mock.patch.object(
            bridge_handlers.engine_controls,
            "_pi_available_provider_names",
            return_value=["venice", "deepseek"],
        ):
            bridge_handlers.handle_update(state, config, client, update, engine=None)

        self.assertEqual(client.callback_answers[0], ("cb-provider-menu-1", "Updated."))
        self.assertIn("Available Pi providers:", client.edits[0][2])
        callback_values = [
            button["callback_data"]
            for row in client.edits[0][3]["inline_keyboard"]
            for button in row
        ]
        self.assertIn("cfg|provider|pi|set|venice", callback_values)
        self.assertIn("cfg|provider|pi|set|deepseek", callback_values)
        self.assertIn("cfg|engine|pi|menu", callback_values)

    def test_callback_query_sets_pi_provider_and_returns_to_engine_menu(self):
        state = bridge.State(chat_engines={"tg:1": "pi"})
        config = make_config(
            engine_plugin="codex",
            pi_provider="venice",
            pi_model="deepseek-v4-flash",
        )
        client = FakeTelegramClient()
        update = {
            "update_id": 13,
            "callback_query": {
                "id": "cb-provider-set-1",
                "data": "cfg|provider|pi|set|deepseek",
                "message": {
                    "message_id": 61,
                    "chat": {"id": 1, "type": "private"},
                    "text": "/engine",
                },
            },
        }

        def fake_pi_provider_model_names(runtime_config):
            if bridge_handlers.configured_pi_provider(runtime_config) == "deepseek":
                return ["deepseek-chat", "deepseek-reasoner"]
            return ["deepseek-v4-flash"]

        with mock.patch.object(
            bridge_handlers.engine_controls,
            "_pi_provider_model_names",
            side_effect=fake_pi_provider_model_names,
        ):
            bridge_handlers.handle_update(state, config, client, update, engine=None)

        repo = bridge_handlers.StateRepository(state)
        self.assertEqual(client.callback_answers[0], ("cb-provider-set-1", "Updated."))
        self.assertEqual(repo.get_chat_pi_provider("tg:1"), "deepseek")
        self.assertEqual(repo.get_chat_pi_model("tg:1"), "deepseek-chat")
        self.assertIn("Pi provider for this chat is now deepseek", client.edits[0][2])
        callback_values = [
            button["callback_data"]
            for row in client.edits[0][3]["inline_keyboard"]
            for button in row
        ]
        self.assertIn("cfg|provider|pi|menu", callback_values)
        self.assertIn("cfg|model|pi|menu", callback_values)

    def test_callback_query_from_effort_menu_goes_back_to_models(self):
        state = bridge.State(chat_engines={"tg:1": "codex"})
        config = make_config(
            engine_plugin="codex",
            codex_model="gpt-5.4",
            codex_reasoning_effort="medium",
        )
        client = FakeTelegramClient()
        update = {
            "update_id": 10,
            "callback_query": {
                "id": "cb-effort-menu-1",
                "data": "cfg|effort|codex|menu",
                "message": {
                    "message_id": 58,
                    "chat": {"id": 1, "type": "private"},
                    "text": "/model",
                },
            },
        }

        with mock.patch.object(
            bridge_handlers.engine_controls,
            "_load_codex_model_catalog",
            return_value=[
                {
                    "slug": "gpt-5.4",
                    "display_name": "gpt-5.4",
                    "supported_efforts": ["low", "medium", "high", "xhigh"],
                }
            ],
        ):
            bridge_handlers.handle_update(state, config, client, update, engine=None)

        self.assertEqual(client.callback_answers[0], ("cb-effort-menu-1", "Updated."))
        callback_values = [
            button["callback_data"]
            for row in client.edits[0][3]["inline_keyboard"]
            for button in row
        ]
        self.assertIn("cfg|model|codex|menu", callback_values)

    def test_model_command_sets_codex_model_override(self):
        state = bridge.State(chat_engines={"tg:1": "codex"})
        config = make_config(engine_plugin="codex", codex_model="gpt-5.4")
        client = FakeTelegramClient()

        with mock.patch.object(
            bridge_handlers.engine_controls,
            "_load_codex_model_choices",
            return_value=[("gpt-5.5", "GPT-5.5"), ("gpt-5.4", "gpt-5.4")],
        ):
            handled = bridge_handlers.handle_model_command(
                state=state,
                config=config,
                client=client,
                scope_key="tg:1",
                chat_id=1,
                message_thread_id=None,
                message_id=42,
                raw_text="/model GPT-5.5",
            )

        self.assertTrue(handled)
        self.assertEqual(bridge_handlers.StateRepository(state).get_chat_codex_model("tg:1"), "gpt-5.5")
        self.assertIn("Codex model for this chat is now gpt-5.5", client.messages[0][1])
        self.assertIsInstance(client.messages[0][3], dict)

    def test_model_reset_clears_codex_model_override(self):
        state = bridge.State(chat_engines={"tg:1": "codex"})
        repo = bridge_handlers.StateRepository(state)
        repo.set_chat_codex_model("tg:1", "gpt-5.5")
        config = make_config(engine_plugin="codex", codex_model="gpt-5.4")
        client = FakeTelegramClient()

        handled = bridge_handlers.handle_model_command(
            state=state,
            config=config,
            client=client,
            scope_key="tg:1",
            chat_id=1,
            message_thread_id=None,
            message_id=42,
            raw_text="/model reset",
        )

        self.assertTrue(handled)
        self.assertIsNone(repo.get_chat_codex_model("tg:1"))
        self.assertIn("Codex model is now gpt-5.4", client.messages[0][1])

    def test_effort_command_sets_codex_effort_override(self):
        state = bridge.State(chat_engines={"tg:1": "codex"})
        config = make_config(
            engine_plugin="codex",
            codex_model="gpt-5.4",
            codex_reasoning_effort="medium",
        )
        client = FakeTelegramClient()

        with mock.patch.object(
            bridge_handlers.engine_controls,
            "_load_codex_model_catalog",
            return_value=[
                {
                    "slug": "gpt-5.4",
                    "display_name": "gpt-5.4",
                    "supported_efforts": ["low", "medium", "high", "xhigh"],
                }
            ],
        ):
            handled = bridge_handlers.handle_effort_command(
                state=state,
                config=config,
                client=client,
                scope_key="tg:1",
                chat_id=1,
                message_thread_id=None,
                message_id=42,
                raw_text="/effort high",
            )

        self.assertTrue(handled)
        self.assertEqual(bridge_handlers.StateRepository(state).get_chat_codex_effort("tg:1"), "high")
        self.assertIn("Codex reasoning effort for this chat is now high", client.messages[0][1])
        self.assertIsInstance(client.messages[0][3], dict)

    def test_effort_reset_clears_codex_effort_override(self):
        state = bridge.State(chat_engines={"tg:1": "codex"})
        repo = bridge_handlers.StateRepository(state)
        repo.set_chat_codex_effort("tg:1", "high")
        config = make_config(engine_plugin="codex", codex_reasoning_effort="medium")
        client = FakeTelegramClient()

        handled = bridge_handlers.handle_effort_command(
            state=state,
            config=config,
            client=client,
            scope_key="tg:1",
            chat_id=1,
            message_thread_id=None,
            message_id=42,
            raw_text="/effort reset",
        )

        self.assertTrue(handled)
        self.assertIsNone(repo.get_chat_codex_effort("tg:1"))
        self.assertIn("Codex reasoning effort is now medium", client.messages[0][1])

    def test_callback_query_updates_codex_effort_menu(self):
        state = bridge.State(chat_engines={"tg:1": "codex"})
        config = make_config(
            engine_plugin="codex",
            codex_model="gpt-5.4",
            codex_reasoning_effort="medium",
        )
        client = FakeTelegramClient()
        update = {
            "update_id": 7,
            "callback_query": {
                "id": "cb-1",
                "data": "cfg|effort|codex|set|high",
                "message": {
                    "message_id": 55,
                    "chat": {"id": 1, "type": "private"},
                    "text": "/effort",
                },
            },
        }

        with mock.patch.object(
            bridge_handlers.engine_controls,
            "_load_codex_model_catalog",
            return_value=[
                {
                    "slug": "gpt-5.4",
                    "display_name": "gpt-5.4",
                    "supported_efforts": ["low", "medium", "high", "xhigh"],
                }
            ],
        ):
            bridge_handlers.handle_update(state, config, client, update, engine=None)

        self.assertEqual(bridge_handlers.StateRepository(state).get_chat_codex_effort("tg:1"), "high")
        self.assertEqual(client.callback_answers[0], ("cb-1", "Updated."))
        self.assertIn("Codex reasoning effort for this chat is now high", client.edits[0][2])

    def test_model_command_sets_pi_model_for_active_pi_engine(self):
        state = bridge.State(chat_engines={"tg:1": "pi"})
        config = make_config(engine_plugin="codex", pi_provider="venice", pi_model="mistral-31-24b")
        client = FakeTelegramClient()
        completed = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=(
                "provider  model                         context  max-out  thinking  images\n"
                "venice    deepseek-v4-flash            128K     16.4K    no        no\n"
            ),
            stderr="",
        )

        with mock.patch.object(bridge_handlers.subprocess, "run", return_value=completed):
            handled = bridge_handlers.handle_model_command(
                state=state,
                config=config,
                client=client,
                scope_key="tg:1",
                chat_id=1,
                message_thread_id=None,
                message_id=42,
                raw_text="/model deepseek-v4-flash",
            )

        self.assertTrue(handled)
        self.assertEqual(bridge_handlers.StateRepository(state).get_chat_pi_model("tg:1"), "deepseek-v4-flash")
        self.assertIn("Pi model for this chat is now deepseek-v4-flash", client.messages[0][1])

    def test_model_command_for_pi_uses_paged_inline_picker(self):
        state = bridge.State(chat_engines={"tg:1": "pi"})
        config = make_config(engine_plugin="codex", pi_provider="venice", pi_model="model-01")
        client = FakeTelegramClient()
        model_names = [f"model-{index:02d}" for index in range(1, 31)]

        with mock.patch.object(bridge_handlers.engine_controls, "_pi_provider_model_names", return_value=model_names):
            handled = bridge_handlers.handle_model_command(
                state=state,
                config=config,
                client=client,
                scope_key="tg:1",
                chat_id=1,
                message_thread_id=None,
                message_id=42,
                raw_text="/model",
            )

        self.assertTrue(handled)
        self.assertIsInstance(client.messages[0][3], dict)
        button_texts = [
            button["text"]
            for row in client.messages[0][3]["inline_keyboard"]
            for button in row
        ]
        self.assertIn("model-01 *", button_texts)
        self.assertIn("model-16", button_texts)
        self.assertNotIn("model-17", button_texts)
        self.assertIn("1/2", button_texts)
        self.assertIn("Next", button_texts)

    def test_callback_query_for_pi_model_page_opens_requested_page(self):
        state = bridge.State(chat_engines={"tg:1": "pi"})
        config = make_config(engine_plugin="codex", pi_provider="venice", pi_model="model-01")
        client = FakeTelegramClient()
        model_names = [f"model-{index:02d}" for index in range(1, 31)]
        update = {
            "update_id": 11,
            "callback_query": {
                "id": "cb-model-page-1",
                "data": "cfg|model|pi|page|1",
                "message": {
                    "message_id": 59,
                    "chat": {"id": 1, "type": "private"},
                    "text": "/model",
                },
            },
        }

        with mock.patch.object(bridge_handlers.engine_controls, "_pi_provider_model_names", return_value=model_names):
            bridge_handlers.handle_update(state, config, client, update, engine=None)

        self.assertEqual(client.callback_answers[0], ("cb-model-page-1", "Updated."))
        button_texts = [
            button["text"]
            for row in client.edits[0][3]["inline_keyboard"]
            for button in row
        ]
        self.assertIn("model-17", button_texts)
        self.assertIn("model-30", button_texts)
        self.assertIn("2/2", button_texts)
        self.assertIn("Prev", button_texts)
        self.assertNotIn("Next", button_texts)

    def test_pi_models_alias_points_users_to_model_list(self):
        state = bridge.State()
        config = make_config(engine_plugin="codex", pi_provider="venice", pi_model="deepseek-v4-flash")
        client = FakeTelegramClient()
        completed = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=(
                "provider  model                         context  max-out  thinking  images\n"
                "venice    deepseek-v4-flash            128K     16.4K    no        no\n"
            ),
            stderr="",
        )

        with mock.patch.object(bridge_handlers.subprocess, "run", return_value=completed):
            handled = bridge_handlers.handle_pi_command(
                state=state,
                config=config,
                client=client,
                scope_key="tg:1",
                chat_id=1,
                message_thread_id=None,
                message_id=42,
                raw_text="/pi models",
            )

        self.assertTrue(handled)
        self.assertIn(
            "Deprecated alias: `/pi models` still works for compatibility, but `/model list` is the canonical command.",
            client.messages[0][1],
        )

    def test_pi_model_alias_points_users_to_model_command(self):
        state = bridge.State()
        config = make_config(engine_plugin="codex", pi_provider="venice", pi_model="mistral-31-24b")
        client = FakeTelegramClient()
        completed = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=(
                "provider  model                         context  max-out  thinking  images\n"
                "venice    deepseek-v4-flash            128K     16.4K    no        no\n"
            ),
            stderr="",
        )

        with mock.patch.object(bridge_handlers.subprocess, "run", return_value=completed):
            handled = bridge_handlers.handle_pi_command(
                state=state,
                config=config,
                client=client,
                scope_key="tg:1",
                chat_id=1,
                message_thread_id=None,
                message_id=42,
                raw_text="/pi model deepseek-v4-flash",
            )

        self.assertTrue(handled)
        self.assertIn(
            "Deprecated alias: `/pi model` still works for compatibility, but `/model <name>` is the canonical command.",
            client.messages[0][1],
        )

    def test_model_list_for_codex_uses_local_model_cache(self):
        state = bridge.State(chat_engines={"tg:1": "codex"})
        config = make_config(engine_plugin="codex", codex_model="gpt-5.4")

        with mock.patch.object(
            bridge_handlers.engine_controls,
            "_load_codex_model_choices",
            return_value=[
                ("gpt-5.5", "GPT-5.5"),
                ("gpt-5.4", "gpt-5.4"),
                ("gpt-5.4-mini", "GPT-5.4-Mini"),
            ],
        ):
            text = bridge_handlers.build_model_list_text(state, config, "tg:1")

        self.assertIn("Available Codex models:", text)
        self.assertIn("- gpt-5.5 - GPT-5.5", text)
        self.assertIn("- gpt-5.4 (current)", text)
        self.assertIn("- gpt-5.4-mini - GPT-5.4-Mini", text)

    def test_should_discard_startup_backlog_for_telegram_only(self):
        self.assertTrue(bridge.should_discard_startup_backlog(make_config(channel_plugin="telegram")))
        self.assertFalse(bridge.should_discard_startup_backlog(make_config(channel_plugin="whatsapp")))
        self.assertFalse(bridge.should_discard_startup_backlog(make_config(channel_plugin="signal")))

    def test_maybe_reset_stale_runtime_offset_resets_to_zero_when_live_queue_restarts(self):
        config = make_config(channel_plugin="whatsapp", state_dir=tempfile.mkdtemp())

        class FakeClient:
            def get_updates(self, offset, timeout_seconds=0):
                return [
                    {"update_id": 1, "message": {}},
                    {"update_id": 2, "message": {}},
                ]

        self.assertEqual(
            bridge.maybe_reset_stale_runtime_offset(config, FakeClient(), 12),
            0,
        )

    def test_output_contains_control_directive_detects_structured_and_legacy(self):
        self.assertTrue(
            bridge_handlers.output_contains_control_directive(
                json.dumps({"telegram_outbound": {"text": "hello"}})
            )
        )
        self.assertTrue(
            bridge_handlers.output_contains_control_directive(
                "[[media:https://example.com/pic.jpg]] caption"
            )
        )
        self.assertFalse(bridge_handlers.output_contains_control_directive("just plain text"))

    def test_finalize_prompt_success_skips_trim_when_control_directive_present(self):
        config = make_config(max_output_chars=20)
        config.empty_output_message = "(No output from Architect)"
        state_repo = mock.Mock()
        progress = mock.Mock()
        client = FakeTelegramClient()
        raw_output = "[[media:https://example.com/pic.jpg]] " + ("x" * 120)
        result = bridge_handlers.subprocess.CompletedProcess(
            args=["/bin/echo"],
            returncode=0,
            stdout=raw_output,
            stderr="",
        )

        with (
            mock.patch.object(bridge_handlers, "parse_executor_output", return_value=(None, raw_output)),
            mock.patch.object(bridge_handlers, "send_executor_output", return_value="ok") as send_mock,
        ):
            bridge_handlers.finalize_prompt_success(
                state_repo=state_repo,
                config=config,
                client=client,
                chat_id=1,
                message_id=18,
                result=result,
                progress=progress,
            )

        self.assertEqual(send_mock.call_args.kwargs["output"], raw_output)

    def test_progress_reporter_can_hide_compact_elapsed_text(self):
        client = FakeSignalProgressClient()
        reporter = bridge_handlers.ProgressReporter(
            client=client,
            chat_id=1,
            reply_to_message_id=5,
            message_thread_id=None,
            assistant_name="Oracle",
            progress_label="Oracle is thinking",
            compact_elapsed_prefix="",
            compact_elapsed_suffix="",
        )

        self.assertEqual(reporter._render_progress_text(), "Oracle is thinking...")

    def test_progress_reporter_renders_engine_context_in_standard_progress_text(self):
        client = FakeSignalProgressClient()
        reporter = bridge_handlers.ProgressReporter(
            client=client,
            chat_id=1,
            reply_to_message_id=5,
            message_thread_id=None,
            assistant_name="Architect",
            progress_context_label="(pi | venice | zai-org-glm-5-1)",
        )
        reporter.started_at = 74.0
        reporter.set_phase("Finalizing response.")

        with mock.patch.object(bridge_handlers.time, "time", return_value=100.0):
            self.assertEqual(
                reporter._render_progress_text(),
                "Architect (pi | venice | zai-org-glm-5-1) is working... 26s elapsed.\nFinalizing response.",
            )

    def test_progress_reporter_passes_message_thread_id_to_progress_calls(self):
        client = FakeProgressEditClient()
        reporter = bridge_handlers.ProgressReporter(
            client=client,
            chat_id=1,
            reply_to_message_id=5,
            message_thread_id=77,
            assistant_name="Sentinel",
        )

        reporter.start()
        self.assertEqual(client.last_thread_id, 77)

        reporter._send_typing()
        self.assertEqual(client.last_thread_id, 77)

    def test_apply_voice_alias_replacements(self):
        transcript, changed = bridge_handlers.apply_voice_alias_replacements(
            "turn off master broom air con",
            [("master broom", "master bedroom"), ("air con", "aircon")],
        )
        self.assertTrue(changed)
        self.assertEqual(transcript, "turn off master bedroom aircon")

    def test_default_voice_alias_replacements_includes_claude_spelling_fix(self):
        defaults = bridge.default_voice_alias_replacements()
        self.assertIn(("clode code", "claude code"), defaults)

    def test_handle_known_command_routes_reset_to_control_commands(self):
        client = FakeTelegramClient()
        state = bridge.State()
        config = make_config()

        with mock.patch.object(bridge_control_commands, "handle_reset_command") as handler:
            handled = bridge_command_routing.handle_known_command(
                state=state,
                config=config,
                client=client,
                scope_key="tg:1",
                chat_id=1,
                message_thread_id=77,
                message_id=88,
                command="/reset",
                raw_text="/reset",
            )

        self.assertTrue(handled)
        handler.assert_called_once_with(state, config, client, "tg:1", 1, 77, 88)

    def test_handle_known_command_routes_voice_alias_to_voice_alias_commands(self):
        client = FakeTelegramClient()
        state = bridge.State()
        config = make_config()

        with mock.patch.object(
            bridge_voice_alias_commands,
            "handle_voice_alias_command",
            return_value=True,
        ) as handler:
            handled = bridge_command_routing.handle_known_command(
                state=state,
                config=config,
                client=client,
                scope_key="tg:1",
                chat_id=1,
                message_thread_id=None,
                message_id=89,
                command="/voice-alias",
                raw_text="/voice-alias list",
            )

        self.assertTrue(handled)
        handler.assert_called_once_with(
            state=state,
            config=config,
            client=client,
            chat_id=1,
            message_id=89,
            raw_text="/voice-alias list",
        )

    def test_voice_alias_command_adds_manual_alias(self):
        client = FakeTelegramClient()
        learning_store = mock.Mock()
        learning_store.add_manual.return_value = ("foo", "bar")
        state = bridge.State(voice_alias_learning_store=learning_store)

        handled = bridge_voice_alias_commands.handle_voice_alias_command(
            state=state,
            config=make_config(),
            client=client,
            chat_id=1,
            message_id=90,
            raw_text="/voice-alias add foo => bar",
        )

        self.assertTrue(handled)
        learning_store.add_manual.assert_called_once_with("foo", "bar")
        self.assertEqual(
            client.messages[-1][:3],
            (1, "Added manual voice alias: `foo` => `bar`", 90),
        )

    def test_build_status_text_uses_current_session_labels(self):
        state = bridge.State(
            canonical_sessions_enabled=True,
            chat_sessions={
                "tg:9": bridge.CanonicalSession(
                    thread_id="thread-1",
                    worker_created_at=1.0,
                    worker_last_used_at=2.0,
                ),
            },
        )
        config = make_config(persistent_workers_idle_timeout_seconds=18000)

        status_text = bridge_handlers.build_status_text(state, config, chat_id=9)

        self.assertIn("Saved Codex threads: 1", status_text)
        self.assertIn("Persistent workers: enabled=False active=1/2 idle_expiry=disabled", status_text)
        self.assertIn("This chat has Codex thread: True", status_text)
        self.assertNotIn("Saved contexts", status_text)
        self.assertNotIn("legacy_idle_timeout", status_text)

    def test_request_safe_restart_status_transitions(self):
        state = bridge.State()

        status, busy = bridge_session_manager.request_safe_restart(
            state,
            chat_id=1,
            message_thread_id=None,
            reply_to_message_id=None,
        )
        self.assertEqual(status, "run_now")
        self.assertEqual(busy, 0)

        status, busy = bridge_session_manager.request_safe_restart(
            state,
            chat_id=1,
            message_thread_id=None,
            reply_to_message_id=None,
        )
        self.assertEqual(status, "in_progress")
        self.assertEqual(busy, 0)

        bridge_session_manager.finish_restart_attempt(state)
        with state.lock:
            state.busy_chats.add(5)

        status, busy = bridge_session_manager.request_safe_restart(
            state,
            chat_id=1,
            message_thread_id=None,
            reply_to_message_id=None,
        )
        self.assertEqual(status, "queued")
        self.assertEqual(busy, 1)

        status, busy = bridge_session_manager.request_safe_restart(
            state,
            chat_id=1,
            message_thread_id=None,
            reply_to_message_id=None,
        )
        self.assertEqual(status, "already_queued")
        self.assertEqual(busy, 1)

    def test_restart_helper_uses_shared_run_status_dir_by_default(self):
        script_text = (ROOT / "ops" / "telegram-bridge" / "restart_and_verify.sh").read_text(
            encoding="utf-8"
        )

        self.assertIn(
            'RESTART_STATUS_DIR="${RESTART_STATUS_DIR:-/run/restart-and-verify}"',
            script_text,
        )

    def test_restart_helper_writes_status_marker(self):
        script_path = ROOT / "ops" / "telegram-bridge" / "restart_and_verify.sh"

        with tempfile.TemporaryDirectory() as tmpdir:
            temp_root = Path(tmpdir)
            bin_dir = temp_root / "bin"
            bin_dir.mkdir()
            state_path = temp_root / "systemctl_state.json"
            status_dir = temp_root / "status"
            status_path = status_dir / "restart_and_verify.telegram-architect-bridge.service.status.json"
            state_path.write_text(
                json.dumps(
                    {
                        "MainPID": "111",
                        "ExecMainStartTimestamp": "before-start",
                        "ExecMainStartTimestampMonotonic": "100",
                        "ActiveState": "active",
                        "SubState": "running",
                    }
                ),
                encoding="utf-8",
            )

            (bin_dir / "id").write_text("#!/usr/bin/env bash\necho 0\n", encoding="utf-8")
            (bin_dir / "id").chmod(0o755)
            (bin_dir / "systemctl").write_text(
                "\n".join(
                    [
                        "#!/usr/bin/env python3",
                        "import json",
                        "import os",
                        "import sys",
                        "from pathlib import Path",
                        "",
                        "state_path = Path(os.environ['FAKE_SYSTEMCTL_STATE'])",
                        "state = json.loads(state_path.read_text(encoding='utf-8'))",
                        "args = sys.argv[1:]",
                        "while args and args[0].startswith('-'):",
                        "    if args[0] == '-p':",
                        "        break",
                        "    args = args[1:]",
                        "cmd = args[0]",
                        "if cmd == 'show':",
                        "    key = args[2]",
                        "    print(state.get(key, ''))",
                        "    raise SystemExit(0)",
                        "if cmd == 'restart':",
                        "    state['MainPID'] = '222'",
                        "    state['ExecMainStartTimestamp'] = 'after-start'",
                        "    state['ExecMainStartTimestampMonotonic'] = '200'",
                        "    state_path.write_text(json.dumps(state), encoding='utf-8')",
                        "    raise SystemExit(0)",
                        "if cmd == 'status':",
                        "    print('fake status ok')",
                        "    raise SystemExit(0)",
                        "raise SystemExit(f'unsupported systemctl args: {sys.argv[1:]}')",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            (bin_dir / "systemctl").chmod(0o755)

            result = subprocess.run(
                ["bash", str(script_path), "--unit", "telegram-architect-bridge.service"],
                check=False,
                cwd=str(ROOT),
                env={
                    **os.environ,
                    "PATH": f"{bin_dir}:{os.environ['PATH']}",
                    "RESTART_WAIT_FOR_IDLE": "false",
                    "RESTART_STATUS_DIR": str(status_dir),
                    "FAKE_SYSTEMCTL_STATE": str(state_path),
                },
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, msg=result.stderr or result.stdout)
            self.assertTrue(status_path.exists(), msg=result.stdout)
            payload = json.loads(status_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["phase"], "completed")
            self.assertEqual(payload["verification"], "pass")
            self.assertEqual(payload["unit_name"], "telegram-architect-bridge.service")
            self.assertEqual(payload["before_main_pid"], "111")
            self.assertEqual(payload["after_main_pid"], "222")

    def test_restart_helper_hands_off_when_running_inside_target_service_cgroup(self):
        script_path = ROOT / "ops" / "telegram-bridge" / "restart_and_verify.sh"

        with tempfile.TemporaryDirectory() as tmpdir:
            temp_root = Path(tmpdir)
            bin_dir = temp_root / "bin"
            bin_dir.mkdir()
            handoff_path = temp_root / "handoff.json"
            state_path = temp_root / "systemctl_state.json"
            state_path.write_text(
                json.dumps(
                    {
                        "ControlGroup": "/system.slice/telegram-architect-bridge.service",
                    }
                ),
                encoding="utf-8",
            )

            (bin_dir / "id").write_text("#!/usr/bin/env bash\necho 0\n", encoding="utf-8")
            (bin_dir / "id").chmod(0o755)
            (bin_dir / "systemctl").write_text(
                "\n".join(
                    [
                        "#!/usr/bin/env python3",
                        "import json",
                        "import os",
                        "import sys",
                        "from pathlib import Path",
                        "",
                        "state = json.loads(Path(os.environ['FAKE_SYSTEMCTL_STATE']).read_text(encoding='utf-8'))",
                        "args = sys.argv[1:]",
                        "cmd = args[0]",
                        "if cmd == 'show':",
                        "    key = args[2]",
                        "    print(state.get(key, ''))",
                        "    raise SystemExit(0)",
                        "raise SystemExit(f'unexpected systemctl call: {sys.argv[1:]}')",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            (bin_dir / "systemctl").chmod(0o755)
            (bin_dir / "systemd-run").write_text(
                "\n".join(
                    [
                        "#!/usr/bin/env python3",
                        "import json",
                        "import os",
                        "import sys",
                        "from pathlib import Path",
                        "",
                        "Path(os.environ['FAKE_HANDOFF_PATH']).write_text(",
                        "    json.dumps({'argv': sys.argv[1:]}, indent=2),",
                        "    encoding='utf-8',",
                        ")",
                        "raise SystemExit(0)",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            (bin_dir / "systemd-run").chmod(0o755)

            result = subprocess.run(
                ["bash", str(script_path), "--unit", "telegram-architect-bridge.service"],
                check=False,
                cwd=str(ROOT),
                env={
                    **os.environ,
                    "PATH": f"{bin_dir}:{os.environ['PATH']}",
                    "FAKE_SYSTEMCTL_STATE": str(state_path),
                    "FAKE_HANDOFF_PATH": str(handoff_path),
                    "RESTART_CGROUP_PATH_OVERRIDE": "/system.slice/telegram-architect-bridge.service/app.slice",
                },
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, msg=result.stderr or result.stdout)
            self.assertTrue(handoff_path.exists(), msg=result.stdout)
            payload = json.loads(handoff_path.read_text(encoding="utf-8"))
            argv = payload["argv"]
            self.assertIn("RESTART_DETACHED_RUN=1", argv)
            self.assertIn("UNIT_NAME=telegram-architect-bridge.service", argv)
            self.assertIn(str(script_path), argv)
            self.assertIn("--unit", argv)
            self.assertIn("telegram-architect-bridge.service", argv)

