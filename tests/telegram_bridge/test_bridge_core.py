import importlib.util
import io
import json
import logging
import os
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
BRIDGE_MAIN = ROOT / "src" / "telegram_bridge" / "main.py"
BRIDGE_DIR = BRIDGE_MAIN.parent

spec = importlib.util.spec_from_file_location("telegram_bridge_main", BRIDGE_MAIN)
if spec is None or spec.loader is None:
    raise RuntimeError("Failed to load telegram bridge module spec")
bridge = importlib.util.module_from_spec(spec)
import sys
if str(BRIDGE_DIR) not in sys.path:
    sys.path.insert(0, str(BRIDGE_DIR))
spec.loader.exec_module(bridge)
import executor as bridge_executor
import handlers as bridge_handlers
import auth_state as bridge_auth_state
import channel_adapter as bridge_channel_adapter
import engine_adapter as bridge_engine_adapter
import http_channel as bridge_http_channel
import plugin_registry as bridge_plugin_registry
import signal_channel as bridge_signal_channel
import whatsapp_channel as bridge_whatsapp_channel
import session_manager as bridge_session_manager
import structured_logging as bridge_structured_logging
import transport as bridge_transport


class FakeTelegramClient:
    def __init__(self, channel_name: str = "telegram") -> None:
        self.channel_name = channel_name
        self.messages = []
        self.photos = []
        self.documents = []
        self.audios = []
        self.voices = []
        self.chat_actions = []
        self.raise_on_voice = None

    def send_message_get_id(self, chat_id, text, reply_to_message_id=None, message_thread_id=None):
        self.send_message(
            chat_id,
            text,
            reply_to_message_id=reply_to_message_id,
            message_thread_id=message_thread_id,
        )
        return len(self.messages)

    def send_message(self, chat_id, text, reply_to_message_id=None, message_thread_id=None):
        del message_thread_id
        self.messages.append((chat_id, text, reply_to_message_id))

    def send_photo(
        self,
        chat_id,
        photo,
        caption=None,
        reply_to_message_id=None,
        message_thread_id=None,
    ):
        del message_thread_id
        self.photos.append((chat_id, photo, caption, reply_to_message_id))

    def send_document(
        self,
        chat_id,
        document,
        caption=None,
        reply_to_message_id=None,
        message_thread_id=None,
    ):
        del message_thread_id
        self.documents.append((chat_id, document, caption, reply_to_message_id))

    def send_audio(
        self,
        chat_id,
        audio,
        caption=None,
        reply_to_message_id=None,
        message_thread_id=None,
    ):
        del message_thread_id
        self.audios.append((chat_id, audio, caption, reply_to_message_id))

    def send_voice(
        self,
        chat_id,
        voice,
        caption=None,
        reply_to_message_id=None,
        message_thread_id=None,
    ):
        del message_thread_id
        if self.raise_on_voice is not None:
            raise self.raise_on_voice
        self.voices.append((chat_id, voice, caption, reply_to_message_id))

    def send_chat_action(self, chat_id, action="typing", message_thread_id=None):
        del message_thread_id
        self.chat_actions.append((chat_id, action))


class FakeDownloadClient:
    def __init__(self, file_meta):
        self.file_meta = file_meta
        self.download_calls = 0

    def get_file(self, file_id):
        return dict(self.file_meta)

    def download_file_to_path(self, file_path, target_path, max_bytes, size_label="File"):
        self.download_calls += 1
        Path(target_path).write_bytes(b"x")


class FakeProgressEditClient:
    channel_name = "whatsapp"
    supports_message_edits = True

    def __init__(self) -> None:
        self.last_thread_id = None

    def send_message_get_id(
        self,
        chat_id,
        text,
        reply_to_message_id=None,
        message_thread_id=None,
    ):
        self.last_thread_id = message_thread_id
        return 101

    def edit_message(self, chat_id, message_id, text):
        raise RuntimeError("WhatsApp bridge HTTP 502: message edit failed")

    def send_chat_action(self, chat_id, action="typing", message_thread_id=None):
        self.last_thread_id = message_thread_id
        return None


class FakeSignalProgressClient:
    channel_name = "signal"
    supports_message_edits = False

    def send_message_get_id(
        self,
        chat_id,
        text,
        reply_to_message_id=None,
        message_thread_id=None,
    ):
        return 202

    def edit_message(self, chat_id, message_id, text):
        raise AssertionError("edit_message should not be called for signal")

    def send_chat_action(self, chat_id, action="typing", message_thread_id=None):
        return None


def make_config(**overrides):
    base = {
        "token": "x",
        "allowed_chat_ids": {1, 2, 3},
        "api_base": "https://api.telegram.org",
        "poll_timeout_seconds": 1,
        "retry_sleep_seconds": 0.1,
        "exec_timeout_seconds": 3,
        "max_input_chars": 4096,
        "max_output_chars": 20000,
        "max_image_bytes": 4096,
        "max_voice_bytes": 4096,
        "max_document_bytes": 4096,
        "attachment_retention_seconds": 14 * 24 * 60 * 60,
        "attachment_max_total_bytes": 10 * 1024 * 1024 * 1024,
        "rate_limit_per_minute": 12,
        "executor_cmd": ["/bin/echo"],
        "voice_transcribe_cmd": [],
        "voice_transcribe_timeout_seconds": 10,
        "voice_alias_replacements": [],
        "voice_alias_learning_enabled": True,
        "voice_alias_learning_path": "/tmp/voice_alias_learning.json",
        "voice_alias_learning_min_examples": 2,
        "voice_alias_learning_confirmation_window_seconds": 900,
        "voice_low_confidence_confirmation_enabled": True,
        "voice_low_confidence_threshold": 0.45,
        "voice_low_confidence_message": "Voice transcript confidence is low, resend",
        "state_dir": "/tmp",
        "persistent_workers_enabled": False,
        "persistent_workers_max": 2,
        "persistent_workers_idle_timeout_seconds": 120,
        "persistent_workers_policy_files": [],
        "canonical_sessions_enabled": False,
        "canonical_legacy_mirror_enabled": False,
        "canonical_sqlite_enabled": False,
        "canonical_sqlite_path": "/tmp/chat_sessions.sqlite3",
        "canonical_json_mirror_enabled": False,
        "memory_sqlite_path": "/tmp/memory.sqlite3",
        "memory_max_messages_per_key": 4000,
        "memory_max_summaries_per_key": 80,
        "memory_prune_interval_seconds": 300,
        "required_prefixes": [],
        "required_prefix_ignore_case": True,
        "require_prefix_in_private": True,
        "allow_private_chats_unlisted": False,
        "allow_group_chats_unlisted": False,
        "assistant_name": "Architect",
        "shared_memory_key": "",
        "channel_plugin": "telegram",
        "engine_plugin": "codex",
        "selectable_engine_plugins": ["codex", "gemma", "pi"],
        "gemma_provider": "ollama_ssh",
        "gemma_model": "gemma4:26b",
        "gemma_base_url": "http://127.0.0.1:11434",
        "gemma_ssh_host": "server4-beast",
        "gemma_request_timeout_seconds": 180,
        "pi_provider": "ollama",
        "pi_model": "gemma4:26b",
        "pi_runner": "ssh",
        "pi_bin": "pi",
        "pi_ssh_host": "server4-beast",
        "pi_local_cwd": "/tmp",
        "pi_remote_cwd": "/tmp",
        "pi_tools_mode": "default",
        "pi_tools_allowlist": "",
        "pi_extra_args": "",
        "pi_ollama_tunnel_enabled": True,
        "pi_ollama_tunnel_local_port": 11435,
        "pi_ollama_tunnel_remote_host": "127.0.0.1",
        "pi_ollama_tunnel_remote_port": 11434,
        "pi_request_timeout_seconds": 180,
        "whatsapp_plugin_enabled": False,
        "whatsapp_bridge_api_base": "http://127.0.0.1:8787",
        "whatsapp_bridge_auth_token": "",
        "whatsapp_poll_timeout_seconds": 20,
        "signal_plugin_enabled": False,
        "signal_bridge_api_base": "http://127.0.0.1:18797",
        "signal_bridge_auth_token": "",
        "signal_poll_timeout_seconds": 20,
        "keyword_routing_enabled": True,
        "diary_mode_enabled": False,
        "diary_capture_quiet_window_seconds": 75,
        "diary_timezone": "Australia/Brisbane",
        "diary_local_root": "/tmp/diary",
        "diary_nextcloud_enabled": False,
        "diary_nextcloud_base_url": "",
        "diary_nextcloud_username": "",
        "diary_nextcloud_app_password": "",
        "diary_nextcloud_remote_root": "/Diary",
    }
    base.update(overrides)
    return bridge.Config(**base)


class BridgeCoreTests(unittest.TestCase):
    def test_parse_executor_output_json_stream(self):
        sample_stream = (
            '{"type":"thread.started","thread_id":"thread-123"}\n'
            '{"type":"item.completed","item":{"type":"agent_message","text":"hello"}}\n'
        )
        thread_id, output = bridge.parse_executor_output(sample_stream)
        self.assertEqual(thread_id, "thread-123")
        self.assertEqual(output, "hello")

    def test_bounded_text_buffer_marks_truncation(self):
        buffer = bridge.BoundedTextBuffer(
            64,
            head_chars=12,
            truncation_marker="\n...[truncated]...\n",
        )
        buffer.append("HEAD-SECTION-")
        buffer.append("x" * 200)
        rendered = buffer.render()
        self.assertLessEqual(len(rendered), 64)
        self.assertIn("...[truncated]...", rendered)
        self.assertTrue(rendered.startswith("HEAD-SECTION"))

    def test_to_telegram_chunks_uses_real_newline_prefix(self):
        chunks = bridge.to_telegram_chunks("x" * 5000)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(chunks[0].startswith("[1/2]\n"))
        self.assertNotIn("\\n", chunks[0][:10])

    def test_parse_stream_json_line_rejects_invalid_payloads(self):
        self.assertIsNone(bridge_executor.parse_stream_json_line("not-json"))
        self.assertIsNone(bridge_executor.parse_stream_json_line("[]"))
        self.assertIsNone(bridge_executor.parse_stream_json_line(""))

    def test_should_reset_thread_after_resume_failure_markers(self):
        self.assertTrue(
            bridge_executor.should_reset_thread_after_resume_failure(
                "Thread not found for resume",
                "",
            )
        )
        self.assertFalse(
            bridge_executor.should_reset_thread_after_resume_failure(
                "permission denied",
                "generic error",
            )
        )

    def test_executor_script_uses_default_runtime_root_without_embedding_policy(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_root = Path(tmpdir)
            repo_root = temp_root / "govorunbot"
            script_dir = repo_root / "src" / "telegram_bridge"
            script_dir.mkdir(parents=True)
            script_path = script_dir / "executor.sh"
            script_path.write_text(
                (ROOT / "src" / "telegram_bridge" / "executor.sh").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            script_path.chmod(0o755)
            (repo_root / "AGENTS.md").write_text("TEMP_GOVORUN_POLICY\n", encoding="utf-8")

            bin_dir = temp_root / "bin"
            bin_dir.mkdir()
            fake_codex = bin_dir / "codex"
            fake_codex.write_text(
                "\n".join(
                    [
                        "#!/usr/bin/env python3",
                        "import json",
                        "import os",
                        "import sys",
                        "payload = sys.stdin.read()",
                        "print(json.dumps({",
                        "    'type': 'item.completed',",
                        "    'item': {",
                        "        'type': 'agent_message',",
                        "        'text': f'PWD={os.getcwd()}\\n{payload}',",
                        "    },",
                        "}))",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            fake_codex.chmod(0o755)

            env = os.environ.copy()
            env["PATH"] = f"{bin_dir}:{env.get('PATH', '')}"
            env["CODEX_BIN"] = str(fake_codex)
            env["CODEX_POLICY_FILE"] = "AGENTS.md"
            env.pop("TELEGRAM_RUNTIME_ROOT", None)
            env.pop("TELEGRAM_SHARED_CORE_ROOT", None)
            env.pop("TELEGRAM_CODEX_WORKDIR", None)

            result = subprocess.run(
                ["bash", str(script_path), "new"],
                input="hello from test\n",
                text=True,
                capture_output=True,
                cwd=str(ROOT),
                env=env,
                check=False,
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertIn(f"PWD={repo_root}", result.stdout)
            self.assertNotIn("TEMP_GOVORUN_POLICY", result.stdout)
            self.assertIn("User request:\\nhello from test", result.stdout)

    def test_executor_script_runs_from_runtime_root_overlay_without_embedding_policy(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_root = Path(tmpdir)
            shared_root = temp_root / "matrix"
            script_dir = shared_root / "src" / "telegram_bridge"
            script_dir.mkdir(parents=True)
            script_path = script_dir / "executor.sh"
            script_path.write_text(
                (ROOT / "src" / "telegram_bridge" / "executor.sh").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            script_path.chmod(0o755)

            runtime_root = temp_root / "oraclebot"
            runtime_root.mkdir(parents=True)
            (runtime_root / "AGENTS.md").write_text("TEMP_ORACLE_POLICY\n", encoding="utf-8")

            bin_dir = temp_root / "bin"
            bin_dir.mkdir()
            fake_codex = bin_dir / "codex"
            fake_codex.write_text(
                "\n".join(
                    [
                        "#!/usr/bin/env python3",
                        "import json",
                        "import os",
                        "import sys",
                        "payload = sys.stdin.read()",
                        "print(json.dumps({",
                        "    'type': 'item.completed',",
                        "    'item': {",
                        "        'type': 'agent_message',",
                        "        'text': f'PWD={os.getcwd()}\\n{payload}',",
                        "    },",
                        "}))",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            fake_codex.chmod(0o755)

            env = os.environ.copy()
            env["PATH"] = f"{bin_dir}:{env.get('PATH', '')}"
            env["CODEX_BIN"] = str(fake_codex)
            env["CODEX_POLICY_FILE"] = "AGENTS.md"
            env.pop("TELEGRAM_SHARED_CORE_ROOT", None)
            env.pop("TELEGRAM_CODEX_WORKDIR", None)
            env["TELEGRAM_RUNTIME_ROOT"] = str(runtime_root)

            result = subprocess.run(
                ["bash", str(script_path), "new"],
                input="hello from overlay test\n",
                text=True,
                capture_output=True,
                cwd=str(ROOT),
                env=env,
                check=False,
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertIn(f"PWD={runtime_root}", result.stdout)
            self.assertNotIn("TEMP_ORACLE_POLICY", result.stdout)
            self.assertIn("User request:\\nhello from overlay test", result.stdout)

    def test_executor_script_runs_auth_sync_hook_when_available(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_root = Path(tmpdir)
            repo_root = temp_root / "matrix"
            script_dir = repo_root / "src" / "telegram_bridge"
            script_dir.mkdir(parents=True)
            script_path = script_dir / "executor.sh"
            script_path.write_text(
                (ROOT / "src" / "telegram_bridge" / "executor.sh").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            script_path.chmod(0o755)

            sync_dir = repo_root / "ops" / "codex"
            sync_dir.mkdir(parents=True)
            marker_path = repo_root / "auth-sync.marker"
            sync_script = sync_dir / "sync_shared_auth.sh"
            sync_script.write_text(
                "#!/usr/bin/env bash\n"
                "set -euo pipefail\n"
                f"printf 'synced\\n' > {str(marker_path)!r}\n",
                encoding="utf-8",
            )
            sync_script.chmod(0o755)

            bin_dir = temp_root / "bin"
            bin_dir.mkdir()
            fake_codex = bin_dir / "codex"
            fake_codex.write_text(
                "\n".join(
                    [
                        "#!/usr/bin/env python3",
                        "import json",
                        "import sys",
                        "payload = sys.stdin.read()",
                        "print(json.dumps({",
                        "    'type': 'item.completed',",
                        "    'item': {",
                        "        'type': 'agent_message',",
                        "        'text': payload,",
                        "    },",
                        "}))",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            fake_codex.chmod(0o755)

            env = os.environ.copy()
            env["PATH"] = f"{bin_dir}:{env.get('PATH', '')}"
            env["CODEX_BIN"] = str(fake_codex)

            result = subprocess.run(
                ["bash", str(script_path), "new"],
                input="hello with auth sync\n",
                text=True,
                capture_output=True,
                cwd=str(ROOT),
                env=env,
                check=False,
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertEqual(marker_path.read_text(encoding="utf-8"), "synced\n")

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

    def test_whatsapp_help_text_is_minimal(self):
        cfg = make_config(channel_plugin="whatsapp")
        text = bridge_handlers.build_help_text(cfg)
        self.assertIn("Available commands:", text)
        self.assertIn("/start - verify bridge connectivity", text)
        self.assertIn("/help or /h - show this message", text)
        self.assertIn("/status - show bridge status and context", text)
        self.assertIn("/reset - clear saved context for this chat", text)
        self.assertIn("/cancel - cancel current in-flight request for this chat", text)
        self.assertIn("/restart - queue a safe bridge restart", text)
        self.assertIn(
            "/voice-alias add <source> => <target> - add approved alias manually",
            text,
        )
        self.assertNotIn("/voice-alias list", text)
        self.assertNotIn("/voice-alias approve", text)
        self.assertNotIn("server3-tv-start", text)
        self.assertNotIn("Use `HA ...`", text)
        self.assertNotIn("/memory mode", text)

    def test_default_plugin_registry_exposes_telegram_and_codex(self):
        registry = bridge_plugin_registry.build_default_plugin_registry()
        self.assertEqual(registry.list_channels(), ["signal", "telegram", "whatsapp"])
        self.assertEqual(registry.list_engines(), ["codex", "gemma", "mavali_eth", "pi"])

    def test_default_plugin_registry_builds_default_plugins(self):
        registry = bridge_plugin_registry.build_default_plugin_registry()
        cfg = make_config()
        channel = registry.build_channel("telegram", cfg)
        engine = registry.build_engine("codex")
        self.assertIsInstance(channel, bridge_channel_adapter.TelegramChannelAdapter)
        self.assertIsInstance(engine, bridge_engine_adapter.CodexEngineAdapter)
        self.assertIsInstance(registry.build_engine("gemma"), bridge_engine_adapter.GemmaEngineAdapter)
        self.assertIsInstance(registry.build_engine("pi"), bridge_engine_adapter.PiEngineAdapter)

    def test_default_plugin_registry_whatsapp_disabled_fails_fast(self):
        registry = bridge_plugin_registry.build_default_plugin_registry()
        with self.assertRaises(RuntimeError):
            registry.build_channel("whatsapp", make_config())

    def test_default_plugin_registry_builds_whatsapp_adapter_when_enabled(self):
        registry = bridge_plugin_registry.build_default_plugin_registry()
        channel = registry.build_channel(
            "whatsapp",
            make_config(whatsapp_plugin_enabled=True),
        )
        self.assertIsInstance(channel, bridge_whatsapp_channel.WhatsAppChannelAdapter)

    def test_default_plugin_registry_builds_signal_adapter_when_enabled(self):
        registry = bridge_plugin_registry.build_default_plugin_registry()
        channel = registry.build_channel(
            "signal",
            make_config(signal_plugin_enabled=True),
        )
        self.assertIsInstance(channel, bridge_signal_channel.SignalChannelAdapter)

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

    def test_memory_engine_channel_key_namespaces_channels(self):
        self.assertEqual(bridge.MemoryEngine.channel_key("telegram", 42), "tg:42")
        self.assertEqual(bridge.MemoryEngine.channel_key("whatsapp", 42), "wa:42")
        self.assertEqual(bridge.MemoryEngine.channel_key("signal", 42), "sig:42")
        self.assertEqual(bridge.MemoryEngine.channel_key("custom-bridge", 42), "custom_bridge:42")

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
        self.assertEqual(config.pi_model, "gemma4:26b")
        self.assertEqual(config.pi_runner, "ssh")
        self.assertEqual(config.pi_ssh_host, "server4-beast")

    def test_load_config_reads_plugin_selection_overrides(self):
        with mock.patch.dict(
            os.environ,
            {
                "TELEGRAM_BOT_TOKEN": "token",
                "TELEGRAM_ALLOWED_CHAT_IDS": "1,2",
                "TELEGRAM_CHANNEL_PLUGIN": "  whatsapp ",
                "TELEGRAM_ENGINE_PLUGIN": "  codex ",
                "TELEGRAM_SELECTABLE_ENGINE_PLUGINS": "codex,gemma,pi",
                "GEMMA_PROVIDER": "ollama_http",
                "GEMMA_MODEL": "gemma-test",
                "GEMMA_BASE_URL": "http://beast:11434",
                "GEMMA_SSH_HOST": "server4-test",
                "GEMMA_REQUEST_TIMEOUT_SECONDS": "55",
                "PI_PROVIDER": "ollama",
                "PI_MODEL": "pi-model",
                "PI_RUNNER": "local",
                "PI_BIN": "/usr/local/bin/pi",
                "PI_SSH_HOST": "pi-host",
                "PI_LOCAL_CWD": "/srv/local-pi",
                "PI_REMOTE_CWD": "/srv/pi",
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
        self.assertEqual(config.selectable_engine_plugins, ["codex", "gemma", "pi"])
        self.assertEqual(config.gemma_provider, "ollama_http")
        self.assertEqual(config.gemma_model, "gemma-test")
        self.assertEqual(config.gemma_base_url, "http://beast:11434")
        self.assertEqual(config.gemma_ssh_host, "server4-test")
        self.assertEqual(config.gemma_request_timeout_seconds, 55)
        self.assertEqual(config.pi_provider, "ollama")
        self.assertEqual(config.pi_model, "pi-model")
        self.assertEqual(config.pi_runner, "local")
        self.assertEqual(config.pi_bin, "/usr/local/bin/pi")
        self.assertEqual(config.pi_ssh_host, "pi-host")
        self.assertEqual(config.pi_local_cwd, "/srv/local-pi")
        self.assertEqual(config.pi_remote_cwd, "/srv/pi")
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

    def test_engine_status_includes_live_pi_health(self):
        state = bridge.State(chat_engines={"tg:1": "pi"})
        config = make_config(engine_plugin="codex", pi_ssh_host="server4-test")
        completed = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="gemma4:26b latest 1 GB\n",
            stderr="0.70.2\n",
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
        run_mock.assert_called_once()
        self.assertIn("server4-test", run_mock.call_args.args[0])

    def test_load_config_reads_whatsapp_plugin_settings(self):
        with mock.patch.dict(
            os.environ,
            {
                "TELEGRAM_BOT_TOKEN": "token",
                "TELEGRAM_ALLOWED_CHAT_IDS": "1",
                "WHATSAPP_PLUGIN_ENABLED": "true",
                "WHATSAPP_BRIDGE_API_BASE": "http://localhost:9876",
                "WHATSAPP_BRIDGE_AUTH_TOKEN": "secret",
                "WHATSAPP_POLL_TIMEOUT_SECONDS": "33",
            },
            clear=True,
        ):
            config = bridge.load_config()
        self.assertTrue(config.whatsapp_plugin_enabled)
        self.assertEqual(config.whatsapp_bridge_api_base, "http://localhost:9876")
        self.assertEqual(config.whatsapp_bridge_auth_token, "secret")
        self.assertEqual(config.whatsapp_poll_timeout_seconds, 33)

    def test_load_config_reads_signal_plugin_settings(self):
        with mock.patch.dict(
            os.environ,
            {
                "TELEGRAM_CHANNEL_PLUGIN": "signal",
                "SIGNAL_PLUGIN_ENABLED": "true",
                "SIGNAL_BRIDGE_API_BASE": "http://localhost:8797",
                "SIGNAL_BRIDGE_AUTH_TOKEN": "signal-secret",
                "SIGNAL_POLL_TIMEOUT_SECONDS": "21",
                "TELEGRAM_ALLOW_PRIVATE_CHATS_UNLISTED": "true",
                "TELEGRAM_ALLOW_GROUP_CHATS_UNLISTED": "true",
                "TELEGRAM_KEYWORD_ROUTING_ENABLED": "false",
            },
            clear=True,
        ):
            config = bridge.load_config()
        self.assertEqual(config.channel_plugin, "signal")
        self.assertTrue(config.signal_plugin_enabled)
        self.assertEqual(config.signal_bridge_api_base, "http://localhost:8797")
        self.assertEqual(config.signal_bridge_auth_token, "signal-secret")
        self.assertEqual(config.signal_poll_timeout_seconds, 21)
        self.assertTrue(config.allow_private_chats_unlisted)
        self.assertTrue(config.allow_group_chats_unlisted)
        self.assertFalse(config.keyword_routing_enabled)
        self.assertEqual(config.allowed_chat_ids, set())

    def test_load_config_defaults_signal_bridge_port_to_18797(self):
        with mock.patch.dict(
            os.environ,
            {
                "TELEGRAM_CHANNEL_PLUGIN": "signal",
                "SIGNAL_PLUGIN_ENABLED": "true",
                "TELEGRAM_ALLOW_PRIVATE_CHATS_UNLISTED": "true",
                "TELEGRAM_ALLOW_GROUP_CHATS_UNLISTED": "true",
            },
            clear=True,
        ):
            config = bridge.load_config()
        self.assertEqual(config.signal_bridge_api_base, "http://127.0.0.1:18797")

    def test_should_discard_startup_backlog_for_telegram_only(self):
        self.assertTrue(bridge.should_discard_startup_backlog(make_config(channel_plugin="telegram")))
        self.assertFalse(bridge.should_discard_startup_backlog(make_config(channel_plugin="whatsapp")))
        self.assertFalse(bridge.should_discard_startup_backlog(make_config(channel_plugin="signal")))

    def test_should_resume_saved_update_offset_for_non_telegram_only(self):
        self.assertFalse(bridge.should_resume_saved_update_offset(make_config(channel_plugin="telegram")))
        self.assertTrue(bridge.should_resume_saved_update_offset(make_config(channel_plugin="whatsapp")))
        self.assertTrue(bridge.should_resume_saved_update_offset(make_config(channel_plugin="signal")))

    def test_should_reset_saved_update_offset_only_when_queue_counter_rolls_back(self):
        self.assertFalse(bridge.should_reset_saved_update_offset(0, 3))
        self.assertFalse(bridge.should_reset_saved_update_offset(10, None))
        self.assertFalse(bridge.should_reset_saved_update_offset(10, 9))
        self.assertTrue(bridge.should_reset_saved_update_offset(10, 2))

    def test_load_saved_update_offset_ignores_invalid_values(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            offset_path = Path(tmpdir) / "offset.txt"
            offset_path.write_text("bad-value\n", encoding="utf-8")
            self.assertEqual(bridge.load_saved_update_offset(str(offset_path)), 0)
            offset_path.write_text("-7\n", encoding="utf-8")
            self.assertEqual(bridge.load_saved_update_offset(str(offset_path)), 0)

    def test_compute_initial_update_offset_resets_when_queue_counter_restarts(self):
        config = make_config(channel_plugin="whatsapp", state_dir=tempfile.mkdtemp())
        offset_path = Path(config.state_dir) / "whatsapp_update_offset.txt"
        bridge.persist_saved_update_offset(str(offset_path), 40)

        class FakeClient:
            def get_updates(self, offset, timeout_seconds=0):
                self.last_offset = offset
                self.last_timeout_seconds = timeout_seconds
                return [
                    {"update_id": 1, "message": {}},
                    {"update_id": 2, "message": {}},
                    {"update_id": 3, "message": {}},
                ]

        client = FakeClient()
        offset, state_path = bridge.compute_initial_update_offset(config, client)
        self.assertEqual(offset, 0)
        self.assertEqual(state_path, str(offset_path))
        self.assertEqual(client.last_offset, 0)
        self.assertEqual(client.last_timeout_seconds, 0)

    def test_compute_initial_update_offset_reuses_saved_offset_with_live_queue(self):
        config = make_config(channel_plugin="whatsapp", state_dir=tempfile.mkdtemp())
        offset_path = Path(config.state_dir) / "whatsapp_update_offset.txt"
        bridge.persist_saved_update_offset(str(offset_path), 10)

        class FakeClient:
            def get_updates(self, offset, timeout_seconds=0):
                return [
                    {"update_id": 8, "message": {}},
                    {"update_id": 9, "message": {}},
                ]

        offset, state_path = bridge.compute_initial_update_offset(config, FakeClient())
        self.assertEqual(offset, 10)
        self.assertEqual(state_path, str(offset_path))

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

    def test_load_config_reads_require_prefix_in_private_override(self):
        with mock.patch.dict(
            os.environ,
            {
                "TELEGRAM_BOT_TOKEN": "token",
                "TELEGRAM_ALLOWED_CHAT_IDS": "1",
                "TELEGRAM_REQUIRED_PREFIXES": "@tank",
                "TELEGRAM_REQUIRE_PREFIX_IN_PRIVATE": "false",
            },
            clear=True,
        ):
            config = bridge.load_config()
        self.assertEqual(config.required_prefixes, ["@tank"])
        self.assertFalse(config.require_prefix_in_private)

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

    def test_whatsapp_adapter_send_message_get_id_posts_json(self):
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return b'{"ok": true, "result": {"message_id": 321}}'

        config = make_config(
            whatsapp_plugin_enabled=True,
            whatsapp_bridge_api_base="http://127.0.0.1:8787",
            whatsapp_bridge_auth_token="token-1",
        )
        adapter = bridge_whatsapp_channel.WhatsAppChannelAdapter(config)
        with mock.patch.object(bridge_http_channel, "urlopen", return_value=Response()) as mocked:
            message_id = adapter.send_message_get_id(
                chat_id=123,
                text="hello",
                reply_to_message_id=55,
            )

        self.assertEqual(message_id, 321)
        request = mocked.call_args.args[0]
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.full_url, "http://127.0.0.1:8787/messages")
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(payload["chat_id"], "123")
        self.assertEqual(payload["text"], "hello")
        self.assertEqual(payload["reply_to_message_id"], "55")
        self.assertEqual(request.get_header("Authorization"), "Bearer token-1")

    def test_whatsapp_adapter_send_voice_posts_media_payload(self):
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return b'{"ok": true, "result": {"message_id": 654}}'

        config = make_config(
            whatsapp_plugin_enabled=True,
            whatsapp_bridge_api_base="http://127.0.0.1:8787",
            whatsapp_bridge_auth_token="token-2",
        )
        adapter = bridge_whatsapp_channel.WhatsAppChannelAdapter(config)
        with mock.patch.object(bridge_http_channel, "urlopen", return_value=Response()) as mocked:
            adapter.send_voice(
                chat_id=123,
                voice="https://example.com/note.ogg",
                caption="voice caption",
                reply_to_message_id=77,
            )

        request = mocked.call_args.args[0]
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.full_url, "http://127.0.0.1:8787/media")
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(payload["chat_id"], "123")
        self.assertEqual(payload["media_ref"], "https://example.com/note.ogg")
        self.assertEqual(payload["media_type"], "voice")
        self.assertEqual(payload["caption"], "voice caption")
        self.assertEqual(payload["reply_to_message_id"], "77")

    def test_signal_adapter_send_message_get_id_posts_json(self):
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return b'{"ok": true, "result": {"message_id": 987}}'

        config = make_config(
            signal_plugin_enabled=True,
            signal_bridge_api_base="http://127.0.0.1:18797",
            signal_bridge_auth_token="signal-token",
        )
        adapter = bridge_signal_channel.SignalChannelAdapter(config)
        with mock.patch.object(bridge_http_channel, "urlopen", return_value=Response()) as mocked:
            message_id = adapter.send_message_get_id(chat_id=33, text="hi")

        self.assertEqual(message_id, 987)
        request = mocked.call_args.args[0]
        self.assertEqual(request.full_url, "http://127.0.0.1:18797/messages")
        self.assertEqual(request.get_header("Authorization"), "Bearer signal-token")

    def test_signal_adapter_disables_message_edits(self):
        adapter = bridge_signal_channel.SignalChannelAdapter(
            make_config(signal_plugin_enabled=True),
        )
        self.assertFalse(adapter.supports_message_edits)
        with self.assertRaises(RuntimeError):
            adapter.edit_message(chat_id=1, message_id=2, text="ignored")

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

    def test_send_executor_output_supports_structured_envelope(self):
        client = FakeTelegramClient()
        rendered = bridge_handlers.send_executor_output(
            client=client,
            chat_id=1,
            message_id=16,
            output=json.dumps(
                {
                    "telegram_outbound": {
                        "text": "photo caption",
                        "media_ref": "https://example.com/pic.jpg",
                    }
                }
            ),
        )
        self.assertEqual(rendered, "photo caption")
        self.assertEqual(len(client.photos), 1)
        self.assertEqual(client.photos[0][1], "https://example.com/pic.jpg")

    def test_send_executor_output_sends_whatsapp_plain_text_with_prefix(self):
        client = FakeTelegramClient(channel_name="whatsapp")
        rendered = bridge_handlers.send_executor_output(
            client=client,
            chat_id=1,
            message_id=116,
            output="hello there",
        )
        self.assertEqual(rendered, "Даю справку: hello there")
        self.assertEqual(client.messages[-1][1], "Даю справку: hello there")

    def test_send_executor_output_rewrites_whatsapp_legacy_prefix(self):
        client = FakeTelegramClient(channel_name="whatsapp")
        rendered = bridge_handlers.send_executor_output(
            client=client,
            chat_id=1,
            message_id=117,
            output="Говорун: already prefixed",
        )
        self.assertEqual(rendered, "Даю справку: already prefixed")
        self.assertEqual(client.messages[-1][1], "Даю справку: already prefixed")

    def test_send_executor_output_keeps_whatsapp_new_prefix_single(self):
        client = FakeTelegramClient(channel_name="whatsapp")
        rendered = bridge_handlers.send_executor_output(
            client=client,
            chat_id=1,
            message_id=117,
            output="Даю справку: already prefixed",
        )
        self.assertEqual(rendered, "Даю справку: already prefixed")
        self.assertEqual(client.messages[-1][1], "Даю справку: already prefixed")

    def test_send_executor_output_sends_whatsapp_media_caption_with_prefix(self):
        client = FakeTelegramClient(channel_name="whatsapp")
        rendered = bridge_handlers.send_executor_output(
            client=client,
            chat_id=1,
            message_id=118,
            output="[[media:https://example.com/pic.jpg]] caption",
        )
        self.assertEqual(rendered, "Даю справку: caption")
        self.assertEqual(client.photos[0][2], "Даю справку: caption")

    def test_send_executor_output_invalid_structured_payload_falls_back_to_raw_text(self):
        client = FakeTelegramClient()
        output = '{"telegram_outbound":"bad"}'
        rendered = bridge_handlers.send_executor_output(
            client=client,
            chat_id=1,
            message_id=17,
            output=output,
        )
        self.assertEqual(rendered, output)
        self.assertEqual(client.messages[-1][1], output)
        self.assertEqual(len(client.photos), 0)

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

    def test_send_executor_output_routes_audio_to_voice_when_requested(self):
        client = FakeTelegramClient()
        rendered = bridge_handlers.send_executor_output(
            client=client,
            chat_id=1,
            message_id=7,
            output="[[media:/tmp/note.ogg]] [[audio_as_voice]] voice caption",
        )
        self.assertEqual(rendered, "voice caption")
        self.assertEqual(len(client.voices), 1)
        self.assertEqual(len(client.audios), 0)
        self.assertEqual(client.chat_actions, [(1, "record_voice"), (1, "upload_voice")])

    def test_send_executor_output_falls_back_to_audio_when_voice_forbidden(self):
        client = FakeTelegramClient()
        client.raise_on_voice = RuntimeError(
            "Telegram API sendVoice failed: 400 Bad Request: VOICE_MESSAGES_FORBIDDEN"
        )
        rendered = bridge_handlers.send_executor_output(
            client=client,
            chat_id=1,
            message_id=8,
            output="[[media:/tmp/note.ogg]] [[audio_as_voice]] fallback caption",
        )
        self.assertEqual(rendered, "fallback caption")
        self.assertEqual(len(client.voices), 0)
        self.assertEqual(len(client.audios), 1)
        self.assertEqual(client.audios[0][2], "fallback caption")
        self.assertEqual(
            client.chat_actions,
            [(1, "record_voice"), (1, "upload_voice"), (1, "upload_audio")],
        )

    def test_send_executor_output_emits_delivery_events_for_voice_fallback(self):
        client = FakeTelegramClient()
        client.raise_on_voice = RuntimeError(
            "Telegram API sendVoice failed: 400 Bad Request: VOICE_MESSAGES_FORBIDDEN"
        )
        with mock.patch.object(bridge_handlers, "emit_event") as emit_mock:
            bridge_handlers.send_executor_output(
                client=client,
                chat_id=1,
                message_id=12,
                output="[[media:/tmp/note.ogg]] [[audio_as_voice]] fallback caption",
            )

        event_names = [call.args[0] for call in emit_mock.call_args_list]
        self.assertIn("bridge.outbound_delivery_attempt", event_names)
        self.assertIn("bridge.outbound_delivery_fallback", event_names)
        self.assertIn("bridge.outbound_delivery_succeeded", event_names)

    def test_send_executor_output_emits_failed_event_when_media_send_crashes(self):
        client = FakeTelegramClient()
        client.send_document = mock.Mock(side_effect=RuntimeError("disk gone"))
        with mock.patch.object(bridge_handlers, "emit_event") as emit_mock:
            rendered = bridge_handlers.send_executor_output(
                client=client,
                chat_id=1,
                message_id=13,
                output="[[media:https://example.com/file.pdf]] doc caption",
            )
        self.assertEqual(rendered, "doc caption")
        self.assertEqual(len(client.messages), 1)
        self.assertEqual(client.messages[0][1], "doc caption")
        event_names = [call.args[0] for call in emit_mock.call_args_list]
        self.assertIn("bridge.outbound_delivery_failed", event_names)

    def test_send_executor_output_routes_photo_and_document(self):
        client = FakeTelegramClient()
        rendered_photo = bridge_handlers.send_executor_output(
            client=client,
            chat_id=1,
            message_id=9,
            output="[[media:https://example.com/pic.jpg]] photo caption",
        )
        rendered_doc = bridge_handlers.send_executor_output(
            client=client,
            chat_id=1,
            message_id=10,
            output="[[media:https://example.com/file.pdf]] doc caption",
        )
        self.assertEqual(rendered_photo, "photo caption")
        self.assertEqual(rendered_doc, "doc caption")
        self.assertEqual(len(client.photos), 1)
        self.assertEqual(len(client.documents), 1)
        self.assertEqual(client.chat_actions, [(1, "upload_photo"), (1, "upload_document")])

    def test_send_executor_output_preserves_message_thread_id_for_documents(self):
        client = mock.Mock()
        client.channel_name = "telegram"

        rendered = bridge_handlers.send_executor_output(
            client=client,
            chat_id=-1003706836145,
            message_id=1374,
            output="[[media:/tmp/feed.html]] feed",
            message_thread_id=511,
        )

        self.assertEqual(rendered, "feed")
        client.send_chat_action.assert_called_once_with(
            -1003706836145,
            action="upload_document",
            message_thread_id=511,
        )
        client.send_document.assert_called_once_with(
            chat_id=-1003706836145,
            document="/tmp/feed.html",
            caption="feed",
            reply_to_message_id=1374,
            message_thread_id=511,
        )
        client.send_message.assert_not_called()

    def test_transport_send_media_remote_uses_request_payload(self):
        config = make_config()
        client = bridge.TelegramClient(config)
        with mock.patch.object(client, "_request", return_value={"ok": True}) as request_mock:
            with mock.patch.object(client, "_request_multipart", return_value={"ok": True}) as multipart_mock:
                client.send_voice(
                    chat_id=1,
                    voice="https://example.com/note.ogg",
                    caption="c",
                    reply_to_message_id=12,
                )
        self.assertTrue(request_mock.called)
        self.assertFalse(multipart_mock.called)
        method_name, payload = request_mock.call_args.args
        self.assertEqual(method_name, "sendVoice")
        self.assertEqual(payload["voice"], "https://example.com/note.ogg")

    def test_transport_send_media_local_file_uses_multipart(self):
        config = make_config()
        client = bridge.TelegramClient(config)
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as handle:
            handle.write(b"test")
            voice_path = handle.name
        try:
            with mock.patch.object(client, "_request", return_value={"ok": True}) as request_mock:
                with mock.patch.object(
                    client,
                    "_request_multipart",
                    return_value={"ok": True},
                ) as multipart_mock:
                    client.send_voice(chat_id=1, voice=voice_path, caption="c", reply_to_message_id=2)
            self.assertFalse(request_mock.called)
            self.assertTrue(multipart_mock.called)
            kwargs = multipart_mock.call_args.kwargs
            self.assertEqual(kwargs["method"], "sendVoice")
            self.assertEqual(kwargs["file_field"], "voice")
        finally:
            Path(voice_path).unlink(missing_ok=True)

    def test_transport_retries_transient_http_error_then_succeeds(self):
        config = make_config()
        config.retry_sleep_seconds = 0.0
        setattr(config, "api_max_attempts", 3)
        client = bridge.TelegramClient(config)

        transient_body = json.dumps(
            {
                "ok": False,
                "error_code": 503,
                "description": "Service Unavailable",
            }
        ).encode("utf-8")

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return b'{"ok": true, "result": {"message_id": 1}}'

        transient_error = bridge_transport.HTTPError(
            url="https://api.telegram.org",
            code=503,
            msg="Service Unavailable",
            hdrs=None,
            fp=io.BytesIO(transient_body),
        )
        with mock.patch.object(bridge_transport, "urlopen", side_effect=[transient_error, Response()]) as mocked:
            client.send_message(chat_id=1, text="hello")

        self.assertEqual(mocked.call_count, 2)

    def test_transport_does_not_retry_non_transient_http_error(self):
        config = make_config()
        config.retry_sleep_seconds = 0.0
        setattr(config, "api_max_attempts", 3)
        client = bridge.TelegramClient(config)

        non_transient_body = json.dumps(
            {
                "ok": False,
                "error_code": 400,
                "description": "Bad Request",
            }
        ).encode("utf-8")
        non_transient_error = bridge_transport.HTTPError(
            url="https://api.telegram.org",
            code=400,
            msg="Bad Request",
            hdrs=None,
            fp=io.BytesIO(non_transient_body),
        )
        with mock.patch.object(bridge_transport, "urlopen", side_effect=[non_transient_error]) as mocked:
            with self.assertRaises(bridge_transport.TelegramApiError):
                client.send_message(chat_id=1, text="hello")

        self.assertEqual(mocked.call_count, 1)

    def test_transport_emits_retry_events_for_transient_error(self):
        config = make_config()
        config.retry_sleep_seconds = 0.0
        setattr(config, "api_max_attempts", 3)
        client = bridge.TelegramClient(config)

        transient_body = json.dumps(
            {
                "ok": False,
                "error_code": 503,
                "description": "Service Unavailable",
            }
        ).encode("utf-8")

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return b'{"ok": true, "result": {"message_id": 9}}'

        transient_error = bridge_transport.HTTPError(
            url="https://api.telegram.org",
            code=503,
            msg="Service Unavailable",
            hdrs=None,
            fp=io.BytesIO(transient_body),
        )
        with (
            mock.patch.object(bridge_transport, "urlopen", side_effect=[transient_error, Response()]),
            mock.patch.object(bridge_transport, "emit_event") as emit_mock,
        ):
            client.send_message(chat_id=1, text="hello")

        event_names = [call.args[0] for call in emit_mock.call_args_list]
        self.assertIn("bridge.telegram_api_retry_scheduled", event_names)
        self.assertIn("bridge.telegram_api_retry_succeeded", event_names)

    def test_transport_emits_failed_event_when_retry_exhausted(self):
        config = make_config()
        config.retry_sleep_seconds = 0.0
        setattr(config, "api_max_attempts", 2)
        client = bridge.TelegramClient(config)

        transient_body = json.dumps(
            {
                "ok": False,
                "error_code": 503,
                "description": "Service Unavailable",
            }
        ).encode("utf-8")
        transient_error = bridge_transport.HTTPError(
            url="https://api.telegram.org",
            code=503,
            msg="Service Unavailable",
            hdrs=None,
            fp=io.BytesIO(transient_body),
        )
        with (
            mock.patch.object(bridge_transport, "urlopen", side_effect=[transient_error, transient_error]),
            mock.patch.object(bridge_transport, "emit_event") as emit_mock,
        ):
            with self.assertRaises(bridge_transport.TelegramApiError):
                client.send_message(chat_id=1, text="hello")

        event_names = [call.args[0] for call in emit_mock.call_args_list]
        self.assertIn("bridge.telegram_api_retry_scheduled", event_names)
        self.assertIn("bridge.telegram_api_failed", event_names)

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

    def test_finalize_prompt_success_trims_plain_output(self):
        config = make_config(max_output_chars=20)
        config.empty_output_message = "(No output from Architect)"
        state_repo = mock.Mock()
        progress = mock.Mock()
        client = FakeTelegramClient()
        raw_output = "x" * 120
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
                message_id=19,
                result=result,
                progress=progress,
            )

        sent_output = send_mock.call_args.kwargs["output"]
        self.assertLessEqual(len(sent_output), config.max_output_chars)
        self.assertIn("[output truncated]", sent_output)

    def test_extract_ha_keyword_request_variants(self):
        self.assertEqual(bridge_handlers.extract_ha_keyword_request("HA open garage"), (True, "open garage"))
        self.assertEqual(
            bridge_handlers.extract_ha_keyword_request("Home Assistant: turn off light"),
            (True, "turn off light"),
        )
        self.assertEqual(bridge_handlers.extract_ha_keyword_request("ha"), (True, ""))
        self.assertEqual(bridge_handlers.extract_ha_keyword_request("happy path"), (False, ""))

    def test_extract_server3_keyword_request_variants(self):
        self.assertEqual(
            bridge_handlers.extract_server3_keyword_request("Server3 TV open Firefox"),
            (True, "open Firefox"),
        )
        self.assertEqual(
            bridge_handlers.extract_server3_keyword_request("server3 tv: play youtube top result"),
            (True, "play youtube top result"),
        )
        self.assertEqual(bridge_handlers.extract_server3_keyword_request("server3 tv"), (True, ""))
        self.assertEqual(bridge_handlers.extract_server3_keyword_request("server3 status"), (False, ""))

    def test_extract_nextcloud_keyword_request_variants(self):
        self.assertEqual(
            bridge_handlers.extract_nextcloud_keyword_request("Nextcloud list files"),
            (True, "list files"),
        )
        self.assertEqual(
            bridge_handlers.extract_nextcloud_keyword_request("nextcloud: create event tomorrow"),
            (True, "create event tomorrow"),
        )
        self.assertEqual(bridge_handlers.extract_nextcloud_keyword_request("nextcloud"), (True, ""))
        self.assertEqual(bridge_handlers.extract_nextcloud_keyword_request("nextcloudx"), (False, ""))

    def test_strip_required_prefix_variants(self):
        prefixes = ["@helper", "helper:"]
        self.assertEqual(
            bridge_handlers.strip_required_prefix("@helper summarize this", prefixes, True),
            (True, "summarize this"),
        )
        self.assertEqual(
            bridge_handlers.strip_required_prefix("HELPER: summarize this", prefixes, True),
            (True, "summarize this"),
        )
        self.assertEqual(
            bridge_handlers.strip_required_prefix("@helperbot should not match", prefixes, True),
            (False, "@helperbot should not match"),
        )
        self.assertEqual(
            bridge_handlers.strip_required_prefix("@helper\u00a0summarize this", prefixes, True),
            (True, "summarize this"),
        )
        self.assertEqual(
            bridge_handlers.strip_required_prefix("@helper\u00a0", prefixes, True),
            (True, ""),
        )
        self.assertEqual(
            bridge_handlers.strip_required_prefix("@helper, summarize this", prefixes, True),
            (True, "summarize this"),
        )
        self.assertEqual(
            bridge_handlers.strip_required_prefix("@helper. summarize this", prefixes, True),
            (True, "summarize this"),
        )

    def test_parse_voice_confidence(self):
        self.assertEqual(
            bridge_handlers.parse_voice_confidence("VOICE_CONFIDENCE=0.723\n"),
            0.723,
        )
        self.assertIsNone(bridge_handlers.parse_voice_confidence("no marker"))

    def test_progress_reporter_disables_whatsapp_edits_after_edit_failure(self):
        client = FakeProgressEditClient()
        reporter = bridge_handlers.ProgressReporter(
            client=client,
            chat_id=1,
            reply_to_message_id=5,
            message_thread_id=None,
            assistant_name="Architect",
            progress_label="Говорун размышляет",
        )
        reporter.progress_message_id = 101
        reporter.pending_update = True

        reporter._maybe_edit(force=True)

        self.assertIsNone(reporter.progress_message_id)

    def test_progress_reporter_skips_signal_edits_when_unsupported(self):
        client = FakeSignalProgressClient()
        reporter = bridge_handlers.ProgressReporter(
            client=client,
            chat_id=1,
            reply_to_message_id=5,
            message_thread_id=None,
            assistant_name="Oracle",
        )
        reporter.progress_message_id = 202
        reporter.pending_update = True

        reporter._maybe_edit(force=True)

        self.assertEqual(reporter.progress_message_id, 202)

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

    def test_extract_prompt_and_media_prefers_media_payload_for_photo_with_caption(self):
        prompt, photo_file_ids, voice_file_id, document = bridge_handlers.extract_prompt_and_media(
            {
                "text": "photo caption",
                "caption": "photo caption",
                "photo": [
                    {"file_id": "p-small", "file_size": 10},
                    {"file_id": "p-large", "file_size": 20},
                ],
            }
        )
        self.assertEqual(prompt, "photo caption")
        self.assertEqual(photo_file_ids, ["p-large"])
        self.assertIsNone(voice_file_id)
        self.assertIsNone(document)

    def test_extract_prompt_and_media_uses_text_fallback_for_document_without_caption(self):
        prompt, photo_file_ids, voice_file_id, document = bridge_handlers.extract_prompt_and_media(
            {
                "text": "summarize this",
                "document": {
                    "file_id": "doc-1",
                    "file_name": "notes.txt",
                    "mime_type": "text/plain",
                },
            }
        )
        self.assertEqual(prompt, "summarize this")
        self.assertEqual(photo_file_ids, [])
        self.assertIsNone(voice_file_id)
        self.assertIsNotNone(document)
        self.assertEqual(document.file_id, "doc-1")

    def test_extract_prompt_and_media_combines_caption_and_text_for_voice(self):
        prompt, photo_file_ids, voice_file_id, document = bridge_handlers.extract_prompt_and_media(
            {
                "text": "extra context",
                "caption": "@helper execute this",
                "voice": {"file_id": "voice-3"},
            }
        )
        self.assertEqual(prompt, "@helper execute this\n\nextra context")
        self.assertEqual(photo_file_ids, [])
        self.assertEqual(voice_file_id, "voice-3")
        self.assertIsNone(document)

    def test_extract_prompt_and_media_uses_replied_photo_when_current_message_has_no_media(self):
        prompt, photo_file_ids, voice_file_id, document = bridge_handlers.extract_prompt_and_media(
            {
                "text": "what about the window?",
                "reply_to_message": {
                    "photo": [
                        {"file_id": "p-small", "file_size": 10},
                        {"file_id": "p-large", "file_size": 20},
                    ],
                },
            }
        )
        self.assertEqual(prompt, "what about the window?")
        self.assertEqual(photo_file_ids, ["p-large"])
        self.assertIsNone(voice_file_id)
        self.assertIsNone(document)

    def test_extract_prompt_and_media_uses_replied_document_when_current_message_has_no_media(self):
        prompt, photo_file_ids, voice_file_id, document = bridge_handlers.extract_prompt_and_media(
            {
                "text": "summarize the quoted file",
                "reply_to_message": {
                    "document": {
                        "file_id": "doc-reply-1",
                        "file_name": "quoted.txt",
                        "mime_type": "text/plain",
                    }
                },
            }
        )
        self.assertEqual(prompt, "summarize the quoted file")
        self.assertEqual(photo_file_ids, [])
        self.assertIsNone(voice_file_id)
        self.assertIsNotNone(document)
        self.assertEqual(document.file_id, "doc-reply-1")

    def test_extract_prompt_and_media_collects_album_photo_ids(self):
        prompt, photo_file_ids, voice_file_id, document = bridge_handlers.extract_prompt_and_media(
            {
                "caption": "Nextcloud add these 3 pics to diary111.docx",
                "media_group_messages": [
                    {
                        "caption": "Nextcloud add these 3 pics to diary111.docx",
                        "photo": [
                            {"file_id": "p1-small", "file_size": 10},
                            {"file_id": "p1-large", "file_size": 20},
                        ],
                    },
                    {
                        "photo": [
                            {"file_id": "p2-small", "file_size": 11},
                            {"file_id": "p2-large", "file_size": 21},
                        ],
                    },
                    {
                        "photo": [
                            {"file_id": "p3-small", "file_size": 12},
                            {"file_id": "p3-large", "file_size": 22},
                        ],
                    },
                ],
            }
        )
        self.assertEqual(prompt, "Nextcloud add these 3 pics to diary111.docx")
        self.assertEqual(photo_file_ids, ["p1-large", "p2-large", "p3-large"])
        self.assertIsNone(voice_file_id)
        self.assertIsNone(document)

    def test_extract_prompt_and_media_collects_whatsapp_flat_photo_ids(self):
        prompt, photo_file_ids, voice_file_id, document = bridge_handlers.extract_prompt_and_media(
            {
                "caption": "Please analyze these images.",
                "photo": [
                    {"file_id": "wa-p1", "file_size": 100, "mime_type": "image/jpeg"},
                    {"file_id": "wa-p2", "file_size": 120, "mime_type": "image/jpeg"},
                    {"file_id": "wa-p3", "file_size": 140, "mime_type": "image/jpeg"},
                ],
            }
        )
        self.assertEqual(prompt, "Please analyze these images.")
        self.assertEqual(photo_file_ids, ["wa-p1", "wa-p2", "wa-p3"])
        self.assertIsNone(voice_file_id)
        self.assertIsNone(document)

    def test_collapse_media_group_updates_merges_album_messages(self):
        updates = [
            {
                "update_id": 101,
                "message": {
                    "message_id": 11,
                    "media_group_id": "album-1",
                    "caption": "album caption",
                    "chat": {"id": 1},
                    "photo": [{"file_id": "p1", "file_size": 10}],
                },
            },
            {
                "update_id": 102,
                "message": {
                    "message_id": 12,
                    "media_group_id": "album-1",
                    "chat": {"id": 1},
                    "photo": [{"file_id": "p2", "file_size": 11}],
                },
            },
            {
                "update_id": 103,
                "message": {
                    "message_id": 13,
                    "chat": {"id": 1},
                    "text": "plain",
                },
            },
        ]

        collapsed = bridge_handlers.collapse_media_group_updates(updates)

        self.assertEqual(len(collapsed), 2)
        album_message = collapsed[0]["message"]
        self.assertEqual(album_message["caption"], "album caption")
        self.assertEqual(len(album_message["media_group_messages"]), 2)
        self.assertEqual(collapsed[1]["message"]["text"], "plain")

    def test_buffer_pending_media_group_updates_flushes_split_album_across_polls(self):
        state = bridge.State()
        first_batch = [
            {
                "update_id": 101,
                "message": {
                    "message_id": 11,
                    "media_group_id": "album-1",
                    "caption": "album caption",
                    "chat": {"id": 1},
                    "photo": [{"file_id": "p1", "file_size": 10}],
                },
            },
            {
                "update_id": 102,
                "message": {
                    "message_id": 12,
                    "chat": {"id": 1},
                    "text": "plain",
                },
            },
        ]

        immediate_updates = bridge.buffer_pending_media_group_updates(
            state,
            first_batch,
            now=100.0,
        )
        self.assertEqual(len(immediate_updates), 1)
        self.assertEqual(immediate_updates[0]["message"]["text"], "plain")
        self.assertEqual(len(state.pending_media_groups), 1)
        self.assertEqual(bridge.flush_ready_media_group_updates(state, now=101.0), [])

        second_batch = [
            {
                "update_id": 103,
                "message": {
                    "message_id": 13,
                    "media_group_id": "album-1",
                    "chat": {"id": 1},
                    "photo": [{"file_id": "p2", "file_size": 11}],
                },
            }
        ]
        immediate_updates = bridge.buffer_pending_media_group_updates(
            state,
            second_batch,
            now=101.0,
        )
        self.assertEqual(immediate_updates, [])

        flushed_updates = bridge.flush_ready_media_group_updates(state, now=103.1)
        self.assertEqual(len(flushed_updates), 1)
        self.assertEqual(len(state.pending_media_groups), 0)
        album_message = flushed_updates[0]["message"]
        self.assertEqual(album_message["caption"], "album caption")
        self.assertEqual(len(album_message["media_group_messages"]), 2)

    def test_compute_poll_timeout_seconds_shortens_while_waiting_for_album_tail(self):
        state = bridge.State()
        state.pending_media_groups["1:album-1"] = bridge.PendingMediaGroup(
            chat_id=1,
            media_group_id="album-1",
            updates=[
                {
                    "update_id": 101,
                    "message": {
                        "message_id": 11,
                        "media_group_id": "album-1",
                        "chat": {"id": 1},
                    },
                }
            ],
            started_at=100.0,
            last_seen_at=100.0,
        )

        config = make_config(poll_timeout_seconds=30)
        self.assertEqual(bridge.compute_poll_timeout_seconds(state, config, now=100.1), 2)
        self.assertEqual(bridge.compute_poll_timeout_seconds(state, config, now=101.2), 1)

    def test_build_reply_context_prompt_from_reply_to_message_text(self):
        prompt = bridge_handlers.build_reply_context_prompt(
            {
                "text": "Это про что",
                "reply_to_message": {
                    "message_id": 77,
                    "text": "Доброе утро, Путиловы! ☀️\n\nДаю справку: ...",
                    "from": {"username": "Govorun TPG 2026"},
                },
            }
        )
        self.assertIn("Reply Context:", prompt)
        self.assertIn("Original Message Author: Govorun TPG 2026", prompt)
        self.assertIn("Original Telegram Message ID: 77", prompt)
        self.assertIn("Message User Replied To:", prompt)
        self.assertIn("Доброе утро, Путиловы!", prompt)

    def test_build_reply_context_prompt_mentions_reply_media_without_text(self):
        prompt = bridge_handlers.build_reply_context_prompt(
            {
                "text": "А это что?",
                "reply_to_message": {
                    "message_id": 91,
                    "photo": [{"file_id": "photo-1", "file_size": 100}],
                    "from": {"username": "Telegram User"},
                },
            }
        )
        self.assertIn("Reply Context:", prompt)
        self.assertIn("Original Telegram Message ID: 91", prompt)
        self.assertIn("В исходном сообщении было изображение.", prompt)

    def test_build_telegram_context_prompt_includes_current_message_id(self):
        prompt = bridge_handlers.build_telegram_context_prompt(
            chat_id=-1003706836145,
            message_thread_id=498,
            scope_key="tg:-1003706836145:topic:498",
            message_id=570,
            message={},
        )

        self.assertIn("Current Telegram Context:", prompt)
        self.assertIn("- Chat ID: -1003706836145", prompt)
        self.assertIn("- Topic ID: 498", prompt)
        self.assertIn("- Current Message ID: 570", prompt)
        self.assertIn("- Scope Key: tg:-1003706836145:topic:498", prompt)
        self.assertIn("treat this current chat/topic as authoritative", prompt)
        self.assertIn("Never fall back to a different chat ID", prompt)

    def test_telegram_text_prompt_includes_delivery_target_guardrail(self):
        self.assertTrue(
            bridge_handlers.should_include_telegram_context_prompt(
                "2",
                "",
                "telegram",
            )
        )
        self.assertFalse(
            bridge_handlers.should_include_telegram_context_prompt(
                "2",
                "",
                "whatsapp",
            )
        )

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

    def test_build_low_confidence_voice_message_uses_configured_text(self):
        config = make_config(voice_low_confidence_message="Voice transcript confidence is low, resend")
        message = bridge_handlers.build_low_confidence_voice_message(
            config,
            transcript="govorun test",
            confidence=0.2,
        )
        self.assertEqual(message, "Voice transcript confidence is low, resend")

    @mock.patch.object(bridge_handlers, "transcribe_voice")
    @mock.patch.object(bridge_handlers, "download_voice_to_temp")
    def test_transcribe_voice_for_chat_blocks_low_confidence(self, download_voice_to_temp, transcribe_voice):
        with tempfile.NamedTemporaryFile(suffix=".oga", delete=False) as handle:
            voice_path = handle.name
        download_voice_to_temp.return_value = voice_path
        transcribe_voice.return_value = ("turn off master broom air con", 0.20)

        client = FakeTelegramClient()
        config = make_config(
            voice_transcribe_cmd=["/bin/echo"],
            voice_alias_replacements=[("master broom", "master bedroom"), ("air con", "aircon")],
            voice_low_confidence_confirmation_enabled=True,
            voice_low_confidence_threshold=0.45,
        )
        try:
            transcript = bridge_handlers.transcribe_voice_for_chat(
                state=bridge.State(),
                config=config,
                client=client,
                chat_id=1,
                message_id=99,
                voice_file_id="voice-1",
                echo_transcript=True,
            )
        finally:
            Path(voice_path).unlink(missing_ok=True)

        self.assertIsNone(transcript)
        self.assertEqual(len(client.messages), 1)
        self.assertEqual(client.messages[0][1], "Voice transcript confidence is low, resend")

    @mock.patch.object(bridge_handlers, "transcribe_voice")
    @mock.patch.object(bridge_handlers, "download_voice_to_temp")
    def test_transcribe_voice_for_chat_applies_aliases_on_success(self, download_voice_to_temp, transcribe_voice):
        with tempfile.NamedTemporaryFile(suffix=".oga", delete=False) as handle:
            voice_path = handle.name
        download_voice_to_temp.return_value = voice_path
        transcribe_voice.return_value = ("turn on master broom air con", 0.91)

        client = FakeTelegramClient()
        config = make_config(
            voice_transcribe_cmd=["/bin/echo"],
            voice_alias_replacements=[("master broom", "master bedroom"), ("air con", "aircon")],
            voice_low_confidence_confirmation_enabled=True,
            voice_low_confidence_threshold=0.45,
        )
        try:
            transcript = bridge_handlers.transcribe_voice_for_chat(
                state=bridge.State(),
                config=config,
                client=client,
                chat_id=1,
                message_id=100,
                voice_file_id="voice-2",
                echo_transcript=True,
            )
        finally:
            Path(voice_path).unlink(missing_ok=True)

        self.assertEqual(transcript, "turn on master bedroom aircon")
        self.assertEqual(len(client.messages), 1)
        self.assertIn("confidence 0.91", client.messages[0][1])
        self.assertIn("master bedroom aircon", client.messages[0][1])

    @mock.patch.object(bridge_handlers, "transcribe_voice_for_chat", return_value="turn on the light")
    def test_prepare_prompt_input_rejects_voice_transcript_without_required_prefix(
        self, transcribe_voice_for_chat
    ):
        client = FakeTelegramClient()
        config = make_config(required_prefixes=["@helper"])
        progress = mock.Mock()

        prepared = bridge_handlers.prepare_prompt_input(
            state=bridge.State(),
            config=config,
            client=client,
            chat_id=1,
            message_id=11,
            prompt="",
            photo_file_id=None,
            voice_file_id="voice-1",
            document=None,
            progress=progress,
            enforce_voice_prefix_from_transcript=True,
        )

        self.assertIsNone(prepared)
        self.assertEqual(len(client.messages), 1)
        self.assertIn("Helper mode needs a prefixed prompt.", client.messages[0][1])
        transcribe_voice_for_chat.assert_called_once()

    @mock.patch.object(bridge_handlers, "transcribe_voice_for_chat", return_value="turn on the light")
    def test_prepare_prompt_input_ignores_whatsapp_voice_transcript_without_prefix(
        self, transcribe_voice_for_chat
    ):
        client = FakeTelegramClient(channel_name="whatsapp")
        config = make_config(required_prefixes=["@helper"])
        progress = mock.Mock()

        prepared = bridge_handlers.prepare_prompt_input(
            state=bridge.State(),
            config=config,
            client=client,
            chat_id=1,
            message_id=110,
            prompt="",
            photo_file_id=None,
            voice_file_id="voice-wa-1",
            document=None,
            progress=progress,
            enforce_voice_prefix_from_transcript=True,
        )

        self.assertIsNone(prepared)
        self.assertEqual(client.messages, [])
        transcribe_voice_for_chat.assert_called_once()

    @mock.patch.object(bridge_handlers, "transcribe_voice_for_chat", return_value="@helper")
    def test_prepare_prompt_input_ignores_whatsapp_voice_prefix_without_action(
        self, transcribe_voice_for_chat
    ):
        client = FakeTelegramClient(channel_name="whatsapp")
        config = make_config(required_prefixes=["@helper"])
        progress = mock.Mock()

        prepared = bridge_handlers.prepare_prompt_input(
            state=bridge.State(),
            config=config,
            client=client,
            chat_id=1,
            message_id=111,
            prompt="",
            photo_file_id=None,
            voice_file_id="voice-wa-2",
            document=None,
            progress=progress,
            enforce_voice_prefix_from_transcript=True,
        )

        self.assertIsNone(prepared)
        self.assertEqual(client.messages, [])
        transcribe_voice_for_chat.assert_called_once()

    @mock.patch.object(bridge_handlers, "transcribe_voice_for_chat", return_value="govoron you ok")
    def test_prepare_prompt_input_whatsapp_voice_prefix_miss_creates_alias_suggestion(
        self, transcribe_voice_for_chat
    ):
        client = FakeTelegramClient(channel_name="whatsapp")
        config = make_config(required_prefixes=["govorun"])
        progress = mock.Mock()
        state = bridge.State()
        state.voice_alias_learning_store = mock.Mock()
        state.voice_alias_learning_store.get_approved_replacements.return_value = []
        state.voice_alias_learning_store.observe_pair.return_value = [
            SimpleNamespace(
                suggestion_id=7,
                source="govoron",
                target="govorun",
                count=2,
            )
        ]

        prepared = bridge_handlers.prepare_prompt_input(
            state=state,
            config=config,
            client=client,
            chat_id=1,
            message_id=113,
            prompt="",
            photo_file_id=None,
            voice_file_id="voice-wa-3",
            document=None,
            progress=progress,
            enforce_voice_prefix_from_transcript=True,
        )

        self.assertIsNone(prepared)
        state.voice_alias_learning_store.observe_pair.assert_called_once_with(
            source="govoron",
            target="govorun",
        )
        self.assertEqual(len(client.messages), 1)
        self.assertIn("Voice correction learning suggestion(s):", client.messages[0][1])
        self.assertIn("Approve with: `/voice-alias approve <id>`", client.messages[0][1])
        transcribe_voice_for_chat.assert_called_once()

    @mock.patch.object(bridge_handlers, "transcribe_voice_for_chat", return_value="@helper turn on the light")
    def test_prepare_prompt_input_accepts_voice_transcript_with_required_prefix(
        self, transcribe_voice_for_chat
    ):
        client = FakeTelegramClient()
        config = make_config(required_prefixes=["@helper"])
        progress = mock.Mock()

        prepared = bridge_handlers.prepare_prompt_input(
            state=bridge.State(),
            config=config,
            client=client,
            chat_id=1,
            message_id=12,
            prompt="",
            photo_file_id=None,
            voice_file_id="voice-2",
            document=None,
            progress=progress,
            enforce_voice_prefix_from_transcript=True,
        )

        self.assertIsNotNone(prepared)
        self.assertEqual(prepared.prompt_text, "turn on the light")
        self.assertEqual(client.messages, [])
        transcribe_voice_for_chat.assert_called_once()

    def test_json_log_formatter_includes_event_and_fields(self):
        record = logging.LogRecord(
            "telegram_bridge",
            logging.INFO,
            __file__,
            1,
            "bridge.request_succeeded",
            args=(),
            exc_info=None,
        )
        record.event = "bridge.request_succeeded"
        record.fields = {"chat_id": 1, "message_id": 2}
        payload = json.loads(bridge_structured_logging.JsonLogFormatter().format(record))
        self.assertEqual(payload["event"], "bridge.request_succeeded")
        self.assertEqual(payload["chat_id"], 1)
        self.assertEqual(payload["message_id"], 2)

    def test_download_helper_rejects_oversize(self):
        client = FakeDownloadClient({"file_path": "files/example.jpg", "file_size": 9999})
        spec = bridge.TelegramFileDownloadSpec(
            file_id="abc",
            max_bytes=1024,
            size_label="Image",
            temp_prefix="telegram-bridge-photo-",
            default_suffix=".jpg",
            too_large_label="Image",
        )
        with self.assertRaises(ValueError):
            bridge.download_telegram_file_to_temp(client, spec)
        self.assertEqual(client.download_calls, 0)

    def test_state_repository_persists_thread_and_inflight_state(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state = bridge.State(
                chat_thread_path=str(Path(tmpdir) / "chat_threads.json"),
                worker_sessions_path=str(Path(tmpdir) / "worker_sessions.json"),
                in_flight_path=str(Path(tmpdir) / "in_flight_requests.json"),
                worker_sessions={
                    "tg:1": bridge.WorkerSession(
                        created_at=1.0,
                        last_used_at=1.0,
                        thread_id="",
                        policy_fingerprint="",
                    )
                },
            )
            repo = bridge.StateRepository(state)

            repo.set_thread_id(1, "thread-xyz")
            threads = json.loads(Path(state.chat_thread_path).read_text(encoding="utf-8"))
            sessions = json.loads(Path(state.worker_sessions_path).read_text(encoding="utf-8"))
            self.assertEqual(threads, {"tg:1": "thread-xyz"})
            self.assertEqual(sessions["tg:1"]["thread_id"], "thread-xyz")

            repo.mark_in_flight_request(1, 55)
            in_flight = json.loads(Path(state.in_flight_path).read_text(encoding="utf-8"))
            self.assertEqual(in_flight["tg:1"]["message_id"], 55)

            repo.clear_in_flight_request(1)
            cleared = json.loads(Path(state.in_flight_path).read_text(encoding="utf-8"))
            self.assertEqual(cleared, {})

            repo.clear_thread_id(1)
            threads_after = json.loads(Path(state.chat_thread_path).read_text(encoding="utf-8"))
            self.assertEqual(threads_after, {})

    def test_ensure_chat_worker_session_rejects_when_all_workers_busy(self):
        state = bridge.State(
            chat_threads={2: "thread-busy"},
            worker_sessions={
                2: bridge.WorkerSession(
                    created_at=1.0,
                    last_used_at=10.0,
                    thread_id="thread-busy",
                    policy_fingerprint="fp",
                )
            },
        )
        state.busy_chats.add(2)
        client = FakeTelegramClient()
        config = make_config(
            persistent_workers_enabled=True,
            persistent_workers_max=1,
            persistent_workers_idle_timeout_seconds=3600,
        )

        allowed = bridge.ensure_chat_worker_session(state, config, client, chat_id=1, message_id=99)
        self.assertFalse(allowed)
        self.assertTrue(client.messages)
        self.assertIn("workers are currently in use", client.messages[-1][1])

    def test_expire_idle_worker_sessions_leaves_live_shared_memory_intact(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            memory_engine = bridge.MemoryEngine(str(Path(tmpdir) / "memory.sqlite3"))
            live_key = "shared:architect:main:session:tg:1"
            archive_key = "shared:architect:main"

            turn = memory_engine.begin_turn(
                conversation_key=live_key,
                channel="telegram",
                sender_name="User",
                user_input="remember this topic",
            )
            memory_engine.finish_turn(
                turn,
                channel="telegram",
                assistant_text="stored",
                new_thread_id="thread-live",
            )
            memory_engine.remember_explicit(live_key, "topic: separate")

            state = bridge.State(
                chat_threads={"tg:1": "thread-live"},
                worker_sessions={
                    "tg:1": bridge.WorkerSession(
                        created_at=1.0,
                        last_used_at=1.0,
                        thread_id="thread-live",
                        policy_fingerprint="fp",
                    )
                },
                memory_engine=memory_engine,
            )
            client = FakeTelegramClient(channel_name="telegram")
            config = make_config(
                allowed_chat_ids={1},
                persistent_workers_enabled=True,
                persistent_workers_idle_timeout_seconds=1,
                shared_memory_key=archive_key,
            )

            with mock.patch.object(bridge_session_manager.time, "time", return_value=100.0):
                bridge.expire_idle_worker_sessions(state, config, client)

            self.assertEqual(memory_engine.get_status(live_key).message_count, 2)
            archive_status = memory_engine.get_status(archive_key)
            self.assertEqual(archive_status.message_count, 0)
            self.assertEqual(archive_status.summary_count, 0)
            self.assertIn("tg:1", state.worker_sessions)
            self.assertFalse(client.messages)

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

    def test_apply_auth_change_thread_reset_clears_stale_threads_and_memory_sessions(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state_dir = Path(tmpdir)
            fingerprint_path = Path(bridge.build_auth_fingerprint_state_path(str(state_dir)))
            fingerprint_path.write_text("old-auth\n", encoding="utf-8")
            memory_engine = bridge.MemoryEngine(str(state_dir / "memory.sqlite3"))
            memory_engine.set_session_thread_id("tg:1", "thread-memory")
            loaded_threads = {1: "thread-1", 2: "thread-2"}
            loaded_worker_sessions = {
                2: bridge.WorkerSession(
                    created_at=1.0,
                    last_used_at=2.0,
                    thread_id="thread-2",
                    policy_fingerprint="old-policy",
                )
            }
            loaded_canonical_sessions = {
                1: bridge.CanonicalSession(thread_id="thread-1"),
                2: bridge.CanonicalSession(
                    thread_id="thread-2",
                    worker_created_at=10.0,
                    worker_last_used_at=20.0,
                    worker_policy_fingerprint="old-policy",
                ),
                3: bridge.CanonicalSession(in_flight_started_at=30.0, in_flight_message_id=300),
            }

            result = bridge.apply_auth_change_thread_reset(
                state_dir=str(state_dir),
                current_auth_fingerprint="new-auth",
                loaded_threads=loaded_threads,
                loaded_worker_sessions=loaded_worker_sessions,
                loaded_canonical_sessions=loaded_canonical_sessions,
                memory_engine=memory_engine,
            )

            self.assertTrue(result["applied"])
            self.assertEqual(result["counts"]["threads"], 2)
            self.assertEqual(result["counts"]["worker_sessions"], 1)
            self.assertEqual(result["counts"]["canonical_sessions"], 2)
            self.assertEqual(result["counts"]["memory_sessions"], 1)
            self.assertEqual(loaded_threads, {})
            self.assertEqual(loaded_worker_sessions, {})
            self.assertNotIn(1, loaded_canonical_sessions)
            self.assertNotIn(2, loaded_canonical_sessions)
            self.assertIn(3, loaded_canonical_sessions)
            self.assertIsNone(memory_engine.get_session_thread_id("tg:1"))
            self.assertEqual(fingerprint_path.read_text(encoding="utf-8").strip(), "new-auth")

    def test_apply_auth_change_thread_reset_bootstrap_clears_legacy_threads_without_prior_fingerprint(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state_dir = Path(tmpdir)
            memory_engine = bridge.MemoryEngine(str(state_dir / "memory.sqlite3"))
            memory_engine.set_session_thread_id("tg:1", "thread-memory")
            loaded_threads = {1: "thread-1"}
            loaded_worker_sessions = {}
            loaded_canonical_sessions = {}

            result = bridge.apply_auth_change_thread_reset(
                state_dir=str(state_dir),
                current_auth_fingerprint="bootstrap-auth",
                loaded_threads=loaded_threads,
                loaded_worker_sessions=loaded_worker_sessions,
                loaded_canonical_sessions=loaded_canonical_sessions,
                memory_engine=memory_engine,
            )

            self.assertTrue(result["applied"])
            self.assertEqual(result["counts"]["threads"], 1)
            self.assertEqual(result["counts"]["memory_sessions"], 1)
            self.assertEqual(loaded_threads, {})
            self.assertIsNone(memory_engine.get_session_thread_id("tg:1"))
            self.assertEqual(
                (state_dir / "auth_fingerprint.txt").read_text(encoding="utf-8").strip(),
                "bootstrap-auth",
            )

    def test_begin_memory_turn_clears_stale_memory_thread_when_bridge_state_is_empty(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state_dir = Path(tmpdir)
            conversation_key = "tg:-1003706836145:topic:2504"
            memory_engine = bridge.MemoryEngine(str(state_dir / "memory.sqlite3"))
            memory_engine.set_session_thread_id(conversation_key, "stale-thread")
            state = bridge.State(
                canonical_sessions_enabled=True,
                memory_engine=memory_engine,
            )
            repo = bridge.StateRepository(state)
            config = make_config(shared_memory_key="")

            prompt_text, previous_thread_id, turn_context = bridge_handlers.begin_memory_turn(
                memory_engine=memory_engine,
                state_repo=repo,
                config=config,
                channel_name="telegram",
                scope_key=conversation_key,
                prompt_text="Solve the problem to get access",
                sender_name="anunakii",
                stateless=False,
                chat_id=-1003706836145,
            )

            self.assertEqual(prompt_text, turn_context.prompt_text)
            self.assertIsNone(previous_thread_id)
            self.assertIsNone(turn_context.thread_id)
            self.assertIsNone(memory_engine.get_session_thread_id(conversation_key))

    def test_begin_memory_turn_syncs_memory_thread_from_bridge_state(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state_dir = Path(tmpdir)
            conversation_key = "tg:-1003706836145:topic:2504"
            memory_engine = bridge.MemoryEngine(str(state_dir / "memory.sqlite3"))
            memory_engine.set_session_thread_id(conversation_key, "stale-thread")
            state = bridge.State(
                canonical_sessions_enabled=True,
                chat_sessions={
                    conversation_key: bridge.CanonicalSession(thread_id="bridge-thread"),
                },
                memory_engine=memory_engine,
            )
            repo = bridge.StateRepository(state)
            config = make_config(shared_memory_key="")

            _, previous_thread_id, turn_context = bridge_handlers.begin_memory_turn(
                memory_engine=memory_engine,
                state_repo=repo,
                config=config,
                channel_name="telegram",
                scope_key=conversation_key,
                prompt_text="Solve the problem to get access",
                sender_name="anunakii",
                stateless=False,
                chat_id=-1003706836145,
            )

            self.assertEqual(previous_thread_id, "bridge-thread")
            self.assertEqual(turn_context.thread_id, "bridge-thread")
            self.assertEqual(memory_engine.get_session_thread_id(conversation_key), "bridge-thread")

    def test_handle_update_routes_status_command(self):
        state = bridge.State()
        client = FakeTelegramClient()
        config = make_config()
        update = {
            "update_id": 1,
            "message": {
                "message_id": 10,
                "chat": {"id": 1},
                "text": "/status",
            },
        }

        bridge.handle_update(state, config, client, update)
        self.assertTrue(client.messages)
        self.assertIn("Bridge status: online", client.messages[-1][1])

    def test_handle_update_routes_help_alias_with_bot_suffix(self):
        state = bridge.State()
        client = FakeTelegramClient()
        config = make_config()
        update = {
            "update_id": 1,
            "message": {
                "message_id": 20,
                "chat": {"id": 1},
                "text": "/h@architect_bot",
            },
        }

        bridge.handle_update(state, config, client, update)
        self.assertTrue(client.messages)
        self.assertIn("Available commands:", client.messages[-1][1])
        self.assertIn("server3-tv-start", client.messages[-1][1])
        self.assertIn("server3-tv-stop", client.messages[-1][1])
        self.assertIn("Use `Server3 TV ...`", client.messages[-1][1])
        self.assertIn("Mention `server2` or `staker2`", client.messages[-1][1])
        self.assertIn("Use `Nextcloud ...`", client.messages[-1][1])
        self.assertIn("Use `SRO ...`", client.messages[-1][1])
        self.assertIn("/cancel", client.messages[-1][1])
        self.assertIn("/voice-alias add <source> => <target>", client.messages[-1][1])
        self.assertIn("/memory mode", client.messages[-1][1])
        self.assertNotIn("/memory mode full - legacy alias for all_context", client.messages[-1][1])
        self.assertIn("/ask <prompt>", client.messages[-1][1])

    def test_handle_update_routes_cancel_when_no_active_request(self):
        state = bridge.State()
        client = FakeTelegramClient()
        config = make_config()
        update = {
            "update_id": 2,
            "message": {
                "message_id": 21,
                "chat": {"id": 1},
                "text": "/cancel",
            },
        }

        bridge.handle_update(state, config, client, update)
        self.assertTrue(client.messages)
        self.assertEqual(client.messages[-1][1], "No active request to cancel.")

    def test_handle_update_routes_cancel_when_request_active(self):
        state = bridge.State()
        with state.lock:
            state.busy_chats.add(1)
            state.cancel_events[1] = threading.Event()
        client = FakeTelegramClient()
        config = make_config()
        update = {
            "update_id": 3,
            "message": {
                "message_id": 22,
                "chat": {"id": 1},
                "text": "/cancel",
            },
        }

        bridge.handle_update(state, config, client, update)
        self.assertTrue(client.messages)
        self.assertEqual(client.messages[-1][1], "Cancel requested. Stopping current request.")
        with state.lock:
            self.assertTrue(state.cancel_events["tg:1"].is_set())

    @mock.patch.object(bridge_handlers, "start_message_worker")
    def test_handle_update_ignores_non_prefixed_when_required(self, start_message_worker):
        state = bridge.State()
        client = FakeTelegramClient()
        config = make_config(required_prefixes=["@helper"])
        update = {
            "update_id": 100,
            "message": {
                "message_id": 200,
                "chat": {"id": 1},
                "text": "hello there",
            },
        }

        bridge.handle_update(state, config, client, update)

        self.assertFalse(start_message_worker.called)
        self.assertEqual(client.messages, [])

    def test_handle_update_accepts_prefixed_status_command_when_required(self):
        state = bridge.State()
        client = FakeTelegramClient()
        config = make_config(required_prefixes=["@helper"])
        update = {
            "update_id": 101,
            "message": {
                "message_id": 201,
                "chat": {"id": 1},
                "text": "@helper /status",
            },
        }

        bridge.handle_update(state, config, client, update)

        self.assertTrue(client.messages)
        self.assertIn("Bridge status: online", client.messages[-1][1])

    @mock.patch.object(bridge_handlers, "start_message_worker")
    def test_handle_update_whatsapp_voice_alias_command_bypasses_prefix_requirement(
        self, start_message_worker
    ):
        state = bridge.State()
        state.voice_alias_learning_store = mock.Mock()
        state.voice_alias_learning_store.list_pending.return_value = []
        client = FakeTelegramClient(channel_name="whatsapp")
        config = make_config(required_prefixes=["govorun"], channel_plugin="whatsapp")
        update = {
            "update_id": 1011,
            "message": {
                "message_id": 2011,
                "chat": {"id": 1, "type": "group"},
                "text": "/voice-alias list",
            },
        }

        bridge.handle_update(state, config, client, update)

        self.assertFalse(start_message_worker.called)
        self.assertEqual(len(client.messages), 1)
        self.assertIn("No pending learned voice alias suggestions.", client.messages[0][1])

    def test_handle_update_rejects_prefix_without_action(self):
        state = bridge.State()
        client = FakeTelegramClient()
        config = make_config(required_prefixes=["@helper"])
        update = {
            "update_id": 102,
            "message": {
                "message_id": 202,
                "chat": {"id": 1},
                "text": "@helper",
            },
        }

        bridge.handle_update(state, config, client, update)

        self.assertEqual(len(client.messages), 1)
        self.assertIn("Helper mode needs a prefixed prompt.", client.messages[0][1])

    @mock.patch.object(bridge_handlers, "start_message_worker")
    def test_handle_update_allows_prefix_only_reply_to_use_reply_context(self, start_message_worker):
        state = bridge.State()
        client = FakeTelegramClient(channel_name="whatsapp")
        config = make_config(required_prefixes=["говорун"], channel_plugin="whatsapp")
        update = {
            "update_id": 1024,
            "message": {
                "message_id": 2024,
                "chat": {"id": 1, "type": "group"},
                "text": "говорун",
                "reply_to_message": {
                    "text": "Посмотри на это и ответь по сути.",
                    "from": {"username": "Vlad"},
                },
            },
        }

        bridge.handle_update(state, config, client, update)

        self.assertTrue(start_message_worker.called)
        kwargs = start_message_worker.call_args.kwargs
        self.assertIn("Reply Context:", kwargs["prompt"])
        self.assertIn("Original Message Author: Vlad", kwargs["prompt"])
        self.assertIn("Посмотри на это и ответь по сути.", kwargs["prompt"])
        self.assertEqual(client.messages, [])

    @mock.patch.object(bridge_handlers, "start_message_worker")
    @mock.patch.object(bridge_handlers, "archive_media_path", return_value="/tmp/archive.jpg")
    @mock.patch.object(bridge_handlers, "download_photo_to_temp", return_value="/tmp/incoming.jpg")
    @mock.patch("handlers.os.remove")
    def test_handle_update_prewarms_attachment_archive_for_unprefixed_photo(
        self,
        remove_mock,
        download_photo_to_temp,
        archive_media_path,
        start_message_worker,
    ):
        attachment_store = mock.Mock()
        attachment_store.get_record.return_value = None
        attachment_store.get_summary.return_value = ""
        state = bridge.State(attachment_store=attachment_store)
        client = FakeTelegramClient(channel_name="whatsapp")
        config = make_config(required_prefixes=["govorun"], channel_plugin="whatsapp")
        update = {
            "update_id": 1025,
            "message": {
                "message_id": 2025,
                "chat": {"id": 1, "type": "group"},
                "photo": [{"file_id": "photo-archive-1", "file_size": 100}],
            },
        }

        bridge.handle_update(state, config, client, update)

        self.assertFalse(start_message_worker.called)
        download_photo_to_temp.assert_called_once()
        archive_media_path.assert_called_once()
        remove_mock.assert_called_once_with("/tmp/incoming.jpg")

    @mock.patch.object(bridge_handlers, "start_message_worker")
    def test_handle_update_defers_voice_prefix_check_to_transcript_when_required(
        self, start_message_worker
    ):
        state = bridge.State()
        client = FakeTelegramClient()
        config = make_config(required_prefixes=["@helper"])
        update = {
            "update_id": 103,
            "message": {
                "message_id": 203,
                "chat": {"id": 1},
                "voice": {"file_id": "voice-1"},
            },
        }

        bridge.handle_update(state, config, client, update)

        self.assertTrue(start_message_worker.called)
        kwargs = start_message_worker.call_args.kwargs
        self.assertEqual(kwargs["prompt"], "")
        self.assertEqual(kwargs["voice_file_id"], "voice-1")
        self.assertTrue(kwargs["enforce_voice_prefix_from_transcript"])
        self.assertEqual(client.messages, [])

    @mock.patch.object(bridge_handlers, "start_message_worker")
    def test_handle_update_mixed_whatsapp_photo_payload_keeps_photo(self, start_message_worker):
        state = bridge.State()
        client = FakeTelegramClient()
        config = make_config()
        update = {
            "update_id": 150,
            "message": {
                "message_id": 250,
                "chat": {"id": 1},
                "text": "photo caption",
                "caption": "photo caption",
                "photo": [{"file_id": "photo-1", "file_size": 100}],
            },
        }

        bridge.handle_update(state, config, client, update)

        self.assertTrue(start_message_worker.called)
        kwargs = start_message_worker.call_args.kwargs
        self.assertIn("Current Telegram Context:", kwargs["prompt"])
        self.assertIn("Current User Message:\nphoto caption", kwargs["prompt"])
        self.assertEqual(kwargs["photo_file_id"], "photo-1")
        self.assertIsNone(kwargs["voice_file_id"])

    @mock.patch.object(bridge_handlers, "start_message_worker")
    def test_handle_update_whatsapp_multi_photo_payload_keeps_all_photos(self, start_message_worker):
        state = bridge.State()
        client = FakeTelegramClient(channel_name="whatsapp")
        config = make_config(channel_plugin="whatsapp")
        update = {
            "update_id": 152,
            "message": {
                "message_id": 252,
                "chat": {"id": 1},
                "caption": "Please analyze these images.",
                "photo": [
                    {"file_id": "wa-photo-1", "file_size": 101, "mime_type": "image/jpeg"},
                    {"file_id": "wa-photo-2", "file_size": 102, "mime_type": "image/jpeg"},
                    {"file_id": "wa-photo-3", "file_size": 103, "mime_type": "image/jpeg"},
                ],
            },
        }

        bridge.handle_update(state, config, client, update)

        self.assertTrue(start_message_worker.called)
        kwargs = start_message_worker.call_args.kwargs
        self.assertEqual(kwargs["prompt"], "Please analyze these images.")
        self.assertEqual(kwargs["photo_file_id"], "wa-photo-1")
        self.assertEqual(kwargs["photo_file_ids"], ["wa-photo-1", "wa-photo-2", "wa-photo-3"])
        self.assertIsNone(kwargs["voice_file_id"])

    @mock.patch.object(bridge_handlers, "start_message_worker")
    def test_handle_update_text_message_never_routes_to_voice_transcribe_path(self, start_message_worker):
        state = bridge.State()
        client = FakeTelegramClient()
        config = make_config()
        update = {
            "update_id": 151,
            "message": {
                "message_id": 251,
                "chat": {"id": 1},
                "text": "@helper status",
            },
        }

        bridge.handle_update(state, config, client, update)

        self.assertTrue(start_message_worker.called)
        kwargs = start_message_worker.call_args.kwargs
        self.assertEqual(kwargs["voice_file_id"], None)
        self.assertFalse(kwargs["enforce_voice_prefix_from_transcript"])

    @mock.patch.object(bridge_handlers, "start_message_worker")
    def test_handle_update_accepts_prefixed_voice_caption_when_required(self, start_message_worker):
        state = bridge.State()
        client = FakeTelegramClient()
        config = make_config(required_prefixes=["@helper"])
        update = {
            "update_id": 104,
            "message": {
                "message_id": 204,
                "chat": {"id": 1},
                "voice": {"file_id": "voice-2"},
                "caption": "@helper transcribe this",
            },
        }

        bridge.handle_update(state, config, client, update)

        self.assertTrue(start_message_worker.called)
        kwargs = start_message_worker.call_args.kwargs
        self.assertIn("Current Telegram Context:", kwargs["prompt"])
        self.assertIn("Current User Message:\ntranscribe this", kwargs["prompt"])
        self.assertEqual(kwargs["voice_file_id"], "voice-2")
        self.assertFalse(kwargs["enforce_voice_prefix_from_transcript"])

    @mock.patch.object(bridge_handlers, "start_message_worker")
    def test_handle_update_allows_unprefixed_private_message_when_configured(
        self, start_message_worker
    ):
        state = bridge.State()
        client = FakeTelegramClient()
        config = make_config(
            required_prefixes=["@helper"],
            require_prefix_in_private=False,
        )
        update = {
            "update_id": 105,
            "message": {
                "message_id": 205,
                "chat": {"id": 1, "type": "private"},
                "text": "hello there",
            },
        }

        bridge.handle_update(state, config, client, update)

        self.assertTrue(start_message_worker.called)
        kwargs = start_message_worker.call_args.kwargs
        self.assertIn("Current Telegram Context:", kwargs["prompt"])
        self.assertIn("Current User Message:\nhello there", kwargs["prompt"])
        self.assertFalse(kwargs["enforce_voice_prefix_from_transcript"])

    @mock.patch.object(bridge_handlers, "start_message_worker")
    def test_handle_update_includes_reply_context_in_prompt(self, start_message_worker):
        state = bridge.State()
        client = FakeTelegramClient(channel_name="whatsapp")
        config = make_config(channel_plugin="whatsapp")
        update = {
            "update_id": 1051,
            "message": {
                "message_id": 2051,
                "chat": {"id": 1, "type": "private"},
                "text": "Это про что",
                "reply_to_message": {
                    "message_id": 99,
                    "text": "Доброе утро, Путиловы! ☀️\n\nДаю справку: В Эрмитаже живут коты.",
                    "from": {"username": "Govorun TPG 2026"},
                },
            },
        }

        bridge.handle_update(state, config, client, update)

        self.assertTrue(start_message_worker.called)
        kwargs = start_message_worker.call_args.kwargs
        self.assertIn("Current Telegram Context:", kwargs["prompt"])
        self.assertIn("- Current Message ID: 2051", kwargs["prompt"])
        self.assertIn("Reply Context:", kwargs["prompt"])
        self.assertIn("Original Telegram Message ID: 99", kwargs["prompt"])
        self.assertIn("Original Message Author: Govorun TPG 2026", kwargs["prompt"])
        self.assertIn("Current User Message:\nЭто про что", kwargs["prompt"])
        self.assertFalse(kwargs["enforce_voice_prefix_from_transcript"])

    @mock.patch.object(bridge_handlers, "start_message_worker")
    def test_handle_update_includes_current_telegram_context_for_message_id_targeting(
        self, start_message_worker
    ):
        state = bridge.State()
        client = FakeTelegramClient()
        config = make_config()
        update = {
            "update_id": 1052,
            "message": {
                "message_id": 2052,
                "chat": {"id": 1, "type": "group"},
                "message_thread_id": 498,
                "is_topic_message": True,
                "text": "Send it to this chat message id not another one",
            },
        }

        bridge.handle_update(state, config, client, update)

        self.assertTrue(start_message_worker.called)
        kwargs = start_message_worker.call_args.kwargs
        self.assertIn("Current Telegram Context:", kwargs["prompt"])
        self.assertIn("- Current Message ID: 2052", kwargs["prompt"])
        self.assertIn("- Topic ID: 498", kwargs["prompt"])
        self.assertIn("- Chat ID: 1", kwargs["prompt"])
        self.assertIn(
            'default to Current Message ID unless they specify another numeric target.',
            kwargs["prompt"],
        )
        self.assertIn(
            "Current User Message:\nSend it to this chat message id not another one",
            kwargs["prompt"],
        )

    @mock.patch.object(bridge_handlers, "start_message_worker")
    def test_handle_update_keeps_prefix_required_in_group_when_private_bypass_enabled(
        self, start_message_worker
    ):
        state = bridge.State()
        client = FakeTelegramClient()
        config = make_config(
            required_prefixes=["@helper"],
            require_prefix_in_private=False,
        )
        update = {
            "update_id": 106,
            "message": {
                "message_id": 206,
                "chat": {"id": 1, "type": "group"},
                "text": "hello there",
            },
        }

        bridge.handle_update(state, config, client, update)

        self.assertFalse(start_message_worker.called)
        self.assertEqual(client.messages, [])

    @mock.patch.object(bridge_handlers, "start_youtube_worker")
    @mock.patch.object(bridge_handlers, "start_message_worker")
    def test_handle_update_routes_bare_youtube_link_without_prefix_in_group(
        self,
        start_message_worker,
        start_youtube_worker,
    ):
        state = bridge.State()
        client = FakeTelegramClient()
        config = make_config(
            required_prefixes=["@helper"],
            require_prefix_in_private=False,
        )
        update = {
            "update_id": 107,
            "message": {
                "message_id": 207,
                "chat": {"id": 1, "type": "group"},
                "text": "https://www.youtube.com/watch?v=yD5DFL3xPmo\nsummarise this",
            },
        }

        bridge.handle_update(state, config, client, update)

        self.assertFalse(start_message_worker.called)
        self.assertTrue(start_youtube_worker.called)
        kwargs = start_youtube_worker.call_args.kwargs
        self.assertEqual(kwargs["request_text"], "https://www.youtube.com/watch?v=yD5DFL3xPmo\nsummarise this")
        self.assertEqual(kwargs["youtube_url"], "https://www.youtube.com/watch?v=yD5DFL3xPmo")
        self.assertEqual(client.messages, [])

    @mock.patch.object(bridge_handlers, "start_youtube_worker")
    @mock.patch.object(bridge_handlers, "start_message_worker")
    def test_handle_update_does_not_auto_route_non_request_text_with_youtube_link(
        self,
        start_message_worker,
        start_youtube_worker,
    ):
        state = bridge.State()
        client = FakeTelegramClient()
        config = make_config(
            required_prefixes=["@helper"],
            require_prefix_in_private=False,
        )
        update = {
            "update_id": 108,
            "message": {
                "message_id": 208,
                "chat": {"id": 1, "type": "group"},
                "text": "watch this https://www.youtube.com/watch?v=yD5DFL3xPmo",
            },
        }

        bridge.handle_update(state, config, client, update)

        self.assertFalse(start_message_worker.called)
        self.assertFalse(start_youtube_worker.called)
        self.assertEqual(client.messages, [])

    @mock.patch.object(bridge_handlers, "send_executor_output", return_value="unavailable")
    @mock.patch.object(bridge_handlers, "run_youtube_analyzer")
    def test_process_youtube_request_returns_unavailable_when_transcript_request_has_no_transcript(
        self,
        run_youtube_analyzer,
        send_executor_output,
    ):
        state = bridge.State()
        client = FakeTelegramClient()
        config = make_config()
        run_youtube_analyzer.return_value = {
            "ok": True,
            "request_mode": "transcript",
            "title": "Example Video",
            "channel": "Example Channel",
            "transcript_text": "",
            "transcript_source": "none",
            "transcript_language": "",
            "transcript_error": "captions missing",
        }

        bridge_handlers.process_youtube_request(
            state=state,
            config=config,
            client=client,
            engine=None,
            chat_id=1,
            message_id=301,
            request_text="full transcript https://www.youtube.com/watch?v=yD5DFL3xPmo",
            youtube_url="https://www.youtube.com/watch?v=yD5DFL3xPmo",
            cancel_event=None,
        )

        sent_output = send_executor_output.call_args.kwargs["output"]
        self.assertIn("could not obtain captions or a usable transcription", sent_output)
        self.assertIn("Example Video", sent_output)

    def test_build_youtube_summary_prompt_includes_basic_video_fields(self):
        prompt = bridge_handlers.build_youtube_summary_prompt(
            "https://www.youtube.com/watch?v=yD5DFL3xPmo",
            {
                "title": "Example Video",
                "channel": "Example Channel",
                "duration_seconds": 120,
                "transcript_source": "automatic_captions",
                "transcript_language": "en",
                "transcript_text": "hello world",
                "description": "example description",
                "chapters": [],
            },
        )

        self.assertIn("Video title: Example Video", prompt)
        self.assertIn("Channel: Example Channel", prompt)
        self.assertIn("Description:\nexample description", prompt)
        self.assertIn("Transcript source: automatic_captions", prompt)

    @mock.patch.object(bridge_handlers, "start_message_worker")
    def test_handle_update_routes_ha_keyword_prompt_stateless(self, start_message_worker):
        state = bridge.State()
        client = FakeTelegramClient()
        config = make_config()
        update = {
            "update_id": 10,
            "message": {
                "message_id": 40,
                "chat": {"id": 1},
                "text": "Home Assistant turn on masters AC to dry mode at 9:25am",
            },
        }

        bridge.handle_update(state, config, client, update)

        self.assertTrue(start_message_worker.called)
        kwargs = start_message_worker.call_args.kwargs
        self.assertTrue(kwargs["stateless"])
        self.assertIn("Home Assistant priority mode is active.", kwargs["prompt"])
        self.assertIn("User request: turn on masters AC to dry mode at 9:25am", kwargs["prompt"])
        self.assertEqual(client.messages, [])

    @mock.patch.object(bridge_handlers, "start_message_worker")
    def test_handle_update_routes_server3_keyword_prompt_stateless(self, start_message_worker):
        state = bridge.State()
        client = FakeTelegramClient()
        config = make_config()
        update = {
            "update_id": 12,
            "message": {
                "message_id": 42,
                "chat": {"id": 1},
                "text": "Server3 TV open desktop and play top youtube result for deephouse 2026",
            },
        }

        bridge.handle_update(state, config, client, update)

        self.assertTrue(start_message_worker.called)
        kwargs = start_message_worker.call_args.kwargs
        self.assertTrue(kwargs["stateless"])
        self.assertIn("Server3 TV operations priority mode is active.", kwargs["prompt"])
        self.assertIn(
            "User request: open desktop and play top youtube result for deephouse 2026",
            kwargs["prompt"],
        )
        self.assertEqual(client.messages, [])

    @mock.patch.object(bridge_handlers, "start_message_worker")
    def test_handle_update_rejects_server3_keyword_without_action(self, start_message_worker):
        state = bridge.State()
        client = FakeTelegramClient()
        config = make_config()
        update = {
            "update_id": 13,
            "message": {
                "message_id": 43,
                "chat": {"id": 1},
                "text": "Server3 TV",
            },
        }

        bridge.handle_update(state, config, client, update)

        self.assertFalse(start_message_worker.called)
        self.assertEqual(len(client.messages), 1)
        self.assertIn("Server3 TV mode needs an action.", client.messages[0][1])

    @mock.patch.object(bridge_handlers, "start_message_worker")
    def test_handle_update_routes_nextcloud_keyword_prompt_stateless(self, start_message_worker):
        state = bridge.State()
        client = FakeTelegramClient()
        config = make_config()
        update = {
            "update_id": 14,
            "message": {
                "message_id": 44,
                "chat": {"id": 1},
                "text": "Nextcloud list files in Documents",
            },
        }

        bridge.handle_update(state, config, client, update)

        self.assertTrue(start_message_worker.called)
        kwargs = start_message_worker.call_args.kwargs
        self.assertTrue(kwargs["stateless"])
        self.assertIn("Nextcloud operations priority mode is active.", kwargs["prompt"])
        self.assertIn("User request: list files in Documents", kwargs["prompt"])
        self.assertEqual(client.messages, [])

    @mock.patch.object(bridge_handlers, "start_message_worker")
    def test_handle_update_rejects_nextcloud_keyword_without_action(self, start_message_worker):
        state = bridge.State()
        client = FakeTelegramClient()
        config = make_config()
        update = {
            "update_id": 15,
            "message": {
                "message_id": 45,
                "chat": {"id": 1},
                "text": "Nextcloud",
            },
        }

        bridge.handle_update(state, config, client, update)

        self.assertFalse(start_message_worker.called)
        self.assertEqual(len(client.messages), 1)
        self.assertIn("Nextcloud mode needs an action.", client.messages[0][1])

    @mock.patch.object(bridge_handlers, "start_message_worker")
    def test_handle_update_rejects_ha_keyword_without_action(self, start_message_worker):
        state = bridge.State()
        client = FakeTelegramClient()
        config = make_config()
        update = {
            "update_id": 11,
            "message": {
                "message_id": 41,
                "chat": {"id": 1},
                "text": "HA",
            },
        }

        bridge.handle_update(state, config, client, update)

        self.assertFalse(start_message_worker.called)
        self.assertEqual(len(client.messages), 1)
        self.assertIn("HA mode needs an action.", client.messages[0][1])

    def test_handle_update_routes_memory_status_command(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state = bridge.State(
                memory_engine=bridge.MemoryEngine(str(Path(tmpdir) / "memory.sqlite3")),
            )
            client = FakeTelegramClient()
            config = make_config()
            update = {
                "update_id": 1,
                "message": {
                    "message_id": 21,
                    "chat": {"id": 1},
                    "text": "/memory status",
                },
            }

            bridge.handle_update(state, config, client, update)
            self.assertTrue(client.messages)
            self.assertIn("Memory status:", client.messages[-1][1])

    @mock.patch.object(bridge_handlers, "start_message_worker")
    def test_handle_update_routes_natural_language_memory_recall(self, start_message_worker):
        with tempfile.TemporaryDirectory() as tmpdir:
            memory_engine = bridge.MemoryEngine(str(Path(tmpdir) / "memory.sqlite3"))
            key = bridge.MemoryEngine.telegram_key(1)
            turn = memory_engine.begin_turn(
                conversation_key=key,
                channel="telegram",
                sender_name="User",
                user_input="first note",
            )
            memory_engine.finish_turn(
                turn,
                channel="telegram",
                assistant_text="reply one",
                new_thread_id="thread-1",
            )
            turn = memory_engine.begin_turn(
                conversation_key=key,
                channel="telegram",
                sender_name="User",
                user_input="second note",
            )
            memory_engine.finish_turn(
                turn,
                channel="telegram",
                assistant_text="reply two",
                new_thread_id="thread-1",
            )

            state = bridge.State(memory_engine=memory_engine)
            client = FakeTelegramClient()
            config = make_config()
            update = {
                "update_id": 46,
                "message": {
                    "message_id": 453,
                    "chat": {"id": 1, "type": "private"},
                    "text": "what were the last 2 messages i sent you?",
                },
            }

            bridge.handle_update(state, config, client, update)

            self.assertFalse(start_message_worker.called)
            self.assertTrue(client.messages)
            self.assertIn("Your last 2 messages in memory are:", client.messages[-1][1])
            self.assertIn("first note", client.messages[-1][1])
            self.assertIn("second note", client.messages[-1][1])

    def test_handle_update_rejects_too_long_input_before_worker_dispatch(self):
        state = bridge.State()
        client = FakeTelegramClient()
        config = make_config(max_input_chars=10)
        update = {
            "update_id": 2,
            "message": {
                "message_id": 30,
                "chat": {"id": 1},
                "text": "x" * 11,
            },
        }

        bridge.handle_update(state, config, client, update)
        self.assertEqual(len(client.messages), 1)
        self.assertIn("Input too long (11 chars). Max is 10.", client.messages[0][1])

    def test_handle_update_denies_non_allowlisted_chat(self):
        state = bridge.State()
        client = FakeTelegramClient()
        config = make_config(allowed_chat_ids={1})
        update = {
            "update_id": 3,
            "message": {
                "message_id": 31,
                "chat": {"id": 2},
                "text": "hello",
            },
        }

        bridge.handle_update(state, config, client, update)
        self.assertEqual(len(client.messages), 1)
        self.assertEqual(client.messages[0][1], config.denied_message)

    def test_handle_update_allows_private_chat_when_unlisted_allowed(self):
        state = bridge.State()
        client = FakeTelegramClient()
        config = make_config(
            allowed_chat_ids={1},
            allow_private_chats_unlisted=True,
        )
        update = {
            "update_id": 4,
            "message": {
                "message_id": 31,
                "chat": {"id": 2, "type": "private"},
                "text": "hello",
            },
        }

        with mock.patch.object(bridge_handlers, "start_message_worker") as start_message_worker:
            bridge.handle_update(state, config, client, update)

        self.assertTrue(start_message_worker.called)
        self.assertEqual(client.messages, [])

    def test_handle_update_uses_whatsapp_memory_conversation_key(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            memory_engine = bridge.MemoryEngine(str(Path(tmpdir) / "memory.sqlite3"))
            state = bridge.State(memory_engine=memory_engine)
            client = FakeTelegramClient(channel_name="whatsapp")
            config = make_config(
                channel_plugin="whatsapp",
                allowed_chat_ids={2},
            )
            update = {
                "update_id": 44,
                "message": {
                    "message_id": 451,
                    "chat": {"id": 2, "type": "private"},
                    "text": "/memory status",
                },
            }
            captured = {}

            def fake_memory_command(engine, conversation_key, text):
                captured["conversation_key"] = conversation_key
                return SimpleNamespace(
                    handled=True,
                    response="memory ok",
                    run_prompt=None,
                    stateless=False,
                )

            with mock.patch.object(
                bridge_handlers,
                "handle_memory_command",
                side_effect=fake_memory_command,
            ):
                bridge.handle_update(state, config, client, update)

            self.assertEqual(captured.get("conversation_key"), "wa:2")
            self.assertEqual(client.messages[-1][1], "memory ok")

    def test_handle_update_uses_configured_shared_memory_key_for_telegram(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            memory_engine = bridge.MemoryEngine(str(Path(tmpdir) / "memory.sqlite3"))
            state = bridge.State(memory_engine=memory_engine)
            client = FakeTelegramClient(channel_name="telegram")
            config = make_config(
                allowed_chat_ids={2},
                shared_memory_key="shared:architect:main",
            )
            update = {
                "update_id": 45,
                "message": {
                    "message_id": 452,
                    "chat": {"id": 2, "type": "private"},
                    "text": "/memory status",
                },
            }
            captured = {}

            def fake_memory_command(engine, conversation_key, text):
                captured["conversation_key"] = conversation_key
                return SimpleNamespace(
                    handled=True,
                    response="memory ok",
                    run_prompt=None,
                    stateless=False,
                )

            with mock.patch.object(
                bridge_handlers,
                "handle_memory_command",
                side_effect=fake_memory_command,
            ):
                bridge.handle_update(state, config, client, update)

            self.assertEqual(
                captured.get("conversation_key"),
                "shared:architect:main:session:tg:2",
            )
            self.assertEqual(client.messages[-1][1], "memory ok")

    def test_build_status_text_uses_configured_channel_memory_namespace(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            memory_engine = bridge.MemoryEngine(str(Path(tmpdir) / "memory.sqlite3"))
            memory_engine.set_mode("wa:9", "session_only")
            memory_engine.begin_turn("wa:9", "whatsapp", "owner", "hello")
            state = bridge.State(memory_engine=memory_engine)
            config = make_config(channel_plugin="whatsapp")
            status_text = bridge_handlers.build_status_text(state, config, chat_id=9)
            self.assertIn("Memory mode: session_only", status_text)
            self.assertIn("Memory messages: 1", status_text)

    def test_build_status_text_uses_live_shared_memory_scope_when_configured(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            memory_engine = bridge.MemoryEngine(str(Path(tmpdir) / "memory.sqlite3"))
            memory_engine.set_mode("shared:architect:main:session:tg:9", "session_only")
            state = bridge.State(memory_engine=memory_engine)
            config = make_config(shared_memory_key="shared:architect:main")
            status_text = bridge_handlers.build_status_text(state, config, chat_id=9)
            self.assertIn("Memory mode: session_only", status_text)

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

    def test_handle_update_rejects_when_chat_busy(self):
        state = bridge.State()
        state.busy_chats.add(1)
        client = FakeTelegramClient()
        config = make_config()
        update = {
            "update_id": 4,
            "message": {
                "message_id": 32,
                "chat": {"id": 1},
                "text": "run now",
            },
        }

        bridge.handle_update(state, config, client, update)
        self.assertEqual(len(client.messages), 1)
        self.assertEqual(client.messages[0][1], config.busy_message)

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

    def test_execute_prompt_with_retry_handles_executor_cancelled(self):
        class CancelingEngine:
            engine_name = "canceling"

            def run(
                self,
                config,
                prompt,
                thread_id,
                image_path=None,
                progress_callback=None,
                cancel_event=None,
            ):
                raise bridge_handlers.ExecutorCancelledError("cancel")

        class FakeProgress:
            def __init__(self):
                self.last_failure = ""

            def handle_executor_event(self, _event):
                return None

            def set_phase(self, _phase):
                return None

            def mark_failure(self, detail):
                self.last_failure = detail

        state = bridge.State()
        state_repo = bridge.StateRepository(state)
        client = FakeTelegramClient()
        config = make_config()
        progress = FakeProgress()

        result = bridge_handlers.execute_prompt_with_retry(
            state_repo=state_repo,
            config=config,
            client=client,
            engine=CancelingEngine(),
            chat_id=1,
            message_id=50,
            prompt_text="hello",
            previous_thread_id=None,
            image_path=None,
            progress=progress,
            cancel_event=threading.Event(),
            session_continuity_enabled=True,
        )

        self.assertIsNone(result)
        self.assertEqual(progress.last_failure, "Execution canceled.")
        self.assertTrue(client.messages)
        self.assertEqual(client.messages[-1][1], "Request canceled.")

    def test_execute_prompt_with_retry_surfaces_usage_limit_without_retry(self):
        class UsageLimitEngine:
            engine_name = "usage-limit"

            def __init__(self):
                self.calls = 0

            def run(
                self,
                config,
                prompt,
                thread_id,
                image_path=None,
                progress_callback=None,
                cancel_event=None,
            ):
                self.calls += 1
                return subprocess.CompletedProcess(
                    args=["codex", "exec"],
                    returncode=1,
                    stdout=(
                        "{\"type\":\"error\",\"message\":\"You've hit your usage limit. "
                        "Upgrade to Pro and try again at 2:00 PM.\"}\n"
                        "{\"type\":\"turn.failed\",\"error\":{\"message\":\"You've hit your usage "
                        "limit. Upgrade to Pro and try again at 2:00 PM.\"}}\n"
                    ),
                    stderr="",
                )

        class FakeProgress:
            def __init__(self):
                self.last_failure = ""

            def handle_executor_event(self, _event):
                return None

            def set_phase(self, _phase):
                return None

            def mark_failure(self, detail):
                self.last_failure = detail

        state = bridge.State()
        state_repo = bridge.StateRepository(state)
        client = FakeTelegramClient()
        config = make_config(persistent_workers_enabled=True)
        progress = FakeProgress()
        engine = UsageLimitEngine()

        result = bridge_handlers.execute_prompt_with_retry(
            state_repo=state_repo,
            config=config,
            client=client,
            engine=engine,
            chat_id=1,
            message_id=51,
            prompt_text="hello",
            previous_thread_id=None,
            image_path=None,
            progress=progress,
            cancel_event=threading.Event(),
            session_continuity_enabled=True,
        )

        self.assertIsNone(result)
        self.assertEqual(engine.calls, 1)
        self.assertEqual(progress.last_failure, "Execution failed.")
        self.assertTrue(client.messages)
        self.assertEqual(
            client.messages[-1][1],
            "The runtime has hit its usage limit. Try again after 2:00 PM.",
        )

    def test_execute_prompt_with_retry_falls_back_when_actor_identity_kwargs_unsupported(self):
        class LegacyEngine:
            engine_name = "legacy"

            def __init__(self):
                self.calls = 0

            def run(
                self,
                config,
                prompt,
                thread_id,
                image_path=None,
                progress_callback=None,
                cancel_event=None,
            ):
                del config, thread_id, image_path, progress_callback, cancel_event
                self.calls += 1
                stdout = json.dumps(
                    {
                        "type": "item.completed",
                        "item": {"type": "agent_message", "text": f"ok:{prompt}"},
                    }
                )
                return subprocess.CompletedProcess(args=["legacy"], returncode=0, stdout=stdout, stderr="")

        class FakeProgress:
            def handle_executor_event(self, _event):
                return None

            def set_phase(self, _phase):
                return None

            def mark_failure(self, _detail):
                return None

        state = bridge.State()
        state_repo = bridge.StateRepository(state)
        client = FakeTelegramClient()
        config = make_config()
        engine = LegacyEngine()

        result = bridge_handlers.execute_prompt_with_retry(
            state_repo=state_repo,
            config=config,
            client=client,
            engine=engine,
            scope_key="tg:1",
            chat_id=1,
            message_thread_id=None,
            message_id=52,
            prompt_text="hello",
            previous_thread_id=None,
            image_path=None,
            actor_user_id=123,
            progress=FakeProgress(),
            cancel_event=threading.Event(),
            session_continuity_enabled=True,
        )

        self.assertIsNotNone(result)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(engine.calls, 1)

    def test_process_prompt_resets_stale_threads_when_auth_fingerprint_changes(self):
        class RecordingEngine:
            engine_name = "codex"

            def __init__(self):
                self.thread_ids = []

            def run(
                self,
                config,
                prompt,
                thread_id,
                session_key=None,
                channel_name=None,
                actor_chat_id=None,
                actor_user_id=None,
                image_path=None,
                image_paths=None,
                progress_callback=None,
                cancel_event=None,
            ):
                del (
                    config,
                    prompt,
                    session_key,
                    channel_name,
                    actor_chat_id,
                    actor_user_id,
                    image_path,
                    image_paths,
                    progress_callback,
                    cancel_event,
                )
                self.thread_ids.append(thread_id)
                stdout = json.dumps(
                    {
                        "type": "item.completed",
                        "item": {"type": "agent_message", "text": "fresh-session"},
                    }
                )
                return subprocess.CompletedProcess(
                    args=["codex", "exec"],
                    returncode=0,
                    stdout=stdout,
                    stderr="",
                )

        with tempfile.TemporaryDirectory() as tmpdir:
            state_dir = Path(tmpdir)
            memory_engine = bridge.MemoryEngine(str(state_dir / "memory.sqlite3"))
            conversation_key = "tg:1"
            memory_engine.set_session_thread_id(conversation_key, "thread-memory-old")
            state = bridge.State(
                chat_threads={conversation_key: "thread-bridge-old"},
                chat_thread_path=str(state_dir / "chat_threads.json"),
                worker_sessions={
                    conversation_key: bridge.WorkerSession(
                        created_at=1.0,
                        last_used_at=2.0,
                        thread_id="thread-bridge-old",
                        policy_fingerprint="policy",
                    )
                },
                worker_sessions_path=str(state_dir / "worker_sessions.json"),
                in_flight_requests={},
                in_flight_path=str(state_dir / "in_flight_requests.json"),
                memory_engine=memory_engine,
                auth_fingerprint_path=str(state_dir / "auth_fingerprint.txt"),
                auth_fingerprint="old-auth",
            )
            Path(state.auth_fingerprint_path).write_text("old-auth\n", encoding="utf-8")
            client = FakeTelegramClient()
            config = make_config(state_dir=str(state_dir), shared_memory_key="")
            engine = RecordingEngine()

            with mock.patch.object(
                bridge_auth_state,
                "compute_current_auth_fingerprint",
                return_value="new-auth",
            ):
                bridge_handlers.process_prompt(
                    state=state,
                    config=config,
                    client=client,
                    engine=engine,
                    scope_key=conversation_key,
                    chat_id=1,
                    message_thread_id=None,
                    message_id=99,
                    prompt="hello after login switch",
                    photo_file_id=None,
                    voice_file_id=None,
                    document=None,
                )

            self.assertEqual(engine.thread_ids, [None])
            self.assertEqual(state.chat_threads, {})
            self.assertEqual(state.worker_sessions, {})
            self.assertIsNone(memory_engine.get_session_thread_id(conversation_key))
            self.assertTrue(client.messages)
            self.assertIn("fresh-session", client.messages[-1][1])

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

    def test_build_canonical_sessions_from_legacy(self):
        worker = bridge.WorkerSession(
            created_at=1.0,
            last_used_at=2.0,
            thread_id="thread-2",
            policy_fingerprint="fp",
        )
        sessions = bridge.build_canonical_sessions_from_legacy(
            chat_threads={1: "thread-1", 2: "thread-2"},
            worker_sessions={2: worker},
            in_flight_requests={3: {"started_at": 9.0, "message_id": 88}},
        )
        self.assertIn(1, sessions)
        self.assertIn(2, sessions)
        self.assertIn(3, sessions)
        self.assertEqual(sessions[1].thread_id, "thread-1")
        self.assertEqual(sessions[2].worker_policy_fingerprint, "fp")
        self.assertEqual(sessions[3].in_flight_message_id, 88)

    def test_state_repository_syncs_canonical_when_enabled(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state = bridge.State(
                chat_thread_path=str(Path(tmpdir) / "chat_threads.json"),
                worker_sessions_path=str(Path(tmpdir) / "worker_sessions.json"),
                in_flight_path=str(Path(tmpdir) / "in_flight_requests.json"),
                chat_sessions_path=str(Path(tmpdir) / "chat_sessions.json"),
                canonical_sessions_enabled=True,
            )
            repo = bridge.StateRepository(state)
            repo.set_thread_id(7, "thread-7")
            repo.mark_in_flight_request(7, 700)

            sessions = bridge.load_canonical_sessions(state.chat_sessions_path)
            self.assertIn("tg:7", sessions)
            self.assertEqual(sessions["tg:7"].thread_id, "thread-7")
            self.assertEqual(sessions["tg:7"].in_flight_message_id, 700)

    def test_state_repository_syncs_canonical_to_sqlite_when_enabled(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sqlite_path = str(Path(tmpdir) / "chat_sessions.sqlite3")
            json_path = str(Path(tmpdir) / "chat_sessions.json")
            state = bridge.State(
                chat_thread_path=str(Path(tmpdir) / "chat_threads.json"),
                worker_sessions_path=str(Path(tmpdir) / "worker_sessions.json"),
                in_flight_path=str(Path(tmpdir) / "in_flight_requests.json"),
                chat_sessions_path=json_path,
                canonical_sessions_enabled=True,
                canonical_sqlite_enabled=True,
                canonical_sqlite_path=sqlite_path,
                canonical_json_mirror_enabled=False,
            )
            repo = bridge.StateRepository(state)
            repo.set_thread_id(12, "thread-12")
            repo.mark_in_flight_request(12, 1200)

            sessions = bridge.load_canonical_sessions_sqlite(sqlite_path)
            self.assertIn("tg:12", sessions)
            self.assertEqual(sessions["tg:12"].thread_id, "thread-12")
            self.assertEqual(sessions["tg:12"].in_flight_message_id, 1200)
            self.assertFalse(Path(json_path).exists())

    def test_canonical_sqlite_json_mirror_writes_json_when_enabled(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sqlite_path = str(Path(tmpdir) / "chat_sessions.sqlite3")
            json_path = str(Path(tmpdir) / "chat_sessions.json")
            state = bridge.State(
                chat_thread_path=str(Path(tmpdir) / "chat_threads.json"),
                worker_sessions_path=str(Path(tmpdir) / "worker_sessions.json"),
                in_flight_path=str(Path(tmpdir) / "in_flight_requests.json"),
                chat_sessions_path=json_path,
                canonical_sessions_enabled=True,
                canonical_sqlite_enabled=True,
                canonical_sqlite_path=sqlite_path,
                canonical_json_mirror_enabled=True,
            )
            repo = bridge.StateRepository(state)
            repo.set_thread_id(13, "thread-13")

            sqlite_sessions = bridge.load_canonical_sessions_sqlite(sqlite_path)
            json_sessions = bridge.load_canonical_sessions(json_path)
            self.assertEqual(sqlite_sessions["tg:13"].thread_id, "thread-13")
            self.assertEqual(json_sessions["tg:13"].thread_id, "thread-13")

    def test_load_or_import_canonical_sessions_sqlite_imports_only_when_empty(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sqlite_path = str(Path(tmpdir) / "chat_sessions.sqlite3")
            initial_sessions = {
                1: bridge.CanonicalSession(thread_id="thread-initial"),
            }
            loaded, imported = bridge.load_or_import_canonical_sessions_sqlite(
                sqlite_path,
                import_sessions=initial_sessions,
            )
            self.assertTrue(imported)
            self.assertEqual(loaded["tg:1"].thread_id, "thread-initial")

            replacement_sessions = {
                1: bridge.CanonicalSession(thread_id="thread-replacement"),
                2: bridge.CanonicalSession(thread_id="thread-two"),
            }
            loaded_again, imported_again = bridge.load_or_import_canonical_sessions_sqlite(
                sqlite_path,
                import_sessions=replacement_sessions,
            )
            self.assertFalse(imported_again)
            self.assertEqual(loaded_again["tg:1"].thread_id, "thread-initial")
            self.assertNotIn("tg:2", loaded_again)

    def test_build_legacy_from_canonical(self):
        canonical = {
            "tg:9": bridge.CanonicalSession(
                thread_id="thread-9",
                worker_created_at=1.0,
                worker_last_used_at=2.0,
                worker_policy_fingerprint="fp",
                in_flight_started_at=3.0,
                in_flight_message_id=90,
            )
        }
        chat_threads, worker_sessions, in_flight = bridge.build_legacy_from_canonical(canonical)
        self.assertEqual(chat_threads["tg:9"], "thread-9")
        self.assertEqual(worker_sessions["tg:9"].policy_fingerprint, "fp")
        self.assertEqual(in_flight["tg:9"]["message_id"], 90)

    def test_canonical_first_set_thread_and_clear_worker_mirrors_legacy(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state = bridge.State(
                chat_thread_path=str(Path(tmpdir) / "chat_threads.json"),
                worker_sessions_path=str(Path(tmpdir) / "worker_sessions.json"),
                in_flight_path=str(Path(tmpdir) / "in_flight_requests.json"),
                chat_sessions_path=str(Path(tmpdir) / "chat_sessions.json"),
                canonical_sessions_enabled=True,
                canonical_legacy_mirror_enabled=True,
                chat_sessions={
                    "tg:5": bridge.CanonicalSession(
                        thread_id="old-thread",
                        worker_created_at=1.0,
                        worker_last_used_at=1.0,
                        worker_policy_fingerprint="old",
                    )
                },
            )
            bridge.persist_canonical_sessions(state)
            bridge.mirror_legacy_from_canonical(state, persist=True)

            repo = bridge.StateRepository(state)
            repo.set_thread_id(5, "new-thread")
            repo.clear_worker_session(5)

            sessions = bridge.load_canonical_sessions(state.chat_sessions_path)
            self.assertEqual(sessions["tg:5"].thread_id, "new-thread")
            self.assertIsNone(sessions["tg:5"].worker_created_at)

            threads = json.loads(Path(state.chat_thread_path).read_text(encoding="utf-8"))
            workers = json.loads(Path(state.worker_sessions_path).read_text(encoding="utf-8"))
            self.assertEqual(threads["tg:5"], "new-thread")
            self.assertEqual(workers, {})

    def test_canonical_first_without_legacy_mirror_skips_legacy_persist(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state = bridge.State(
                chat_thread_path=str(Path(tmpdir) / "chat_threads.json"),
                worker_sessions_path=str(Path(tmpdir) / "worker_sessions.json"),
                in_flight_path=str(Path(tmpdir) / "in_flight_requests.json"),
                chat_sessions_path=str(Path(tmpdir) / "chat_sessions.json"),
                canonical_sessions_enabled=True,
                canonical_legacy_mirror_enabled=False,
            )
            repo = bridge.StateRepository(state)
            repo.set_thread_id(11, "thread-11")

            sessions = bridge.load_canonical_sessions(state.chat_sessions_path)
            self.assertEqual(sessions["tg:11"].thread_id, "thread-11")
            self.assertFalse(Path(state.chat_thread_path).exists())

    def test_ensure_chat_worker_session_canonical_rejects_when_all_workers_busy(self):
        state = bridge.State(
            canonical_sessions_enabled=True,
            chat_sessions={
                "tg:2": bridge.CanonicalSession(
                    thread_id="thread-busy",
                    worker_created_at=1.0,
                    worker_last_used_at=10.0,
                    worker_policy_fingerprint="fp",
                )
            },
        )
        state.busy_chats.add(2)
        client = FakeTelegramClient()
        config = make_config(
            persistent_workers_enabled=True,
            persistent_workers_max=1,
            canonical_sessions_enabled=True,
        )

        allowed = bridge.ensure_chat_worker_session(state, config, client, chat_id=1, message_id=99)
        self.assertFalse(allowed)
        self.assertTrue(client.messages)
        self.assertIn("workers are currently in use", client.messages[-1][1])

    def test_ensure_chat_worker_session_canonical_sends_policy_refresh_notice(self):
        state = bridge.State(
            canonical_sessions_enabled=True,
            chat_sessions={
                "tg:1": bridge.CanonicalSession(
                    thread_id="thread-old",
                    worker_created_at=1.0,
                    worker_last_used_at=2.0,
                    worker_policy_fingerprint="stale-fingerprint",
                )
            },
        )
        client = FakeTelegramClient()
        config = make_config(
            persistent_workers_enabled=True,
            persistent_workers_max=2,
            canonical_sessions_enabled=True,
        )

        allowed = bridge.ensure_chat_worker_session(state, config, client, chat_id=1, message_id=88)
        self.assertTrue(allowed)
        self.assertTrue(client.messages)
        self.assertIn("Policy/context files changed", client.messages[-1][1])
        self.assertIn("tg:1", state.chat_sessions)
        self.assertEqual(state.chat_sessions["tg:1"].thread_id, "")

    def test_state_repository_concurrent_inflight_persistence_is_safe(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state = bridge.State(
                chat_thread_path=str(Path(tmpdir) / "chat_threads.json"),
                worker_sessions_path=str(Path(tmpdir) / "worker_sessions.json"),
                in_flight_path=str(Path(tmpdir) / "in_flight_requests.json"),
            )
            repo = bridge.StateRepository(state)
            errors = []
            errors_lock = threading.Lock()

            def worker(seed: int) -> None:
                for i in range(120):
                    chat_id = ((seed * 7) + i) % 12 + 1
                    try:
                        repo.mark_in_flight_request(chat_id, i)
                        repo.clear_in_flight_request(chat_id)
                    except Exception as exc:  # pragma: no cover - regression guard
                        with errors_lock:
                            errors.append(repr(exc))
                        return

            threads = [threading.Thread(target=worker, args=(idx,)) for idx in range(16)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

            self.assertEqual(errors, [])

    def test_finalize_chat_work_clears_busy_when_inflight_clear_fails(self):
        state = bridge.State()
        state.busy_chats.add(1)
        client = FakeTelegramClient()

        class FailingStateRepo:
            def __init__(self, _state):
                pass

            def clear_in_flight_request(self, _chat_id):
                raise RuntimeError("boom")

        with mock.patch.object(bridge_session_manager, "StateRepository", FailingStateRepo):
            bridge_session_manager.finalize_chat_work(state, client, chat_id=1)
        self.assertNotIn("tg:1", state.busy_chats)


if __name__ == "__main__":
    unittest.main()
