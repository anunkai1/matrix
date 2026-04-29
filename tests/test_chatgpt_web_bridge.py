from __future__ import annotations

import unittest
from unittest import mock

from ops.chatgpt_web_bridge import (
    BrowserBrainClient,
    ChatGPTWebBridgeError,
    detect_blocked_state,
    detect_network_blocked_state,
    ensure_browser_brain_service,
    extract_response,
    find_latest_copy_button,
    find_prompt_box,
    find_send_button,
    open_or_reuse_chatgpt_tab,
    submit_prompt,
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

    def test_find_latest_copy_button_returns_last_visible_copy(self) -> None:
        snapshot = {
            "snapshot_id": "snap-3",
            "elements": [
                {"ref": "el-1", "role": "button", "aria_label": "Copy", "visible": True, "enabled": True},
                {"ref": "el-2", "role": "button", "aria_label": "Copy", "visible": True, "enabled": True},
            ],
        }

        self.assertEqual(find_latest_copy_button(snapshot), {"snapshot_id": "snap-3", "ref": "el-2"})

    def test_detect_blocked_state_login(self) -> None:
        snapshot = {"aria_snapshot": "Log in\nSign up\nContinue with Google", "elements": []}

        self.assertEqual(detect_blocked_state(snapshot), "login_required")

    def test_detect_blocked_state_login_with_prompt_still_counts_as_login_required(self) -> None:
        snapshot = {
            "aria_snapshot": """
            - banner:
              - button "Log in"
            - main:
              - heading "You said:" [level=4]
              - text: hello
              - heading "ChatGPT said:" [level=4]
              - text: ●
              - button "Stop streaming"
            """
        }

        self.assertEqual(detect_blocked_state(snapshot), "login_required")

    def test_detect_network_blocked_state_flags_backend_403s(self) -> None:
        class FakeClient:
            def request(self, method: str, path: str, payload=None):
                assert method == "POST"
                assert path == "/v1/network"
                return {
                    "events": [
                        {"url": "https://chatgpt.com/backend-api/models?iim=false&is_gizmo=false", "status": 403},
                        {"url": "https://chatgpt.com/ces/statsc/flush", "status": 403},
                    ]
                }

        self.assertEqual(detect_network_blocked_state(FakeClient(), "tab-1"), "network_403")

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

    def test_extract_response_uses_latest_chatgpt_said_section(self) -> None:
        snapshot = {
            "aria_snapshot": """
            - navigation:
              - link "Old conversation"
            - main:
              - heading "You said:" [level=4]
              - text: "Reply with exactly: expected answer"
              - heading "ChatGPT said:" [level=4]
              - paragraph: expected answer
              - group "Response actions":
                - button "Copy response"
            """
        }

        self.assertEqual(extract_response(snapshot, "Reply with exactly: expected answer"), "expected answer")

    def test_extract_response_returns_empty_before_chatgpt_answer(self) -> None:
        snapshot = {
            "aria_snapshot": """
            - navigation:
              - link "Old conversation"
            - main:
              - heading "You said:" [level=4]
              - text: "Reply with exactly: expected answer"
              - button "Thinking"
            """
        }

        self.assertEqual(extract_response(snapshot, "Reply with exactly: expected answer"), "")

    def test_extract_response_filters_chatgpt_ui_wrapper_lines(self) -> None:
        snapshot = {
            "aria_snapshot": """
            group "Your message actions":
            heading "ChatGPT said:" [level=4]
            selectable chatgpt_web engine ok
            group "Response actions":
            Ask anything
            img
            tooltip "Use Voice, Control, Alt, V": Ctrl + Alt + V
            alert
            status
            """
        }

        self.assertEqual(
            extract_response(snapshot, "Reply with exactly: selectable chatgpt_web engine ok"),
            "selectable chatgpt_web engine ok",
        )

    def test_browser_brain_timeout_becomes_bridge_error(self) -> None:
        client = BrowserBrainClient("http://browser-brain.test", timeout_seconds=7)

        with mock.patch("ops.chatgpt_web_bridge.urlopen", side_effect=TimeoutError("timed out")):
            with self.assertRaises(ChatGPTWebBridgeError) as ctx:
                client.request("POST", "/v1/start", {})

        self.assertIn("timed out after 7s: POST /v1/start", str(ctx.exception))

    def test_open_reuse_skips_start_when_browser_brain_already_running(self) -> None:
        class FakeClient:
            def __init__(self) -> None:
                self.calls: list[tuple[str, str]] = []

            def request(self, method: str, path: str, payload=None):
                self.calls.append((method, path))
                if path == "/v1/status":
                    return {"running": True}
                if path == "/v1/tabs":
                    return {"tabs": [{"tab_id": "tab-1", "url": "https://chatgpt.com/"}]}
                if path == "/v1/tabs/focus":
                    return {"tab": {"tab_id": "tab-1"}}
                raise AssertionError(f"unexpected request {method} {path}")

        client = FakeClient()

        self.assertEqual(open_or_reuse_chatgpt_tab(client, url="https://chatgpt.com/"), "tab-1")
        self.assertNotIn(("POST", "/v1/start"), client.calls)

    def test_open_reuse_prefers_fresh_chatgpt_tab_over_old_conversation(self) -> None:
        class FakeClient:
            def request(self, method: str, path: str, payload=None):
                if path == "/v1/status":
                    return {"running": True}
                if path == "/v1/tabs":
                    return {
                        "tabs": [
                            {"tab_id": "old", "url": "https://chatgpt.com/c/old"},
                            {"tab_id": "fresh", "url": "https://chatgpt.com/"},
                        ]
                    }
                if path == "/v1/tabs/focus":
                    return {"tab": {"tab_id": payload["tab_id"]}}
                raise AssertionError(f"unexpected request {method} {path}")

        self.assertEqual(open_or_reuse_chatgpt_tab(FakeClient(), url="https://chatgpt.com/"), "fresh")

    def test_ensure_browser_brain_service_raises_manual_start_error(self) -> None:
        inactive = mock.Mock(returncode=3)
        failed_start = mock.Mock(returncode=1, stdout="", stderr="access denied")

        with mock.patch("ops.chatgpt_web_bridge.subprocess.run", side_effect=[inactive, failed_start]) as run_mock:
            with self.assertRaises(ChatGPTWebBridgeError) as ctx:
                ensure_browser_brain_service("server3-browser-brain.service")

        self.assertIn("Start it manually", str(ctx.exception))
        self.assertEqual(run_mock.call_args_list[1].args[0][:2], ["systemctl", "start"])

    def test_submit_prompt_enter_fallback_uses_refreshed_snapshot(self) -> None:
        class FakeClient:
            def __init__(self) -> None:
                self.actions = []

            def request(self, method: str, path: str, payload=None):
                self.actions.append((method, path, payload))
                if path == "/v1/act/type":
                    return {"ok": True}
                if path == "/v1/snapshot":
                    return {
                        "snapshot_id": "snap-after",
                        "elements": [
                            {
                                "ref": "el-after",
                                "role": "textbox",
                                "aria_label": "Message ChatGPT",
                                "visible": True,
                                "enabled": True,
                                "content_editable": True,
                            }
                        ],
                    }
                if path == "/v1/act/press":
                    return {"ok": True}
                raise AssertionError(f"unexpected request {method} {path}")

        client = FakeClient()
        submit_prompt(
            client,
            "tab-1",
            {
                "snapshot_id": "snap-before",
                "elements": [
                    {
                        "ref": "el-before",
                        "role": "textbox",
                        "aria_label": "Message ChatGPT",
                        "visible": True,
                        "enabled": True,
                        "content_editable": True,
                    }
                ],
            },
            "hello",
        )

        press_payload = client.actions[-1][2]
        self.assertEqual(press_payload["snapshot_id"], "snap-after")
        self.assertEqual(press_payload["ref"], "el-after")


if __name__ == "__main__":
    unittest.main()
