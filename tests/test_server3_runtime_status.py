from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "ops" / "server3_runtime_status.py"
MANIFEST_PATH = ROOT / "infra" / "server3-runtime-manifest.json"

SPEC = spec_from_file_location("server3_runtime_status", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
server3_runtime_status = module_from_spec(SPEC)
sys.modules[SPEC.name] = server3_runtime_status
SPEC.loader.exec_module(server3_runtime_status)


class Server3RuntimeStatusTests(unittest.TestCase):
    def test_manifest_covers_major_server3_units(self) -> None:
        runtimes = server3_runtime_status.load_manifest(MANIFEST_PATH)
        units = {
            unit.name
            for runtime in runtimes
            for unit in runtime.units
        }
        self.assertTrue(
            {
                "telegram-architect-bridge.service",
                "telegram-tank-bridge.service",
                "whatsapp-govorun-bridge.service",
                "govorun-whatsapp-bridge.service",
                "signal-oracle-bridge.service",
                "oracle-signal-bridge.service",
                "nordvpnd.service",
                "tailscaled.service",
                "server3-runtime-observer.timer",
                "server3-chat-routing-contract-check.timer",
                "server3-monthly-apt-upgrade.timer",
                "lightdm.service",
            }.issubset(units)
        )

    def test_evaluate_runtime_accepts_expected_inactive_unit(self) -> None:
        runtime = server3_runtime_status.RuntimeSpec(
            name="UI layer",
            category="optional",
            purpose="Desktop UI",
            expected_default_state="inactive",
            dependencies=[],
            owner_user=None,
            notes=[],
            units=[
                server3_runtime_status.UnitSpec(
                    name="lightdm.service",
                    kind="service",
                    expected_state="inactive",
                )
            ],
        )
        statuses = {
            "lightdm.service": server3_runtime_status.UnitStatus(
                name="lightdm.service",
                load_state="loaded",
                active_state="inactive",
                sub_state="dead",
                unit_file_state="disabled",
                available=True,
                matches_expected=False,
                issues=[],
            )
        }

        evaluated = server3_runtime_status.evaluate_runtime(runtime, statuses)

        self.assertTrue(evaluated.matches_expected)
        self.assertEqual(evaluated.live_state, "inactive")

    def test_evaluate_runtime_flags_unexpected_inactive_service(self) -> None:
        runtime = server3_runtime_status.RuntimeSpec(
            name="Architect",
            category="primary",
            purpose="Main runtime",
            expected_default_state="active",
            dependencies=[],
            owner_user="architect",
            notes=[],
            units=[
                server3_runtime_status.UnitSpec(
                    name="telegram-architect-bridge.service",
                    kind="service",
                    expected_state="active",
                )
            ],
        )
        statuses = {
            "telegram-architect-bridge.service": server3_runtime_status.UnitStatus(
                name="telegram-architect-bridge.service",
                load_state="loaded",
                active_state="inactive",
                sub_state="dead",
                unit_file_state="enabled",
                available=True,
                matches_expected=False,
                issues=[],
            )
        }

        evaluated = server3_runtime_status.evaluate_runtime(runtime, statuses)

        self.assertFalse(evaluated.matches_expected)
        self.assertEqual(evaluated.units[0].issues, ["expected active, got inactive"])

    def test_evaluate_runtime_accepts_active_running_timer_when_waiting_expected(self) -> None:
        runtime = server3_runtime_status.RuntimeSpec(
            name="Mavali ETH",
            category="secondary",
            purpose="Receipt monitor timer",
            expected_default_state="active",
            dependencies=[],
            owner_user="mavali_eth",
            notes=[],
            units=[
                server3_runtime_status.UnitSpec(
                    name="mavali-eth-receipt-monitor.timer",
                    kind="timer",
                    expected_state="active",
                    expected_substate="waiting",
                )
            ],
        )
        statuses = {
            "mavali-eth-receipt-monitor.timer": server3_runtime_status.UnitStatus(
                name="mavali-eth-receipt-monitor.timer",
                load_state="loaded",
                active_state="active",
                sub_state="running",
                unit_file_state="enabled",
                available=True,
                matches_expected=False,
                issues=[],
            )
        }

        evaluated = server3_runtime_status.evaluate_runtime(runtime, statuses)

        self.assertTrue(evaluated.matches_expected)
        self.assertEqual(evaluated.live_state, "active")

    def test_collect_runtime_statuses_queries_each_unit_once(self) -> None:
        runtimes = [
            server3_runtime_status.RuntimeSpec(
                name="Runtime A",
                category="primary",
                purpose="First runtime",
                expected_default_state="active",
                dependencies=[],
                owner_user=None,
                notes=[],
                units=[
                    server3_runtime_status.UnitSpec(
                        name="shared.service",
                        kind="service",
                        expected_state="active",
                    )
                ],
            ),
            server3_runtime_status.RuntimeSpec(
                name="Runtime B",
                category="secondary",
                purpose="Second runtime",
                expected_default_state="active",
                dependencies=[],
                owner_user=None,
                notes=[],
                units=[
                    server3_runtime_status.UnitSpec(
                        name="shared.service",
                        kind="service",
                        expected_state="active",
                    )
                ],
            ),
        ]
        status = server3_runtime_status.UnitStatus(
            name="shared.service",
            load_state="loaded",
            active_state="active",
            sub_state="running",
            unit_file_state="enabled",
            available=True,
            matches_expected=False,
            issues=[],
        )

        with unittest.mock.patch.object(
            server3_runtime_status,
            "query_unit_status",
            return_value=status,
        ) as query:
            evaluated = server3_runtime_status.collect_runtime_statuses(runtimes)

        self.assertEqual(len(evaluated), 2)
        query.assert_called_once_with("shared.service")


if __name__ == "__main__":
    unittest.main()
