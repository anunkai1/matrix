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
        self.context = mock.Mock()

    def is_closed(self) -> bool:
        return False

    def title(self) -> str:
        return self._title

    def evaluate(self, _script: str) -> str:
        return "clipboard text"

    def on(self, _event, _callback) -> None:
        return None


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

    def test_snapshot_includes_aria_snapshot_and_locator_hints(self) -> None:
        service = BrowserBrainService(BrowserBrainConfig())
        frame = mock.Mock()
        frame.url = "https://example.com"
        frame.name = ""
        frame.evaluate.return_value = [
            {
                "tag": "button",
                "role": "button",
                "name": "Submit",
                "text": "Submit",
                "visible": True,
                "enabled": True,
                "input_type": "",
                "placeholder": "",
                "title": "",
                "href": "",
                "aria_label": "",
                "content_editable": False,
            }
        ]
        page = mock.Mock()
        page.frames = [frame]
        page.locator.return_value.aria_snapshot.return_value = "- button \"Submit\""

        snapshot = service._build_snapshot(page)

        element = snapshot.elements["el-0001"]
        self.assertEqual(snapshot.aria_snapshot, "- button \"Submit\"")
        self.assertEqual(element.locator_kind, "role")
        self.assertEqual(element.locator_value, "button:Submit")
        self.assertIn("role=button", element.locator_selector)

    def test_find_element_prefers_unique_playwright_locator(self) -> None:
        service = BrowserBrainService(BrowserBrainConfig(action_timeout_ms=123))
        element = SimpleNamespace(role="button", name="Submit", frame_id="https://example.com", aria_label="", placeholder="", title="", text="", tag="button")
        locator = mock.Mock()
        handle = object()
        locator.count.return_value = 1
        locator.element_handle.return_value = handle
        frame = mock.Mock()
        frame.url = "https://example.com"
        frame.get_by_role.return_value = locator
        page = mock.Mock()
        page.frames = [frame]

        self.assertIs(service._find_element(page, element), handle)
        frame.get_by_role.assert_called_once_with("button", name="Submit", exact=True)
        locator.element_handle.assert_called_once_with(timeout=123)

    def test_navigation_policy_blocks_untrusted_origin(self) -> None:
        service = BrowserBrainService(
            BrowserBrainConfig(navigation_allowed_origins=("https://example.com",), navigation_blocked_origins=())
        )

        service._validate_navigation_url("https://example.com/path")
        with self.assertRaises(BrowserBrainError) as ctx:
            service._validate_navigation_url("https://evil.example/path")

        self.assertEqual(ctx.exception.code, "navigation_blocked")
        self.assertEqual(ctx.exception.status, 403)

    def test_safe_actions_call_playwright_element_methods(self) -> None:
        service = BrowserBrainService(BrowserBrainConfig(action_timeout_ms=456))
        page = object()
        element = mock.Mock()
        element.select_option.return_value = ["one"]

        with (
            mock.patch.object(service, "_page_for_payload", return_value=page),
            mock.patch.object(service, "_resolve_element", return_value=element),
            mock.patch.object(service, "_tab_payload", return_value={"tab_id": "tab-1"}),
            mock.patch.object(service, "_tab_id", return_value="tab-1"),
            mock.patch.object(service, "_log_action"),
        ):
            hover_result = service.act_hover({"tab_id": "tab-1", "snapshot_id": "snap-1", "ref": "el-0001"})
            select_result = service.act_select(
                {"tab_id": "tab-1", "snapshot_id": "snap-1", "ref": "el-0002", "values": ["one"]}
            )

        element.hover.assert_called_once_with(timeout=456)
        element.select_option.assert_called_once_with(["one"], timeout=456)
        self.assertTrue(hover_result["ok"])
        self.assertTrue(select_result["ok"])

    def test_wait_uses_playwright_arg_keyword(self) -> None:
        service = BrowserBrainService(BrowserBrainConfig(action_timeout_ms=789))
        page = mock.Mock()

        with (
            mock.patch.object(service, "_page_for_payload", return_value=page),
            mock.patch.object(service, "_tab_payload", return_value={"tab_id": "tab-1"}),
            mock.patch.object(service, "_tab_id", return_value="tab-1"),
            mock.patch.object(service, "_log_action"),
        ):
            result = service.wait({"tab_id": "tab-1", "condition": "text", "value": "Ready"})

        page.wait_for_function.assert_called_once_with(
            "(expected) => document.body && document.body.innerText && document.body.innerText.includes(expected)",
            arg="Ready",
            timeout=789,
        )
        self.assertTrue(result["ok"])

    def test_dialog_handle_arms_next_dialog_policy(self) -> None:
        service = BrowserBrainService(BrowserBrainConfig())
        page = FakePage("https://example.com", "Example")

        with (
            mock.patch.object(service, "_page_for_payload", return_value=page),
            mock.patch.object(service, "_log_action"),
        ):
            result = service.dialog_handle({"tab_id": "tab-1", "accept": False})

        self.assertTrue(result["armed"])
        self.assertFalse(service._next_dialog_policy_by_tab[result["tab"]["tab_id"]]["accept"])

    def test_clipboard_read_grants_permission_and_reads_text(self) -> None:
        service = BrowserBrainService(BrowserBrainConfig())
        page = FakePage("https://chatgpt.com/c/123", "ChatGPT")

        with (
            mock.patch.object(service, "_page_for_payload", return_value=page),
            mock.patch.object(service, "_tab_payload", return_value={"tab_id": "tab-1", "url": page.url}),
            mock.patch.object(service, "_log_action"),
        ):
            result = service.clipboard_read({"tab_id": "tab-1"})

        page.context.grant_permissions.assert_called_once_with(
            ["clipboard-read", "clipboard-write"],
            origin="https://chatgpt.com",
        )
        self.assertEqual(result["text"], "clipboard text")
        self.assertEqual(result["length"], len("clipboard text"))


if __name__ == "__main__":
    unittest.main()
