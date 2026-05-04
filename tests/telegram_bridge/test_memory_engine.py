import importlib.util
import tempfile
import time
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
    def test_begin_turn_and_finish_turn_store_and_load_messages(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "memory.sqlite3")
            key = memory.MemoryEngine.telegram_key(1)
            engine = memory.MemoryEngine(db_path)

            turn = engine.begin_turn(
                conversation_key=key,
                channel="telegram",
                sender_name="User",
                user_input="Hello world",
            )
            self.assertIn("Hello world", turn.prompt_text)
            self.assertIn("Current User Input:", turn.prompt_text)

            engine.finish_turn(
                turn,
                channel="telegram",
                assistant_text="Hi there!",
                new_thread_id="thread-1",
            )

            status = engine.get_status(key)
            self.assertEqual(status.message_count, 2)
            self.assertTrue(status.session_active)

            turn2 = engine.begin_turn(
                conversation_key=key,
                channel="telegram",
                sender_name="User",
                user_input="Second message",
            )
            self.assertIn("Hello world", turn2.prompt_text)
            self.assertIn("Hi there!", turn2.prompt_text)
            self.assertIn("Second message", turn2.prompt_text)

    def test_finish_turn_uses_supplied_assistant_name(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "memory.sqlite3")
            key = memory.MemoryEngine.telegram_key(334)
            engine = memory.MemoryEngine(db_path)

            turn = engine.begin_turn(
                conversation_key=key,
                channel="signal",
                sender_name="User",
                user_input="hello",
            )
            engine.finish_turn(
                turn,
                channel="signal",
                assistant_text="",
                new_thread_id="thread-oracle",
                assistant_name="Oracle",
            )

            with engine._lock, engine._connect() as conn:
                row = conn.execute(
                    """
                    SELECT sender_name, text
                    FROM messages
                    WHERE conversation_key = ? AND sender_role = 'assistant'
                    ORDER BY id DESC
                    LIMIT 1
                    """,
                    (key,),
                ).fetchone()
            self.assertEqual(str(row["sender_name"]), "Oracle")
            self.assertEqual(str(row["text"]), "(No output from Oracle)")

    def test_recent_messages_respect_token_budget(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "memory.sqlite3")
            key = memory.MemoryEngine.telegram_key(446)
            engine = memory.MemoryEngine(db_path)

            for idx in range(250):
                user_text = f"Long message {idx}: " + ("detail " * 100)
                turn = engine.begin_turn(
                    conversation_key=key,
                    channel="telegram",
                    sender_name="User",
                    user_input=user_text,
                )
                engine.finish_turn(
                    turn,
                    channel="telegram",
                    assistant_text=f"reply {idx}",
                    new_thread_id="thread-long",
                )

            assembled = engine.begin_turn(
                conversation_key=key,
                channel="telegram",
                sender_name="User",
                user_input="Final check",
            )
            # The most recent messages should be included
            self.assertIn("reply 249", assembled.prompt_text)
            # Very old messages should be dropped (token budget exceeded)
            self.assertNotIn("Long message 0:", assembled.prompt_text)

    def test_clear_session_removes_messages_and_session(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "memory.sqlite3")
            key = memory.MemoryEngine.telegram_key(333)
            engine = memory.MemoryEngine(db_path)

            turn = engine.begin_turn(
                conversation_key=key,
                channel="signal",
                sender_name="User",
                user_input="who are you",
            )
            engine.finish_turn(
                turn,
                channel="signal",
                assistant_text="I am Oracle.",
                new_thread_id="thread-oracle",
                assistant_name="Oracle",
            )

            engine.clear_session(key)

            status = engine.get_status(key)
            self.assertEqual(status.message_count, 0)
            self.assertFalse(status.session_active)

    def test_session_thread_id_persistence(self):
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

    def test_stateless_turn_does_not_store_messages(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "memory.sqlite3")
            key = memory.MemoryEngine.cli_key("default")
            engine = memory.MemoryEngine(db_path)

            turn = engine.begin_turn(
                conversation_key=key,
                channel="cli",
                sender_name="CLI User",
                user_input="Stateless query",
                stateless=True,
            )
            self.assertTrue(turn.stateless)
            engine.finish_turn(turn, channel="cli", assistant_text="No memory", new_thread_id="thread-unused")
            status = engine.get_status(key)
            self.assertEqual(status.message_count, 0)
            self.assertFalse(status.session_active)

    def test_ask_command_is_stateless(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "memory.sqlite3")
            key = memory.MemoryEngine.cli_key("default")
            engine = memory.MemoryEngine(db_path)

            cmd = memory.handle_memory_command(engine, key, "/ask what time is it?")
            self.assertTrue(cmd.handled)
            self.assertTrue(cmd.stateless)
            self.assertEqual(cmd.run_prompt, "what time is it?")

    def test_removed_memory_commands_return_stub(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "memory.sqlite3")
            key = memory.MemoryEngine.cli_key("default")
            engine = memory.MemoryEngine(db_path)

            for cmd in ["/memory status", "/remember project: test", "/forget 1", "/forget-all", "/reset-session", "/hard-reset-memory"]:
                result = memory.handle_memory_command(engine, key, cmd)
                self.assertTrue(result.handled, f"Command {cmd} should be handled")
                self.assertIn("simplified", result.response or "")

    def test_telegram_key_helpers(self):
        self.assertEqual(memory.MemoryEngine.telegram_key(123), "tg:123")
        self.assertEqual(memory.MemoryEngine.channel_key("telegram", 456), "tg:456")
        self.assertEqual(memory.MemoryEngine.channel_key("whatsapp", 789), "wa:789")
        self.assertEqual(memory.MemoryEngine.channel_key("signal", 101), "sig:101")

    def test_hard_reset_clears_all(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "memory.sqlite3")
            key = memory.MemoryEngine.telegram_key(900)
            engine = memory.MemoryEngine(db_path)

            turn = engine.begin_turn(
                conversation_key=key,
                channel="telegram",
                sender_name="User",
                user_input="message 1",
            )
            engine.finish_turn(turn, channel="telegram", assistant_text="reply 1", new_thread_id="t1")

            engine.hard_reset_memory(key)
            status = engine.get_status(key)
            self.assertEqual(status.message_count, 0)

    def test_hard_reset_all_memory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "memory.sqlite3")
            key = memory.MemoryEngine.telegram_key(901)
            engine = memory.MemoryEngine(db_path)

            turn = engine.begin_turn(
                conversation_key=key,
                channel="telegram",
                sender_name="User",
                user_input="message 1",
            )
            engine.finish_turn(turn, channel="telegram", assistant_text="reply 1", new_thread_id="t1")

            counts = engine.hard_reset_all_memory()
            self.assertGreater(counts["messages"], 0)
            self.assertGreater(counts["sessions"], 0)

    def test_per_key_isolation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "memory.sqlite3")
            engine = memory.MemoryEngine(db_path)
            key_a = memory.MemoryEngine.telegram_key(1)
            key_b = memory.MemoryEngine.telegram_key(2)

            turn_a = engine.begin_turn(
                conversation_key=key_a,
                channel="telegram",
                sender_name="User",
                user_input="Chat A message",
            )
            engine.finish_turn(turn_a, channel="telegram", assistant_text="Reply A", new_thread_id="thread-a")

            turn_b = engine.begin_turn(
                conversation_key=key_b,
                channel="telegram",
                sender_name="User",
                user_input="Chat B message",
            )
            engine.finish_turn(turn_b, channel="telegram", assistant_text="Reply B", new_thread_id="thread-b")

            self.assertEqual(engine.get_status(key_a).message_count, 2)
            self.assertEqual(engine.get_status(key_b).message_count, 2)

            self.assertIn("Chat A message", engine.begin_turn(
                conversation_key=key_a,
                channel="telegram",
                sender_name="User",
                user_input="new",
            ).prompt_text)

    def test_natural_language_memory_query_returns_none(self):
        self.assertIsNone(memory.parse_natural_language_memory_intent("what did I say yesterday?"))
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "memory.sqlite3")
            engine = memory.MemoryEngine(db_path)
            result = memory.handle_natural_language_memory_query(
                engine, "tg:1", "what did I say yesterday?"
            )
            self.assertIsNone(result)

    def test_build_memory_help_lines_returns_empty(self):
        self.assertEqual(memory.build_memory_help_lines(), [])


if __name__ == "__main__":
    unittest.main()
