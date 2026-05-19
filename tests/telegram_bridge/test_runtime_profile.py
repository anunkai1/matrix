import importlib.util
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "src" / "telegram_bridge" / "runtime_profile.py"
MODULE_DIR = MODULE_PATH.parent

spec = importlib.util.spec_from_file_location("telegram_bridge_runtime_profile", MODULE_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError("Failed to load telegram runtime profile module spec")
runtime_profile = importlib.util.module_from_spec(spec)
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))
sys.modules[spec.name] = runtime_profile
spec.loader.exec_module(runtime_profile)


class RuntimeProfileTests(unittest.TestCase):
    def test_extract_keyword_request_supports_expected_separators(self) -> None:
        self.assertEqual(
            runtime_profile.extract_server3_keyword_request("Server3 TV: open Firefox"),
            (True, "open Firefox"),
        )

    def test_apply_outbound_reply_prefix_normalizes_whatsapp_prefix(self) -> None:
        client = SimpleNamespace(channel_name="whatsapp")
        self.assertEqual(
            runtime_profile.apply_outbound_reply_prefix(client, "говорун: привет"),
            "Даю справку: привет",
        )
        self.assertEqual(
            runtime_profile.apply_outbound_reply_prefix(client, "Даю справку: привет"),
            "Даю справку: привет",
        )

    def test_start_command_message_uses_assistant_name(self) -> None:
        config = SimpleNamespace(assistant_name="HelperBot")
        self.assertIn("HelperBot", runtime_profile.start_command_message(config))

    def test_start_command_message_accepts_grouped_identity_config(self) -> None:
        config = SimpleNamespace(identity=SimpleNamespace(assistant_name="HelperBot"))
        self.assertIn("HelperBot", runtime_profile.start_command_message(config))

    def test_engine_progress_context_uses_recent_codex_model_when_unset(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            codex_home = Path(tmpdir) / ".codex"
            codex_home.mkdir()
            db_path = codex_home / "state_5.sqlite"
            connection = sqlite3.connect(db_path)
            try:
                connection.execute(
                    """
                    create table threads (
                        cwd text,
                        model text,
                        updated_at integer,
                        updated_at_ms integer
                    )
                    """
                )
                connection.execute(
                    "insert into threads (cwd, model, updated_at, updated_at_ms) values (?, ?, ?, ?)",
                    ("/runtime/mavali", "gpt-5.5", 1, 1000),
                )
                connection.commit()
            finally:
                connection.close()

            config = SimpleNamespace(codex_model="")
            with mock.patch.dict(
                os.environ,
                {"CODEX_HOME": str(codex_home), "TELEGRAM_RUNTIME_ROOT": "/runtime/mavali"},
                clear=False,
            ):
                self.assertEqual(
                    runtime_profile.build_engine_progress_context_label(config, "codex"),
                    "(codex | gpt-5.5)",
                )

    def test_mavali_eth_progress_context_includes_codex_model(self) -> None:
        config = SimpleNamespace(codex_model="")
        with mock.patch.object(
            runtime_profile,
            "_effective_codex_progress_model",
            return_value="gpt-5.5",
        ):
            self.assertEqual(
                runtime_profile.build_engine_progress_context_label(config, "mavali_eth"),
                "(mavali_eth | codex | gpt-5.5)",
            )

    def test_engine_progress_context_accepts_grouped_engine_config(self) -> None:
        config = SimpleNamespace(
            engines=SimpleNamespace(
                engine_plugin="gemma",
                gemma_provider="ollama_ssh",
                gemma_model="gemma4:26b",
                pi_provider="ollama",
                pi_model="qwen3-coder:30b",
            )
        )
        self.assertEqual(
            runtime_profile.build_engine_progress_context_label(config, None),
            "(ollama(s4) | gemma4:26b)",
        )

    def test_extract_sro_keyword_request_supports_expected_separators(self) -> None:
        self.assertEqual(
            runtime_profile.extract_sro_keyword_request("SRO: status"),
            (True, "status"),
        )
        self.assertEqual(
            runtime_profile.extract_sro_keyword_request("Runtime Observer - summary 24h"),
            (True, "summary 24h"),
        )

    def test_sro_prompt_references_wrapper(self) -> None:
        prompt = runtime_profile.build_sro_keyword_prompt("summary 24h")
        self.assertIn("runtime_observer_ctl.sh", prompt)
        self.assertIn("summary --hours N", prompt)

    def test_extract_youtube_link_request_detects_watch_urls(self) -> None:
        self.assertEqual(
            runtime_profile.extract_youtube_link_request("https://www.youtube.com/watch?v=yD5DFL3xPmo"),
            (True, "https://www.youtube.com/watch?v=yD5DFL3xPmo"),
        )
        self.assertEqual(
            runtime_profile.extract_youtube_link_request("full transcript https://youtu.be/yD5DFL3xPmo!"),
            (True, "https://youtu.be/yD5DFL3xPmo"),
        )
        self.assertEqual(
            runtime_profile.extract_youtube_link_request("watch this https://youtu.be/yD5DFL3xPmo!"),
            (False, ""),
        )
        self.assertEqual(
            runtime_profile.extract_youtube_link_request(
                "https://www.youtube.com/watch?v=yD5DFL3xPmo\nsummarise this"
            ),
            (True, "https://www.youtube.com/watch?v=yD5DFL3xPmo"),
        )

if __name__ == "__main__":
    unittest.main()
