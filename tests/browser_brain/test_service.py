from __future__ import annotations

import sys
import tempfile
import types
import unittest
from types import SimpleNamespace
from unittest import mock

from src.browser_brain.config import BrowserBrainConfig
from src.browser_brain.service import BrowserBrainError, BrowserBrainService


class FakePage:
    def __init__(self, url: str, title: str) -> None:
        self.url = url
        self._title = title

    def is_closed(self) -> bool:
        return False

    def title(self) -> str:
        return self._title


class FakeContext:
    def __init__(self, pages: list[FakePage]) -> None:
        self.pages = pages

    def new_page(self) -> FakePage:
        page = FakePage("about:blank", "")
        self.pages.append(page)
        return page


class FakeBrowserConnection:
    def __init__(self, contexts: list[FakeContext]) -> None:
        self.contexts = contexts
        self.close = mock.Mock()

    def is_connected(self) -> bool:
        return True


class FakePlaywrightHandle:
    def __init__(self, connection: FakeBrowserConnection) -> None:
        self.chromium = SimpleNamespace(
            connect_over_cdp=mock.Mock(return_value=connection),
            launch_persistent_context=mock.Mock(),
        )
        self.stop = mock.Mock()


class FakeSyncPlaywright:
    def __init__(self, handle: FakePlaywrightHandle) -> None:
        self._handle = handle

    def start(self) -> FakePlaywrightHandle:
        return self._handle


class BrowserBrainServiceTests(unittest.TestCase):
    def test_existing_session_mode_attaches_over_cdp_without_closing_user_browser(self) -> None:
        page = FakePage("https://x.com/home", "Home / X")
        context = FakeContext([page])
        connection = FakeBrowserConnection([context])
        playwright_handle = FakePlaywrightHandle(connection)
        fake_module = types.ModuleType("playwright.sync_api")
        fake_module.sync_playwright = lambda: FakeSyncPlaywright(playwright_handle)

        config = BrowserBrainConfig(
            connection_mode="existing_session",
            existing_session_cdp_url="http://127.0.0.1:9555",
        )
        service = BrowserBrainService(config)

        with mock.patch.dict(sys.modules, {"playwright.sync_api": fake_module}):
            status = service.start({})
            self.assertTrue(status["running"])
            self.assertEqual(status["connection_mode"], "existing_session")
            self.assertEqual(status["cdp_endpoint_url"], "http://127.0.0.1:9555")
            self.assertEqual(status["tabs"][0]["url"], "https://x.com/home")
            playwright_handle.chromium.connect_over_cdp.assert_called_once_with("http://127.0.0.1:9555")

            stop_result = service.stop({})
            self.assertFalse(stop_result["running"])
            connection.close.assert_not_called()
            playwright_handle.stop.assert_called_once()

    def test_act_upload_sets_input_files_on_resolved_element(self) -> None:
        config = BrowserBrainConfig()
        service = BrowserBrainService(config)
        page = object()
        element = mock.Mock()

        with tempfile.NamedTemporaryFile(suffix=".mp4") as handle:
            upload_path = handle.name
            with (
                mock.patch.object(service, "_page_for_payload", return_value=page),
                mock.patch.object(service, "_resolve_element", return_value=element),
                mock.patch.object(service, "_tab_payload", return_value={"tab_id": "tab-1", "url": "https://x.com/compose"}),
                mock.patch.object(service, "_tab_id", return_value="tab-1"),
                mock.patch.object(service, "_log_action"),
            ):
                result = service.act_upload(
                    {"tab_id": "tab-1", "snapshot_id": "snap-1", "ref": "el-0007", "path": upload_path}
                )

        element.set_input_files.assert_called_once_with(upload_path, timeout=config.action_timeout_ms)
        self.assertTrue(result["ok"])
        self.assertEqual(result["files"], [upload_path])

    def test_act_upload_rejects_missing_file(self) -> None:
        config = BrowserBrainConfig()
        service = BrowserBrainService(config)

        with self.assertRaises(BrowserBrainError) as ctx:
            service.act_upload({"tab_id": "tab-1", "snapshot_id": "snap-1", "ref": "el-0007", "path": "/tmp/does-not-exist.mp4"})

        self.assertEqual(ctx.exception.code, "file_not_found")


if __name__ == "__main__":
    unittest.main()
