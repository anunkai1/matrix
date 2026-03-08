import importlib.util
import os
import sys
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "src" / "telegram_bridge" / "runtime_config.py"
MODULE_DIR = MODULE_PATH.parent

spec = importlib.util.spec_from_file_location("telegram_bridge_runtime_config", MODULE_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError("Failed to load telegram runtime config module spec")
runtime_config = importlib.util.module_from_spec(spec)
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))
sys.modules[spec.name] = runtime_config
spec.loader.exec_module(runtime_config)


class RuntimeConfigTests(unittest.TestCase):
    def test_build_policy_watch_files_defaults_to_repo_policy_files(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            files = runtime_config.build_policy_watch_files()
        self.assertEqual(
            files,
            [
                str(ROOT / "AGENTS.md"),
                str(ROOT / "ARCHITECT_INSTRUCTION.md"),
                str(ROOT / "SERVER3_ARCHIVE.md"),
            ],
        )

    def test_build_policy_watch_files_honors_override(self):
        with mock.patch.dict(
            os.environ,
            {"TELEGRAM_POLICY_WATCH_FILES": "/tmp/a,/tmp/b"},
            clear=True,
        ):
            files = runtime_config.build_policy_watch_files()
        self.assertEqual(files, ["/tmp/a", "/tmp/b"])

    def test_load_config_defaults_executor_to_repo_executor_script(self):
        with mock.patch.dict(
            os.environ,
            {
                "TELEGRAM_BOT_TOKEN": "token",
                "TELEGRAM_ALLOWED_CHAT_IDS": "1,2",
            },
            clear=True,
        ):
            config = runtime_config.load_config()
        self.assertEqual(
            config.executor_cmd,
            [str(ROOT / "src" / "telegram_bridge" / "executor.sh")],
        )


if __name__ == "__main__":
    unittest.main()
