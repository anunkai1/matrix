from pathlib import Path
import unittest

from src.browser_brain.config import BrowserBrainConfig


class BrowserBrainConfigTests(unittest.TestCase):
    def test_from_env_overrides_defaults(self) -> None:
        config = BrowserBrainConfig.from_env(
            {
                "BROWSER_BRAIN_HOST": "127.0.0.2",
                "BROWSER_BRAIN_PORT": "49000",
                "BROWSER_BRAIN_BROWSER_EXECUTABLE": "/opt/brave",
                "BROWSER_BRAIN_STATE_DIR": "/tmp/browser-brain",
                "BROWSER_BRAIN_PROFILE_DIR": "/tmp/browser-brain/profile-alt",
                "BROWSER_BRAIN_CAPTURE_DIR": "/tmp/browser-brain/captures-alt",
                "BROWSER_BRAIN_REMOTE_DEBUGGING_PORT": "9333",
                "BROWSER_BRAIN_STARTUP_TIMEOUT_SECONDS": "11",
                "BROWSER_BRAIN_ACTION_TIMEOUT_MS": "8001",
                "BROWSER_BRAIN_SCREENSHOT_TTL_HOURS": "3",
                "BROWSER_BRAIN_HEADLESS": "false",
                "BROWSER_BRAIN_LOG_ACTIONS": "0",
            }
        )

        self.assertEqual(config.host, "127.0.0.2")
        self.assertEqual(config.port, 49000)
        self.assertEqual(config.browser_executable, "/opt/brave")
        self.assertEqual(config.state_dir, Path("/tmp/browser-brain"))
        self.assertEqual(config.browser_user_data_dir, Path("/tmp/browser-brain/profile-alt"))
        self.assertEqual(config.capture_dir, Path("/tmp/browser-brain/captures-alt"))
        self.assertEqual(config.remote_debugging_port, 9333)
        self.assertEqual(config.startup_timeout_seconds, 11)
        self.assertEqual(config.action_timeout_ms, 8001)
        self.assertEqual(config.screenshot_ttl_hours, 3)
        self.assertFalse(config.headless)
        self.assertFalse(config.log_actions)


if __name__ == "__main__":
    unittest.main()
