from __future__ import annotations

import sys
import types
import unittest
from types import SimpleNamespace
from unittest import mock

from src.browser_brain.config import BrowserBrainConfig
from src.browser_brain.service import BrowserBrainService


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


if __name__ == "__main__":
    unittest.main()
