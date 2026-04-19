from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "ops" / "signaltube_ask.py"
SPEC = importlib.util.spec_from_file_location("signaltube_ask", MODULE_PATH)
signaltube_ask = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = signaltube_ask
assert SPEC.loader is not None
SPEC.loader.exec_module(signaltube_ask)


class SignalTubeAskTests(unittest.TestCase):
    def test_build_scan_plan_extracts_initial_request(self) -> None:
        plan = signaltube_ask.build_scan_plan("I want to see some videos about the Iran war", {})

        self.assertEqual(plan["focus"], "Iran war")
        self.assertFalse(plan["remove_mainstream"])
        self.assertIn("Iran war latest analysis", plan["queries"])

    def test_build_scan_plan_refines_previous_request(self) -> None:
        previous = signaltube_ask.build_scan_plan("I want to see some videos about the Iran war", {})

        plan = signaltube_ask.build_scan_plan("That's too much mainstream news, remove mainstream news", previous)

        self.assertEqual(plan["focus"], "Iran war")
        self.assertTrue(plan["remove_mainstream"])
        self.assertIn("Iran war independent analysis", plan["queries"])

    def test_build_scan_plan_adds_viewpoint_lenses(self) -> None:
        previous = signaltube_ask.build_scan_plan("I want to see some videos about the Iran war", {})

        plan = signaltube_ask.build_scan_plan("Give me sources that are Iran aligned or China aligned", previous)

        self.assertEqual(plan["focus"], "Iran war")
        self.assertEqual(plan["viewpoints"], ["china", "iran"])
        self.assertIn("Iran war chinese perspective", plan["queries"])
        self.assertIn("Iran war iranian perspective", plan["queries"])


if __name__ == "__main__":
    unittest.main()
