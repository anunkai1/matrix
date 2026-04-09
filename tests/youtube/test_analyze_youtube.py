import importlib.util
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "ops" / "youtube" / "analyze_youtube.py"

spec = importlib.util.spec_from_file_location("youtube_analyzer", MODULE_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError("Failed to load YouTube analyzer module spec")
youtube_analyzer = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = youtube_analyzer
spec.loader.exec_module(youtube_analyzer)


class AnalyzeYouTubeTests(unittest.TestCase):
    def test_infer_request_mode_detects_transcript_requests(self) -> None:
        self.assertEqual(youtube_analyzer.infer_request_mode("full transcript https://youtu.be/abc"), "transcript")
        self.assertEqual(youtube_analyzer.infer_request_mode("транскрипт https://youtu.be/abc"), "transcript")
        self.assertEqual(youtube_analyzer.infer_request_mode("https://youtu.be/abc"), "summary")

    def test_clean_subtitle_text_strips_timing_and_tags(self) -> None:
        raw = (
            "WEBVTT\n\n"
            "00:00:01.000 --> 00:00:03.000\n"
            "<c>hello</c>\n\n"
            "1\n"
            "00:00:03.500 --> 00:00:05.000\n"
            "hello\n"
            "world\n"
        )
        self.assertEqual(youtube_analyzer.clean_subtitle_text(raw), "hello\nworld")

    def test_choose_subtitle_candidates_prefers_video_language_then_manual(self) -> None:
        metadata = {
            "language": "ru",
            "subtitles": {"en": [{}], "ru": [{}]},
            "automatic_captions": {"ru": [{}], "de": [{}]},
        }

        candidates = youtube_analyzer.choose_subtitle_candidates(metadata)

        self.assertEqual(candidates[0], ("manual", "ru"))
        self.assertIn(("auto", "ru"), candidates)
        self.assertIn(("manual", "en"), candidates)

    @mock.patch.object(youtube_analyzer, "run_command")
    def test_load_channel_profile_extracts_channel_context(self, run_command) -> None:
        run_command.return_value = subprocess.CompletedProcess(
            args=["yt-dlp"],
            returncode=0,
            stdout=(
                '{"title":"Asian Boss","channel":"Asian Boss","channel_follower_count":4030000,'
                '"description":"Street-interview based channel about Asia.",'
                '"tags":["Asia","interviews"],"channel_url":"https://www.youtube.com/@AsianBoss"}'
            ),
            stderr="",
        )

        profile = youtube_analyzer.load_channel_profile(
            {"channel_url": "https://www.youtube.com/@AsianBoss"}
        )

        self.assertEqual(profile["title"], "Asian Boss")
        self.assertEqual(profile["follower_count"], 4030000)
        self.assertIn("Street-interview", profile["description"])
        self.assertEqual(profile["tags"], ["Asia", "interviews"])

    @mock.patch.object(youtube_analyzer, "run_command")
    def test_load_channel_profile_returns_empty_when_channel_missing(self, run_command) -> None:
        profile = youtube_analyzer.load_channel_profile({})
        self.assertEqual(profile, {})
        run_command.assert_not_called()

    @mock.patch.object(youtube_analyzer.os, "replace")
    @mock.patch.object(youtube_analyzer, "find_downloaded_audio")
    @mock.patch.object(youtube_analyzer, "run_command")
    def test_download_audio_falls_back_to_best_available_media(
        self,
        run_command,
        find_downloaded_audio,
        os_replace,
    ) -> None:
        run_command.side_effect = [
            subprocess.CompletedProcess(args=["yt-dlp"], returncode=1, stdout="", stderr="Requested format is not available"),
            subprocess.CompletedProcess(args=["yt-dlp"], returncode=0, stdout="", stderr=""),
        ]
        find_downloaded_audio.return_value = "/tmp/example.mp4"

        persisted = youtube_analyzer.download_audio("https://www.youtube.com/watch?v=abc")

        self.assertTrue(persisted.endswith("example.mp4"))
        self.assertEqual(run_command.call_count, 2)
        self.assertIn("bestaudio/best", run_command.call_args_list[0].args[0])
        self.assertNotIn("bestaudio/best", run_command.call_args_list[1].args[0])
        os_replace.assert_called_once()


if __name__ == "__main__":
    unittest.main()
