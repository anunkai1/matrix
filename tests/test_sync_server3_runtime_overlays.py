import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "ops" / "runtime_overlays" / "sync_server3_runtime_overlays.py"

spec = importlib.util.spec_from_file_location("sync_server3_runtime_overlays", MODULE_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError("Failed to load overlay sync module spec")
overlay_sync = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = overlay_sync
spec.loader.exec_module(overlay_sync)


class OverlaySyncTests(unittest.TestCase):
    def test_install_runtime_skips_when_runtime_src_resolves_to_shared_core(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            shared_root = root / "shared"
            shared_src = shared_root / "src" / "telegram_bridge"
            shared_src.mkdir(parents=True)
            shared_main = shared_src / "main.py"
            shared_main.write_text("ORIGINAL\n", encoding="utf-8")

            runtime_root = root / "tankbot"
            runtime_root.mkdir()
            os.symlink(shared_root / "src", runtime_root / "src")

            runtime = overlay_sync.OverlayRuntime(
                name="Tank",
                owner_user="tank",
                runtime_root=runtime_root,
                shared_core_root=shared_root,
            )
            installed = overlay_sync.install_runtime(runtime)
            self.assertEqual(installed, [])
            self.assertEqual(shared_main.read_text(encoding="utf-8"), "ORIGINAL\n")

    def test_install_runtime_writes_expected_overlay_shims(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            shared_root = root / "shared"
            shared_src = shared_root / "src" / "telegram_bridge"
            shared_src.mkdir(parents=True)

            runtime_root = root / "oraclebot"
            target_dir = runtime_root / "src" / "telegram_bridge"
            target_dir.mkdir(parents=True)
            (target_dir / "wait_for_signal_transport.py").write_text("OLD\n", encoding="utf-8")

            runtime = overlay_sync.OverlayRuntime(
                name="Oracle bridge",
                owner_user="oracle",
                runtime_root=runtime_root,
                shared_core_root=shared_root,
            )
            fake_owner = SimpleNamespace(pw_uid=os.getuid(), pw_gid=os.getgid())
            with mock.patch.object(overlay_sync.pwd, "getpwnam", return_value=fake_owner), mock.patch.object(
                overlay_sync.os, "chown"
            ):
                installed = overlay_sync.install_runtime(runtime)

            self.assertEqual(
                installed,
                [
                    str(target_dir / "main.py"),
                    str(target_dir / "executor.sh"),
                    str(target_dir / "wait_for_signal_transport.py"),
                ],
            )
            self.assertIn("Server3 shared-core overlay shim.", (target_dir / "main.py").read_text(encoding="utf-8"))
            self.assertIn("TELEGRAM_RUNTIME_ROOT", (target_dir / "executor.sh").read_text(encoding="utf-8"))
            self.assertIn(
                "runpy.run_path",
                (target_dir / "wait_for_signal_transport.py").read_text(encoding="utf-8"),
            )


if __name__ == "__main__":
    unittest.main()
