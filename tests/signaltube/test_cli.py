from __future__ import annotations

import sys
import tempfile
import unittest
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "ops" / "signaltube_lab.py"

SPEC = spec_from_file_location("signaltube_lab_cli", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
signaltube_lab_cli = module_from_spec(SPEC)
sys.modules[SPEC.name] = signaltube_lab_cli
SPEC.loader.exec_module(signaltube_lab_cli)


class SignalTubeCliTests(unittest.TestCase):
    def test_scheduled_collect_uses_configured_topics_and_writes_feed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "signaltube.sqlite"
            html_path = Path(tmp) / "feed.html"
            store = signaltube_lab_cli.SignalTubeStore(db_path)
            store.init()
            store.upsert_topic("latest space videos", max_candidates=12)

            snapshot = {
                "elements": [
                    {"name": "Sign in", "href": "https://accounts.google.com/"},
                    {
                        "name": "Latest space telescope discovery",
                        "href": "https://www.youtube.com/watch?v=abcDEF_1234",
                    },
                ]
            }
            with mock.patch.object(signaltube_lab_cli.BrowserBrainClient, "open_search_snapshot", return_value=snapshot):
                exit_code = signaltube_lab_cli.main(
                    [
                        "--db",
                        str(db_path),
                        "--html",
                        str(html_path),
                        "scheduled-collect",
                        "--skip-youtube-metadata",
                    ]
                )

            self.assertEqual(exit_code, 0)
            self.assertTrue(html_path.exists())
            body = html_path.read_text(encoding="utf-8")
            self.assertIn("Latest space telescope discovery", body)

    def test_feedback_command_stores_signal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "signaltube.sqlite"

            exit_code = signaltube_lab_cli.main(
                [
                    "--db",
                    str(db_path),
                    "feedback",
                    "--topic",
                    "latest space videos",
                    "--video-id",
                    "abcDEF_1234",
                    "--signal",
                    "save",
                ]
            )

            self.assertEqual(exit_code, 0)
            store = signaltube_lab_cli.SignalTubeStore(db_path)
            events = store.load_feedback_events(topic="latest space videos")
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]["signal"], "save")

    def test_channels_block_command_stores_blocked_channel(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "signaltube.sqlite"

            exit_code = signaltube_lab_cli.main(
                [
                    "--db",
                    str(db_path),
                    "channels",
                    "block",
                    "--channel",
                    "Space Channel",
                ]
            )

            self.assertEqual(exit_code, 0)
            store = signaltube_lab_cli.SignalTubeStore(db_path)
            blocked = store.load_blocked_channels()
            self.assertEqual(blocked, {"space channel"})

    def test_videos_seen_command_stores_seen_video(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "signaltube.sqlite"

            exit_code = signaltube_lab_cli.main(
                [
                    "--db",
                    str(db_path),
                    "videos",
                    "seen",
                    "--video-id",
                    "abcDEF_1234",
                ]
            )

            self.assertEqual(exit_code, 0)
            store = signaltube_lab_cli.SignalTubeStore(db_path)
            seen = store.load_seen_video_ids()
            self.assertEqual(seen, {"abcDEF_1234"})

    def test_publish_command_invokes_filegator_publish(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            html_path = Path(tmp) / "feed.html"
            html_path.write_text("<html></html>", encoding="utf-8")

            with mock.patch.object(
                signaltube_lab_cli, "publish_html", return_value="https://mavali.top/projects/SignalTube/index.html"
            ) as publish_html:
                exit_code = signaltube_lab_cli.main(
                    [
                        "--html",
                        str(html_path),
                        "publish",
                        "--username",
                        "user1",
                        "--password",
                        "secret",
                    ]
                )

            self.assertEqual(exit_code, 0)
            publish_html.assert_called_once()

    def test_render_publishes_when_publish_env_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "signaltube.sqlite"
            html_path = Path(tmp) / "feed.html"
            store = signaltube_lab_cli.SignalTubeStore(db_path)
            store.init()
            store.upsert_topic("latest space videos", max_candidates=12)

            snapshot = {
                "elements": [
                    {"name": "Sign in", "href": "https://accounts.google.com/"},
                    {
                        "name": "Latest space telescope discovery",
                        "href": "https://www.youtube.com/watch?v=abcDEF_1234",
                    },
                ]
            }
            env = {
                "SIGNALTUBE_PUBLISH_USERNAME": "user1",
                "SIGNALTUBE_PUBLISH_PASSWORD": "secret",
            }
            with mock.patch.dict(signaltube_lab_cli.os.environ, env, clear=False):
                with mock.patch.object(
                    signaltube_lab_cli.BrowserBrainClient, "open_search_snapshot", return_value=snapshot
                ):
                    with mock.patch.object(
                        signaltube_lab_cli, "publish_html", return_value="https://mavali.top/projects/SignalTube/index.html"
                    ) as publish_html:
                        exit_code = signaltube_lab_cli.main(
                            [
                                "--db",
                                str(db_path),
                                "--html",
                                str(html_path),
                                "scheduled-collect",
                                "--skip-youtube-metadata",
                            ]
                        )

            self.assertEqual(exit_code, 0)
            publish_html.assert_called_once()


if __name__ == "__main__":
    unittest.main()
