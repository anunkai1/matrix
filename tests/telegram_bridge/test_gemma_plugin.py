import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
BRIDGE_DIR = ROOT / "src" / "telegram_bridge"
SRC_ROOT = ROOT / "src"
if str(BRIDGE_DIR) not in sys.path:
    sys.path.insert(0, str(BRIDGE_DIR))
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

import engine_adapter as bridge_engine_adapter
import plugin_registry as bridge_plugin_registry


class GemmaPluginTests(unittest.TestCase):
    def test_default_plugin_registry_exposes_gemma_engine(self):
        registry = bridge_plugin_registry.build_default_plugin_registry()
        self.assertIn("gemma", registry.list_engines())
        self.assertIn("chatgptweb", registry.list_engines())
        self.assertIsInstance(registry.build_engine("chatgptweb"), bridge_engine_adapter.ChatGPTWebEngineAdapter)
        self.assertIsInstance(registry.build_engine("chatgpt_web"), bridge_engine_adapter.ChatGPTWebEngineAdapter)
        self.assertIsInstance(registry.build_engine("gemma"), bridge_engine_adapter.GemmaEngineAdapter)
        self.assertIsInstance(registry.build_engine("venice"), bridge_engine_adapter.VeniceEngineAdapter)

    def test_gemma_http_engine_extracts_ollama_content(self):
        engine = bridge_engine_adapter.GemmaEngineAdapter()
        config = SimpleNamespace(
            gemma_provider="ollama_http",
            gemma_model="gemma4:26b",
            gemma_base_url="http://server4-beast:11434",
            gemma_request_timeout_seconds=30,
        )
        response = b'{"message":{"role":"assistant","content":"hello from gemma"},"done":true}'
        fake_urlopen = mock.MagicMock()
        fake_urlopen.return_value.__enter__.return_value.read.return_value = response
        with mock.patch.object(bridge_engine_adapter.urllib_request, "urlopen", fake_urlopen):
            result = engine.run(config=config, prompt="hello", thread_id=None)
        self.assertEqual(result.returncode, 0)
        self.assertIn("OUTPUT_BEGIN", result.stdout)
        self.assertIn("hello from gemma", result.stdout)

    def test_venice_http_engine_extracts_chat_completion_content(self):
        engine = bridge_engine_adapter.VeniceEngineAdapter()
        config = SimpleNamespace(
            venice_api_key="venice-key",
            venice_base_url="https://api.venice.ai/api/v1",
            venice_model="mistral-31-24b",
            venice_temperature=0.2,
            venice_request_timeout_seconds=30,
        )
        response = b'{"choices":[{"message":{"role":"assistant","content":"hello from venice"}}],"object":"chat.completion"}'
        fake_urlopen = mock.MagicMock()
        fake_urlopen.return_value.__enter__.return_value.read.return_value = response
        with mock.patch.object(bridge_engine_adapter.urllib_request, "urlopen", fake_urlopen):
            result = engine.run(config=config, prompt="hello", thread_id=None)
        self.assertEqual(result.returncode, 0)
        self.assertIn("OUTPUT_BEGIN", result.stdout)
        self.assertIn("hello from venice", result.stdout)

    def test_chatgpt_web_engine_extracts_json_answer_from_cli(self):
        engine = bridge_engine_adapter.ChatGPTWebEngineAdapter()
        config = SimpleNamespace(
            chatgpt_web_bridge_script="/srv/chatgpt_web_bridge.py",
            chatgpt_web_python_bin="python3",
            chatgpt_web_browser_brain_url="http://127.0.0.1:47831",
            chatgpt_web_browser_brain_service="server3-browser-brain.service",
            chatgpt_web_url="https://chatgpt.com/",
            chatgpt_web_start_service=True,
            chatgpt_web_request_timeout_seconds=1,
            chatgpt_web_ready_timeout_seconds=1,
            chatgpt_web_response_timeout_seconds=1,
            chatgpt_web_poll_seconds=0.1,
        )
        process = mock.MagicMock()
        process.communicate.return_value = ('{"answer":"hello from chatgpt web","tab_id":"tab-1"}', "")
        process.returncode = 0
        with mock.patch.object(bridge_engine_adapter.subprocess, "Popen", return_value=process) as popen:
            result = engine.run(config=config, prompt="hello", thread_id=None)
        self.assertEqual(result.returncode, 0)
        self.assertIn("OUTPUT_BEGIN", result.stdout)
        self.assertIn("hello from chatgpt web", result.stdout)
        self.assertEqual(popen.call_args.args[0][-1], "--start-service")
        self.assertEqual(process.communicate.call_args.kwargs["input"], "hello")

    def test_chatgpt_web_engine_does_not_start_service_by_default(self):
        engine = bridge_engine_adapter.ChatGPTWebEngineAdapter()
        config = SimpleNamespace(
            chatgpt_web_bridge_script="/srv/chatgpt_web_bridge.py",
            chatgpt_web_python_bin="python3",
            chatgpt_web_browser_brain_url="http://127.0.0.1:47831",
            chatgpt_web_browser_brain_service="server3-browser-brain.service",
            chatgpt_web_url="https://chatgpt.com/",
            chatgpt_web_request_timeout_seconds=1,
            chatgpt_web_ready_timeout_seconds=1,
            chatgpt_web_response_timeout_seconds=1,
            chatgpt_web_poll_seconds=0.1,
        )
        process = mock.MagicMock()
        process.communicate.return_value = ('{"answer":"hello from chatgpt web","tab_id":"tab-1"}', "")
        process.returncode = 0

        with mock.patch.object(bridge_engine_adapter.subprocess, "Popen", return_value=process) as popen:
            result = engine.run(config=config, prompt="hello", thread_id=None)

        self.assertEqual(result.returncode, 0)
        self.assertNotIn("--start-service", popen.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
