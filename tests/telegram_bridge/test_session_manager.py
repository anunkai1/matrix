import os
import sys
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
BRIDGE_DIR = ROOT / "src" / "telegram_bridge"
if str(BRIDGE_DIR) not in sys.path:
    sys.path.insert(0, str(BRIDGE_DIR))

import session_manager


class SessionManagerRestartUnitTests(unittest.TestCase):
    def test_build_restart_unit_name_prefers_explicit_restart_env(self):
        with mock.patch.dict(
            os.environ,
            {
                "TELEGRAM_RESTART_UNIT": "telegram-mavali-eth-bridge.service",
                "UNIT_NAME": "telegram-architect-bridge.service",
            },
            clear=False,
        ):
            self.assertEqual(
                session_manager.build_restart_unit_name(),
                "telegram-mavali-eth-bridge.service",
            )

    def test_build_restart_unit_name_falls_back_to_unit_name_env(self):
        with mock.patch.dict(
            os.environ,
            {"UNIT_NAME": "telegram-mavali-eth-bridge.service"},
            clear=False,
        ):
            os.environ.pop("TELEGRAM_RESTART_UNIT", None)
            self.assertEqual(
                session_manager.build_restart_unit_name(),
                "telegram-mavali-eth-bridge.service",
            )
