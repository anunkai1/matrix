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

    def test_build_policy_watch_files_uses_runtime_root_agents_and_shared_docs(self):
        with mock.patch.dict(
            os.environ,
            {
                "TELEGRAM_RUNTIME_ROOT": "/srv/runtime-overlay",
                "TELEGRAM_SHARED_CORE_ROOT": str(ROOT),
            },
            clear=True,
        ):
            files = runtime_config.build_policy_watch_files()
        self.assertEqual(
            files,
            [
                "/srv/runtime-overlay/AGENTS.md",
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

    def test_load_config_defaults_affective_runtime_to_disabled(self):
        with mock.patch.dict(
            os.environ,
            {
                "TELEGRAM_BOT_TOKEN": "token",
                "TELEGRAM_ALLOWED_CHAT_IDS": "1",
                "TELEGRAM_BRIDGE_STATE_DIR": "/tmp/runtime-config-affective",
            },
            clear=True,
        ):
            config = runtime_config.load_config()
        self.assertFalse(config.affective_runtime_enabled)
        self.assertEqual(
            config.affective_runtime_db_path,
            "/tmp/runtime-config-affective/affective_state.sqlite3",
        )
        self.assertEqual(config.affective_runtime_ping_target, "1.1.1.1")

    def test_load_config_reads_affective_runtime_overrides(self):
        with mock.patch.dict(
            os.environ,
            {
                "TELEGRAM_BOT_TOKEN": "token",
                "TELEGRAM_ALLOWED_CHAT_IDS": "1",
                "TELEGRAM_AFFECTIVE_RUNTIME_ENABLED": "true",
                "TELEGRAM_AFFECTIVE_RUNTIME_DB_PATH": "/var/lib/trinitybot/affective.sqlite3",
                "TELEGRAM_AFFECTIVE_RUNTIME_PING_TARGET": "",
            },
            clear=True,
        ):
            config = runtime_config.load_config()
        self.assertTrue(config.affective_runtime_enabled)
        self.assertEqual(
            config.affective_runtime_db_path,
            "/var/lib/trinitybot/affective.sqlite3",
        )
        self.assertEqual(config.affective_runtime_ping_target, "")

    def test_load_config_reads_diary_overrides(self):
        with mock.patch.dict(
            os.environ,
            {
                "TELEGRAM_BOT_TOKEN": "token",
                "TELEGRAM_ALLOWED_CHAT_IDS": "1",
                "TELEGRAM_DIARY_MODE_ENABLED": "true",
                "TELEGRAM_DIARY_CAPTURE_QUIET_WINDOW_SECONDS": "42",
                "TELEGRAM_DIARY_TIMEZONE": "Australia/Brisbane",
                "TELEGRAM_DIARY_LOCAL_ROOT": "/var/lib/diary",
                "TELEGRAM_DIARY_NEXTCLOUD_ENABLED": "true",
                "TELEGRAM_DIARY_NEXTCLOUD_BASE_URL": "https://nextcloud.local",
                "TELEGRAM_DIARY_NEXTCLOUD_USERNAME": "DiaryUser",
                "TELEGRAM_DIARY_NEXTCLOUD_APP_PASSWORD": "secret",
                "TELEGRAM_DIARY_NEXTCLOUD_REMOTE_ROOT": "/Travel Diary",
            },
            clear=True,
        ):
            config = runtime_config.load_config()
        self.assertTrue(config.diary_mode_enabled)
        self.assertEqual(config.diary_capture_quiet_window_seconds, 42)
        self.assertEqual(config.diary_local_root, "/var/lib/diary")
        self.assertTrue(config.diary_nextcloud_enabled)
        self.assertEqual(config.diary_nextcloud_base_url, "https://nextcloud.local")
        self.assertEqual(config.diary_nextcloud_username, "DiaryUser")
        self.assertEqual(config.diary_nextcloud_app_password, "secret")
        self.assertEqual(config.diary_nextcloud_remote_root, "/Travel Diary")


if __name__ == "__main__":
    unittest.main()
