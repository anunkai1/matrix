import importlib
import io
import logging
import os
import unittest
from unittest import mock

import telegram_bridge.structured_logging as structured_logging


class StructuredLoggingTests(unittest.TestCase):
    def _configure_with_stream(self, env_value=mock.sentinel.unset):
        if env_value is mock.sentinel.unset:
            env_patch = mock.patch.dict(os.environ, {}, clear=False)
        elif env_value is None:
            env_patch = mock.patch.dict(os.environ, {"TELEGRAM_LOG_SUPPRESS_EVENTS": ""}, clear=False)
        else:
            env_patch = mock.patch.dict(
                os.environ,
                {"TELEGRAM_LOG_SUPPRESS_EVENTS": env_value},
                clear=False,
            )

        with env_patch:
            module = importlib.reload(structured_logging)
            module.configure_bridge_logging("INFO")
            root = logging.getLogger()
            stream = io.StringIO()
            root.handlers[0].stream = stream
            return module, stream

    def test_default_suppressed_info_event_is_not_logged(self) -> None:
        module, stream = self._configure_with_stream()

        module.emit_event("bridge.request_phase_timing", fields={"phase": "engine_run"})

        self.assertEqual(stream.getvalue(), "")

    def test_warning_for_suppressed_event_still_logs(self) -> None:
        module, stream = self._configure_with_stream()

        module.emit_event(
            "bridge.request_phase_timing",
            level=logging.WARNING,
            fields={"phase": "engine_run"},
        )

        output = stream.getvalue()
        self.assertIn('"event": "bridge.request_phase_timing"', output)
        self.assertIn('"level": "WARNING"', output)

    def test_env_can_disable_default_suppression(self) -> None:
        module, stream = self._configure_with_stream(env_value=None)

        module.emit_event("bridge.request_phase_timing", fields={"phase": "engine_run"})

        output = stream.getvalue()
        self.assertIn('"event": "bridge.request_phase_timing"', output)
        self.assertIn('"level": "INFO"', output)

    def test_env_can_override_suppressed_event_list(self) -> None:
        module, stream = self._configure_with_stream(env_value="bridge.update_received")

        module.emit_event("bridge.request_phase_timing", fields={"phase": "engine_run"})
        module.emit_event("bridge.update_received", fields={"chat_id": 1})

        output = stream.getvalue()
        self.assertIn('"event": "bridge.request_phase_timing"', output)
        self.assertNotIn('"event": "bridge.update_received"', output)


if __name__ == "__main__":
    unittest.main()
