import importlib.util
import sys
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "ops" / "browser_brain" / "browser_brain_ctl.py"

spec = importlib.util.spec_from_file_location("browser_brain_ctl", MODULE_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError("Failed to load browser brain CLI module spec")
browser_brain_ctl = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = browser_brain_ctl
spec.loader.exec_module(browser_brain_ctl)


class BrowserBrainCLITests(unittest.TestCase):
    @mock.patch.object(browser_brain_ctl, "_print")
    @mock.patch.object(browser_brain_ctl, "_request")
    @mock.patch.object(browser_brain_ctl, "_ensure_service")
    def test_open_command_calls_tabs_open_route(self, ensure_service, request, printer) -> None:
        request.return_value = {"tab": {"tab_id": "tab-1"}}

        exit_code = browser_brain_ctl.main(["open", "--url", "https://example.com"])

        self.assertEqual(exit_code, 0)
        ensure_service.assert_called_once_with(browser_brain_ctl.DEFAULT_SERVICE)
        request.assert_called_once_with(
            browser_brain_ctl.DEFAULT_BASE_URL,
            "POST",
            "/v1/tabs/open",
            {"url": "https://example.com"},
        )
        printer.assert_called_once_with({"tab": {"tab_id": "tab-1"}})

    @mock.patch.object(browser_brain_ctl, "_print")
    @mock.patch.object(browser_brain_ctl, "_request")
    @mock.patch.object(browser_brain_ctl, "_ensure_service")
    def test_status_command_skips_service_start(self, ensure_service, request, printer) -> None:
        request.return_value = {"running": False}

        exit_code = browser_brain_ctl.main(["status"])

        self.assertEqual(exit_code, 0)
        ensure_service.assert_not_called()
        request.assert_called_once_with(browser_brain_ctl.DEFAULT_BASE_URL, "GET", "/v1/status")
        printer.assert_called_once_with({"running": False})

    @mock.patch.object(browser_brain_ctl, "_print")
    @mock.patch.object(browser_brain_ctl, "_request")
    @mock.patch.object(browser_brain_ctl, "_ensure_service")
    def test_safe_action_commands_call_expected_routes(self, ensure_service, request, printer) -> None:
        request.return_value = {"ok": True}

        exit_code = browser_brain_ctl.main(["hover", "--tab-id", "tab-1", "--snapshot-id", "snap-1", "--ref", "el-1"])
        self.assertEqual(exit_code, 0)
        request.assert_called_with(
            browser_brain_ctl.DEFAULT_BASE_URL,
            "POST",
            "/v1/act/hover",
            {"tab_id": "tab-1", "snapshot_id": "snap-1", "ref": "el-1"},
        )

        exit_code = browser_brain_ctl.main(
            ["select", "--tab-id", "tab-1", "--snapshot-id", "snap-1", "--ref", "el-2", "--value", "one"]
        )
        self.assertEqual(exit_code, 0)
        request.assert_called_with(
            browser_brain_ctl.DEFAULT_BASE_URL,
            "POST",
            "/v1/act/select",
            {"tab_id": "tab-1", "snapshot_id": "snap-1", "ref": "el-2", "values": ["one"]},
        )

        self.assertEqual(ensure_service.call_count, 2)
        self.assertEqual(printer.call_count, 2)

    @mock.patch.object(browser_brain_ctl, "_print")
    @mock.patch.object(browser_brain_ctl, "_request")
    @mock.patch.object(browser_brain_ctl, "_ensure_service")
    def test_read_only_browser_diagnostics_call_expected_routes(self, ensure_service, request, printer) -> None:
        request.return_value = {"messages": []}

        exit_code = browser_brain_ctl.main(["console", "--tab-id", "tab-1", "--limit", "5"])
        self.assertEqual(exit_code, 0)
        request.assert_called_with(
            browser_brain_ctl.DEFAULT_BASE_URL,
            "POST",
            "/v1/console",
            {"tab_id": "tab-1", "limit": 5},
        )

        exit_code = browser_brain_ctl.main(["network", "--tab-id", "tab-1", "--limit", "5"])
        self.assertEqual(exit_code, 0)
        request.assert_called_with(
            browser_brain_ctl.DEFAULT_BASE_URL,
            "POST",
            "/v1/network",
            {"tab_id": "tab-1", "limit": 5},
        )

        exit_code = browser_brain_ctl.main(["clipboard-read", "--tab-id", "tab-1"])
        self.assertEqual(exit_code, 0)
        request.assert_called_with(
            browser_brain_ctl.DEFAULT_BASE_URL,
            "POST",
            "/v1/clipboard/read",
            {"tab_id": "tab-1"},
        )

        self.assertEqual(ensure_service.call_count, 3)
        self.assertEqual(printer.call_count, 3)


if __name__ == "__main__":
    unittest.main()
