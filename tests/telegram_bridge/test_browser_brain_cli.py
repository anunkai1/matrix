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


if __name__ == "__main__":
    unittest.main()
