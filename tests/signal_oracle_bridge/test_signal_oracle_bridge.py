import importlib.util
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "ops" / "signal_oracle" / "bridge" / "signal_oracle_bridge.py"

spec = importlib.util.spec_from_file_location("signal_oracle_bridge", MODULE_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError("Failed to load signal oracle bridge module spec")
signal_bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(signal_bridge)


def make_config(state_dir: str):
    return signal_bridge.Config(
        api_host="127.0.0.1",
        api_port=18797,
        api_auth_token="",
        state_dir=state_dir,
        signal_cli_path="signal-cli",
        signal_account="+15550001111",
        signal_account_uuid="",
        signal_http_host="127.0.0.1",
        signal_http_port=18080,
        signal_receive_mode="manual",
        signal_ignore_attachments=False,
        signal_ignore_stories=True,
        signal_send_read_receipts=False,
        max_updates_per_poll=100,
        max_queue_size=2000,
        max_long_poll_seconds=30,
        file_max_bytes=5 * 1024 * 1024,
        file_total_bytes=20 * 1024 * 1024,
        daemon_startup_timeout_seconds=1,
        log_level="INFO",
    )


class SignalOracleBridgeTests(unittest.TestCase):
    def test_load_config_uses_current_default_ports(self):
        with unittest.mock.patch.dict(
            "os.environ",
            {"SIGNAL_ACCOUNT": "+15550001111"},
            clear=True,
        ):
            config = signal_bridge.load_config()
        self.assertEqual(config.api_port, 18797)
        self.assertEqual(config.signal_http_port, 18080)

    def test_normalize_envelope_for_text_dm(self):
        with tempfile.TemporaryDirectory() as tmp:
            bridge = signal_bridge.SignalOracleBridge(make_config(tmp))
            update = bridge._normalize_envelope(
                {
                    "sourceNumber": "+15552223333",
                    "sourceName": "Alice",
                    "timestamp": 1730000000000,
                    "dataMessage": {"message": "@oracle hello"},
                }
            )

        self.assertIsNotNone(update)
        message = update["message"]
        self.assertEqual(message["chat"]["type"], "private")
        self.assertEqual(message["from"]["first_name"], "Alice")
        self.assertEqual(message["text"], "@oracle hello")
        self.assertEqual(message["message_id"], 1730000000000)

    def test_normalize_envelope_for_group_voice_attachment(self):
        with tempfile.TemporaryDirectory() as tmp:
            bridge = signal_bridge.SignalOracleBridge(make_config(tmp))
            update = bridge._normalize_envelope(
                {
                    "sourceNumber": "+15554445555",
                    "sourceName": "Bob",
                    "timestamp": 1730000000100,
                    "dataMessage": {
                        "message": "@oracle transcribe this",
                        "groupInfo": {"groupId": "grp-1", "groupName": "Oracle Room"},
                        "attachments": [
                            {
                                "id": "att-1",
                                "contentType": "audio/ogg",
                                "filename": "voice-note.ogg",
                                "size": 321,
                            }
                        ],
                    },
                }
            )

        self.assertIsNotNone(update)
        message = update["message"]
        self.assertEqual(message["chat"]["type"], "group")
        self.assertEqual(message["caption"], "@oracle transcribe this")
        self.assertEqual(message["voice"]["file_id"].startswith("sig-"), True)

    def test_normalize_envelope_for_dm_aac_voice_note(self):
        with tempfile.TemporaryDirectory() as tmp:
            bridge = signal_bridge.SignalOracleBridge(make_config(tmp))
            update = bridge._normalize_envelope(
                {
                    "sourceNumber": "+15554445555",
                    "sourceName": "Bob",
                    "timestamp": 1730000000200,
                    "dataMessage": {
                        "attachments": [
                            {
                                "id": "att-aac-1",
                                "contentType": "audio/aac",
                                "filename": "voice-note.aac",
                                "size": 10573,
                            }
                        ],
                    },
                }
            )

        self.assertIsNotNone(update)
        message = update["message"]
        self.assertEqual(message["chat"]["type"], "private")
        self.assertIn("voice", message)
        self.assertNotIn("document", message)
        self.assertTrue(message["voice"]["file_id"].startswith("sig-"))

    def test_get_file_meta_returns_cached_attachment_mapping(self):
        with tempfile.TemporaryDirectory() as tmp:
            bridge = signal_bridge.SignalOracleBridge(make_config(tmp))
            file_id = bridge.attachments.remember(
                attachment_id="att-2",
                sender="+15556667777",
                group_id="",
                content_type="image/jpeg",
                file_name="photo.jpg",
                size=456,
            )
            meta = bridge.get_file_meta(file_id)

        self.assertEqual(meta["file_path"], file_id)
        self.assertEqual(meta["file_size"], 456)
        self.assertEqual(meta["file_name"], "photo.jpg")

    def test_own_sender_detection_matches_account_number(self):
        with tempfile.TemporaryDirectory() as tmp:
            bridge = signal_bridge.SignalOracleBridge(make_config(tmp))
            self.assertTrue(bridge._is_own_sender({"sourceNumber": "+15550001111"}))
            self.assertFalse(bridge._is_own_sender({"sourceNumber": "+15559990000"}))


if __name__ == "__main__":
    unittest.main()
