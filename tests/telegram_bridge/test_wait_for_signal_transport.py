import unittest
from pathlib import Path
from unittest import mock
from urllib.error import URLError

import sys

ROOT = Path(__file__).resolve().parents[2]
BRIDGE_DIR = ROOT / "src" / "telegram_bridge"
if str(BRIDGE_DIR) not in sys.path:
    sys.path.insert(0, str(BRIDGE_DIR))

import wait_for_signal_transport as wait_mod


class _FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


class _Response:
    def __init__(self, status: int = 200) -> None:
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class WaitForSignalTransportTests(unittest.TestCase):
    def test_build_health_url_appends_health(self):
        self.assertEqual(
            wait_mod.build_health_url("http://127.0.0.1:18797"),
            "http://127.0.0.1:18797/health",
        )
        self.assertEqual(
            wait_mod.build_health_url("http://127.0.0.1:18797/"),
            "http://127.0.0.1:18797/health",
        )
        self.assertEqual(
            wait_mod.build_health_url("http://127.0.0.1:18797/api"),
            "http://127.0.0.1:18797/api/health",
        )
        self.assertEqual(
            wait_mod.build_health_url("http://127.0.0.1:18797/health"),
            "http://127.0.0.1:18797/health",
        )

    def test_wait_succeeds_after_retries(self):
        clock = _FakeClock()
        opener = mock.Mock(side_effect=[URLError("down"), URLError("down"), _Response(204)])
        ready = wait_mod.wait_for_signal_transport(
            "http://127.0.0.1:18797/health",
            timeout_seconds=10,
            interval_seconds=1,
            opener=opener,
            sleep=clock.sleep,
            monotonic=clock.monotonic,
        )
        self.assertTrue(ready)
        self.assertEqual(opener.call_count, 3)

    def test_wait_times_out_when_health_never_recovers(self):
        clock = _FakeClock()
        opener = mock.Mock(side_effect=URLError("still down"))
        ready = wait_mod.wait_for_signal_transport(
            "http://127.0.0.1:18797/health",
            timeout_seconds=3,
            interval_seconds=1,
            opener=opener,
            sleep=clock.sleep,
            monotonic=clock.monotonic,
        )
        self.assertFalse(ready)
        self.assertGreaterEqual(opener.call_count, 3)


if __name__ == "__main__":
    unittest.main()
