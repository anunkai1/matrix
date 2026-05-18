import importlib.util
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "ops" / "server3_control_plane" / "serve.py"

spec = importlib.util.spec_from_file_location("server3_control_plane_serve", MODULE_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError("Failed to load server3 control plane serve module spec")
serve = importlib.util.module_from_spec(spec)
spec.loader.exec_module(serve)


class Server3ControlPlaneServeTests(unittest.TestCase):
    def test_snapshot_is_stale_for_missing_generated_at(self):
        self.assertTrue(serve.snapshot_is_stale({}))

    def test_snapshot_is_stale_for_old_snapshot(self):
        now = datetime.now(serve.DEFAULT_TZ)
        old_snapshot = {
            "generatedAt": (now - timedelta(seconds=serve.DEFAULT_SNAPSHOT_MAX_AGE_SECONDS + 1)).isoformat()
        }
        self.assertTrue(serve.snapshot_is_stale(old_snapshot, now=now))

    def test_snapshot_is_not_stale_for_recent_snapshot(self):
        now = datetime.now(serve.DEFAULT_TZ)
        fresh_snapshot = {
            "generatedAt": (now - timedelta(seconds=serve.DEFAULT_SNAPSHOT_MAX_AGE_SECONDS - 5)).isoformat()
        }
        self.assertFalse(serve.snapshot_is_stale(fresh_snapshot, now=now))

    def test_load_snapshot_with_refresh_returns_fresh_snapshot_without_refresh(self):
        fresh_snapshot = {"generatedAt": datetime.now(serve.DEFAULT_TZ).isoformat(), "value": "fresh"}
        with mock.patch.object(serve, "load_snapshot", return_value=fresh_snapshot) as load_snapshot:
            with mock.patch.object(serve, "refresh_snapshot") as refresh_snapshot:
                payload = serve.load_snapshot_with_refresh()
        self.assertEqual(payload, fresh_snapshot)
        load_snapshot.assert_called_once_with()
        refresh_snapshot.assert_not_called()

    def test_load_snapshot_with_refresh_refreshes_stale_snapshot(self):
        stale_snapshot = {"generatedAt": "2026-01-01T00:00:00+10:00", "value": "stale"}
        refreshed_snapshot = {"generatedAt": datetime.now(serve.DEFAULT_TZ).isoformat(), "value": "fresh"}
        with mock.patch.object(serve, "load_snapshot", return_value=stale_snapshot) as load_snapshot:
            with mock.patch.object(serve, "refresh_snapshot", return_value=refreshed_snapshot) as refresh_snapshot:
                payload = serve.load_snapshot_with_refresh()
        self.assertEqual(payload, refreshed_snapshot)
        load_snapshot.assert_called_once_with()
        refresh_snapshot.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
