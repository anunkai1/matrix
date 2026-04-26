from __future__ import annotations

import unittest

from ops.chatgpt_web_bridge import (
    detect_blocked_state,
    extract_response,
    find_prompt_box,
    find_send_button,
)


class ChatGPTWebBridgeTests(unittest.TestCase):
    def test_find_prompt_box_prefers_chatgpt_textbox(self) -> None:
        snapshot = {
            "snapshot_id": "snap-1",
            "elements": [
                {"ref": "el-1", "role": "textbox", "name": "Search", "visible": True, "enabled": True},
                {
                    "ref": "el-2",
                    "role": "textbox",
                    "aria_label": "Message ChatGPT",
                    "visible": True,
                    "enabled": True,
                    "content_editable": True,
                },
            ],
        }

        self.assertEqual(find_prompt_box(snapshot), {"snapshot_id": "snap-1", "ref": "el-2"})

    def test_find_send_button_detects_send_prompt(self) -> None:
        snapshot = {
            "snapshot_id": "snap-2",
            "elements": [
                {"ref": "el-1", "role": "button", "name": "Attach files", "visible": True, "enabled": True},
                {"ref": "el-2", "role": "button", "aria_label": "Send prompt", "visible": True, "enabled": True},
            ],
        }

        self.assertEqual(find_send_button(snapshot), {"snapshot_id": "snap-2", "ref": "el-2"})

    def test_detect_blocked_state_login(self) -> None:
        snapshot = {"aria_snapshot": "Log in\nSign up\nContinue with Google", "elements": []}

        self.assertEqual(detect_blocked_state(snapshot), "login_required")

    def test_extract_response_uses_tail_after_prompt(self) -> None:
        snapshot = {
            "aria_snapshot": """
            - main:
              - paragraph: What is 2+2?
              - article:
                - paragraph: 2+2 is 4.
                - button "Copy"
              - textbox "Message ChatGPT"
            """
        }

        self.assertEqual(extract_response(snapshot, "What is 2+2?"), "2+2 is 4.")


if __name__ == "__main__":
    unittest.main()
