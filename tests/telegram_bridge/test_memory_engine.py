import importlib.util
import re
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "src" / "telegram_bridge" / "memory_engine.py"

spec = importlib.util.spec_from_file_location("bridge_memory_engine", MODULE_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError("Failed to load memory engine module spec")
memory = importlib.util.module_from_spec(spec)
spec.loader.exec_module(memory)


class MemoryEngineTests(unittest.TestCase):
    def test_default_mode_is_full(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "memory.sqlite3")
            engine = memory.MemoryEngine(db_path)
            self.assertEqual(engine.get_mode("tg:100"), memory.MODE_FULL)

    def test_per_key_isolation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "memory.sqlite3")
            engine = memory.MemoryEngine(db_path)
            key_a = memory.MemoryEngine.telegram_key(1)
            key_b = memory.MemoryEngine.telegram_key(2)

            fact_id, _ = engine.remember_explicit(key_a, "I prefer metric units")
            self.assertGreater(fact_id, 0)

            exported_a = engine.export_facts(key_a)
            exported_b = engine.export_facts(key_b)
            self.assertEqual(len(exported_a), 1)
            self.assertEqual(len(exported_b), 0)

    def test_cli_session_persists_across_engine_restarts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "memory.sqlite3")
            key = memory.MemoryEngine.cli_key("default")

            engine_a = memory.MemoryEngine(db_path)
            turn = engine_a.begin_turn(
                conversation_key=key,
                channel="cli",
                sender_name="CLI User",
                user_input="Track this session",
            )
            engine_a.finish_turn(turn, channel="cli", assistant_text="Session stored", new_thread_id="thread-abc")

            engine_b = memory.MemoryEngine(db_path)
            self.assertEqual(engine_b.get_session_thread_id(key), "thread-abc")
            status = engine_b.get_status(key)
            self.assertEqual(status.message_count, 2)
            self.assertTrue(status.session_active)

    def test_session_only_skips_facts_and_summary_sections(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "memory.sqlite3")
            key = memory.MemoryEngine.telegram_key(44)
            engine = memory.MemoryEngine(db_path)

            engine.remember_explicit(key, "favorite_editor: vim")
            engine.set_mode(key, memory.MODE_SESSION_ONLY)
            turn = engine.begin_turn(
                conversation_key=key,
                channel="telegram",
                sender_name="User",
                user_input="my name is Alice and I like pizza",
            )
            self.assertNotIn("Durable Facts:", turn.prompt_text)
            self.assertNotIn("Conversation Summary:", turn.prompt_text)
            engine.finish_turn(turn, channel="telegram", assistant_text="ok", new_thread_id="thread-1")

            exported = engine.export_facts(key)
            active = [row for row in exported if row["status"] == "active"]
            self.assertEqual(len(active), 1)
            self.assertEqual(active[0]["fact_key"], "explicit:favorite_editor")
            self.assertEqual(engine.get_status(key).summary_count, 0)

    def test_command_flow_for_remember_forget_reset_and_hard_reset(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "memory.sqlite3")
            key = memory.MemoryEngine.cli_key("default")
            engine = memory.MemoryEngine(db_path)

            remember = memory.handle_memory_command(engine, key, "/remember project: matrix")
            self.assertTrue(remember.handled)
            self.assertIn("Remembered", remember.response or "")
            match = re.search(r"id=(\d+)", remember.response or "")
            self.assertIsNotNone(match)
            fact_id = match.group(1)

            export = memory.handle_memory_command(engine, key, "/memory export")
            self.assertIn(f"id={fact_id}", export.response or "")

            forget = memory.handle_memory_command(engine, key, f"/forget {fact_id}")
            self.assertIn("Forgot fact id", forget.response or "")

            engine.remember_explicit(key, "timezone: AEST")
            forget_all = memory.handle_memory_command(engine, key, "/forget-all")
            self.assertIn("Forgot", forget_all.response or "")

            engine.set_session_thread_id(key, "thread-before-reset")
            reset_session = memory.handle_memory_command(engine, key, "/reset-session")
            self.assertIn("Session continuity reset", reset_session.response or "")
            self.assertIsNone(engine.get_session_thread_id(key))

            hard_reset = memory.handle_memory_command(engine, key, "/hard-reset-memory")
            self.assertIn("Hard reset complete", hard_reset.response or "")
            status = engine.get_status(key)
            self.assertEqual(status.active_fact_count, 0)
            self.assertEqual(status.summary_count, 0)
            self.assertEqual(status.message_count, 0)
            self.assertFalse(status.session_active)
            self.assertEqual(status.mode, memory.MODE_FULL)

    def test_ask_command_is_stateless(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "memory.sqlite3")
            key = memory.MemoryEngine.cli_key("default")
            engine = memory.MemoryEngine(db_path)

            cmd = memory.handle_memory_command(engine, key, "/ask what time is it?")
            self.assertTrue(cmd.handled)
            self.assertTrue(cmd.stateless)
            self.assertEqual(cmd.run_prompt, "what time is it?")

            turn = engine.begin_turn(
                conversation_key=key,
                channel="cli",
                sender_name="CLI User",
                user_input=cmd.run_prompt or "",
                stateless=True,
            )
            self.assertTrue(turn.stateless)
            engine.finish_turn(turn, channel="cli", assistant_text="No memory", new_thread_id="thread-unused")
            status = engine.get_status(key)
            self.assertEqual(status.message_count, 0)
            self.assertFalse(status.session_active)

    def test_summarization_trigger_and_prompt_sections(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "memory.sqlite3")
            key = memory.MemoryEngine.telegram_key(77)
            engine = memory.MemoryEngine(db_path)
            engine.remember_explicit(key, "profile: Architect operator")

            for i in range(55):
                user_text = f"Message {i} about bridge runtime behavior"
                assistant_text = f"Reply {i} with status"
                turn = engine.begin_turn(
                    conversation_key=key,
                    channel="telegram",
                    sender_name="User",
                    user_input=user_text,
                )
                engine.finish_turn(turn, channel="telegram", assistant_text=assistant_text, new_thread_id="thread-k")

            status = engine.get_status(key)
            self.assertGreaterEqual(status.summary_count, 1)

            assembled = engine.begin_turn(
                conversation_key=key,
                channel="telegram",
                sender_name="User",
                user_input="Final check",
            )
            self.assertIn("Conversation Summary:", assembled.prompt_text)
            self.assertIn("Durable Facts:", assembled.prompt_text)
            self.assertIn("Recent Messages:", assembled.prompt_text)
            recent_block = assembled.prompt_text.split("Recent Messages:\n", maxsplit=1)[1]
            recent_lines = [line for line in recent_block.splitlines() if line.startswith("- [")]
            self.assertLessEqual(len(recent_lines), memory.RECENT_WINDOW)


if __name__ == "__main__":
    unittest.main()
