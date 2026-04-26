import os
import sys
import tempfile
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
import gemma_readonly_tools
import plugin_registry as bridge_plugin_registry


class GemmaPluginTests(unittest.TestCase):
    def test_default_plugin_registry_exposes_gemma_engine(self):
        registry = bridge_plugin_registry.build_default_plugin_registry()
        self.assertIn("gemma", registry.list_engines())
        self.assertIsInstance(registry.build_engine("gemma"), bridge_engine_adapter.GemmaEngineAdapter)

    def test_gemma_http_engine_extracts_ollama_content(self):
        engine = bridge_engine_adapter.GemmaEngineAdapter()
        config = SimpleNamespace(
            gemma_provider="ollama_http",
            gemma_model="gemma4:26b",
            gemma_base_url="http://server4-beast:11434",
            gemma_request_timeout_seconds=30,
            gemma_readonly_tools_enabled=False,
        )
        response = b'{"message":{"role":"assistant","content":"hello from gemma"},"done":true}'
        fake_urlopen = mock.MagicMock()
        fake_urlopen.return_value.__enter__.return_value.read.return_value = response
        with mock.patch.object(bridge_engine_adapter.urllib_request, "urlopen", fake_urlopen):
            result = engine.run(config=config, prompt="hello", thread_id=None)
        self.assertEqual(result.returncode, 0)
        self.assertIn("OUTPUT_BEGIN", result.stdout)
        self.assertIn("hello from gemma", result.stdout)

    def test_gemma_http_engine_executes_readonly_tool_request_then_final_answer(self):
        engine = bridge_engine_adapter.GemmaEngineAdapter()
        with tempfile.TemporaryDirectory() as tmpdir:
            Path(tmpdir, "note.txt").write_text("tool-visible content\n", encoding="utf-8")
            config = SimpleNamespace(
                gemma_provider="ollama_http",
                gemma_model="gemma4:26b",
                gemma_base_url="http://server4-beast:11434",
                gemma_request_timeout_seconds=30,
                gemma_readonly_tools_enabled=True,
                gemma_readonly_roots=[tmpdir],
                gemma_readonly_tool_timeout_seconds=5,
            )
            responses = [
                b'{"message":{"role":"assistant","content":"```json\\n{\\"tool\\":\\"read_file\\",\\"args\\":{\\"path\\":\\"note.txt\\"}}\\n```\\nI will use this."},"done":true}',
                b'{"message":{"role":"assistant","content":"The file says tool-visible content."},"done":true}',
            ]
            fake_urlopen = mock.MagicMock()
            fake_urlopen.return_value.__enter__.return_value.read.side_effect = responses
            with mock.patch.object(bridge_engine_adapter.urllib_request, "urlopen", fake_urlopen):
                result = engine.run(config=config, prompt="What is in note.txt?", thread_id=None)
        self.assertEqual(result.returncode, 0)
        self.assertIn("The file says tool-visible content.", result.stdout)
        self.assertEqual(fake_urlopen.call_count, 2)
        second_body = json_body_from_request(fake_urlopen.call_args_list[1].args[0])
        self.assertIn("READ-ONLY TOOL RESULT", second_body["messages"][-1]["content"])
        self.assertIn("tool-visible content", second_body["messages"][-1]["content"])

    def test_gemma_http_engine_lists_files_when_initial_tool_prompt_returns_empty(self):
        engine = bridge_engine_adapter.GemmaEngineAdapter()
        with tempfile.TemporaryDirectory() as tmpdir:
            Path(tmpdir, "visible.txt").write_text("ok\n", encoding="utf-8")
            config = SimpleNamespace(
                gemma_provider="ollama_http",
                gemma_model="gemma4:26b",
                gemma_base_url="http://server4-beast:11434",
                gemma_request_timeout_seconds=30,
                gemma_readonly_tools_enabled=True,
                gemma_readonly_roots=[tmpdir],
                gemma_readonly_tool_timeout_seconds=5,
            )
            fake_urlopen = mock.MagicMock()
            fake_urlopen.return_value.__enter__.return_value.read.return_value = (
                b'{"message":{"role":"assistant","content":""},"done":true}'
            )
            with mock.patch.object(bridge_engine_adapter.urllib_request, "urlopen", fake_urlopen):
                result = engine.run(
                    config=config,
                    prompt="Can you list files you have access to read?",
                    thread_id=None,
                )
        self.assertEqual(result.returncode, 0)
        self.assertIn("visible.txt", result.stdout)
        self.assertNotIn("(No output", result.stdout)

    def test_gemma_http_engine_reads_current_file_request_despite_prior_list_context(self):
        engine = bridge_engine_adapter.GemmaEngineAdapter()
        with tempfile.TemporaryDirectory() as tmpdir:
            Path(tmpdir, "AGENTS.md").write_text("agent instructions\n", encoding="utf-8")
            config = SimpleNamespace(
                gemma_provider="ollama_http",
                gemma_model="gemma4:26b",
                gemma_base_url="http://server4-beast:11434",
                gemma_request_timeout_seconds=30,
                gemma_readonly_tools_enabled=True,
                gemma_readonly_roots=[tmpdir],
                gemma_readonly_tool_timeout_seconds=5,
            )
            fake_urlopen = mock.MagicMock()
            fake_urlopen.return_value.__enter__.return_value.read.return_value = (
                b'{"message":{"role":"assistant","content":""},"done":true}'
            )
            prompt = (
                "Recent Messages:\n"
                "- [user] anunakii: Can you list files you have access to read?\n\n"
                "Current User Message:\n"
                "can you post whats inside agents.md file here"
            )
            with mock.patch.object(bridge_engine_adapter.urllib_request, "urlopen", fake_urlopen):
                result = engine.run(config=config, prompt=prompt, thread_id=None)
        self.assertEqual(result.returncode, 0)
        self.assertIn("agent instructions", result.stdout)
        self.assertNotIn("Current listing", result.stdout)

    def test_readonly_harness_blocks_paths_outside_allowed_roots(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            harness = gemma_readonly_tools.GemmaReadonlyToolHarness(allowed_roots=[tmpdir])
            result = harness.execute("read_file", {"path": "/etc/passwd"})
        self.assertFalse(result.ok)
        self.assertIn("outside allowed", result.error)

    def test_readonly_harness_blocks_private_internal_paths(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            private_dir = Path(tmpdir, "private")
            private_dir.mkdir()
            Path(private_dir, "SOUL.md").write_text("hidden\n", encoding="utf-8")
            Path(tmpdir, ".git").mkdir()
            Path(tmpdir, "public.txt").write_text("ok\n", encoding="utf-8")
            harness = gemma_readonly_tools.GemmaReadonlyToolHarness(allowed_roots=[tmpdir])
            read_result = harness.execute("read_file", {"path": "private/SOUL.md"})
            list_result = harness.execute("list_files", {"path": ".", "max_depth": 1})
            case_result = harness.execute("read_file", {"path": "PUBLIC.TXT"})
        self.assertFalse(read_result.ok)
        self.assertIn("private/internal", read_result.error)
        self.assertIn("public.txt", list_result.output)
        self.assertNotIn("SOUL.md", list_result.output)
        self.assertNotIn(".git", list_result.output)
        self.assertTrue(case_result.ok)
        self.assertIn("ok", case_result.output)

    def test_readonly_harness_rejects_non_allowlisted_commands(self):
        harness = gemma_readonly_tools.GemmaReadonlyToolHarness(allowed_roots=[str(ROOT)])
        result = harness.execute("run_readonly_command", {"command": "rm -rf /tmp/example"})
        self.assertFalse(result.ok)
        self.assertIn("not allowlisted", result.error)


def json_body_from_request(request):
    data = request.data
    if isinstance(data, bytes):
        data = data.decode("utf-8")
    import json

    return json.loads(data)


if __name__ == "__main__":
    unittest.main()
