import importlib.util
import re
import tempfile
import time
import unittest
from unittest import mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "src" / "telegram_bridge" / "memory_engine.py"

spec = importlib.util.spec_from_file_location("bridge_memory_engine", MODULE_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError("Failed to load memory engine module spec")
memory = importlib.util.module_from_spec(spec)
spec.loader.exec_module(memory)


class MemoryEngineTests(unittest.TestCase):
    def test_default_mode_is_all_context(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "memory.sqlite3")
            engine = memory.MemoryEngine(db_path)
            self.assertEqual(engine.get_mode("tg:100"), memory.MODE_FULL)

    def test_legacy_full_alias_maps_to_all_context(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "memory.sqlite3")
            engine = memory.MemoryEngine(db_path)
            key = memory.MemoryEngine.telegram_key(101)

            mode = engine.set_mode(key, "full")
            self.assertEqual(mode, memory.MODE_FULL)
            self.assertEqual(engine.get_mode(key), memory.MODE_FULL)

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

            mode_alias = memory.handle_memory_command(engine, key, "/memory mode full")
            self.assertTrue(mode_alias.handled)
            self.assertIn("all_context", mode_alias.response or "")

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

    def test_remember_redacts_obvious_secret_values(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "memory.sqlite3")
            key = memory.MemoryEngine.cli_key("default")
            engine = memory.MemoryEngine(db_path)

            remember = memory.handle_memory_command(
                engine,
                key,
                "/remember api_key: sk-SecretToken1234567890",
            )
            self.assertTrue(remember.handled)
            self.assertIn("Remembered", remember.response or "")

            exported = engine.export_facts(key, include_sensitive=True)
            self.assertEqual(len(exported), 1)
            value = str(exported[0]["fact_value"])
            self.assertIn("[REDACTED]", value)
            self.assertNotIn("sk-SecretToken1234567890", value)

    def test_memory_export_is_redacted_by_default_with_raw_opt_in(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "memory.sqlite3")
            key = memory.MemoryEngine.cli_key("default")
            engine = memory.MemoryEngine(db_path)

            with engine._lock, engine._connect() as conn:
                engine._upsert_fact(
                    conn,
                    key,
                    "legacy:token",
                    "token: sk-rawlegacy1234567890",
                    explicit=True,
                    confidence=0.99,
                    source_msg_id=None,
                )

            safe_export = memory.handle_memory_command(engine, key, "/memory export")
            self.assertIn("redacted", safe_export.response or "")
            self.assertNotIn("sk-rawlegacy1234567890", safe_export.response or "")
            self.assertIn("[REDACTED]", safe_export.response or "")

            raw_export = memory.handle_memory_command(engine, key, "/memory export raw")
            self.assertIn("sk-rawlegacy1234567890", raw_export.response or "")

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

    def test_retention_prunes_old_messages_and_keeps_explicit_facts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "memory.sqlite3")
            key = memory.MemoryEngine.telegram_key(88)
            engine = memory.MemoryEngine(
                db_path,
                max_messages_per_key=6,
                max_summaries_per_key=80,
                prune_interval_seconds=0,
            )
            engine.remember_explicit(key, "favorite_shell: bash")

            for i in range(8):
                turn = engine.begin_turn(
                    conversation_key=key,
                    channel="telegram",
                    sender_name="User",
                    user_input=f"Retention message {i}",
                )
                engine.finish_turn(
                    turn,
                    channel="telegram",
                    assistant_text=f"Retention reply {i}",
                    new_thread_id="thread-r",
                )

            status = engine.get_status(key)
            self.assertLessEqual(status.message_count, 6)
            facts = [row for row in engine.export_facts(key) if row["status"] == "active"]
            self.assertEqual(len(facts), 1)
            self.assertEqual(facts[0]["fact_key"], "explicit:favorite_shell")

    def test_force_retention_prunes_summary_rows_and_reconciles_state(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "memory.sqlite3")
            key = memory.MemoryEngine.cli_key("ops")
            engine = memory.MemoryEngine(
                db_path,
                max_messages_per_key=0,
                max_summaries_per_key=1,
                prune_interval_seconds=300,
            )

            with engine._lock, engine._connect() as conn:
                engine._ensure_memory_rows(conn, key)
                now = time.time()
                conn.executemany(
                    """
                    INSERT INTO chat_summaries (
                        conversation_key,
                        start_msg_id,
                        end_msg_id,
                        summary_text,
                        key_points_json,
                        open_loops_json,
                        created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (key, 1, 10, "s1", "[]", "[]", now),
                        (key, 11, 20, "s2", "[]", "[]", now + 1),
                        (key, 21, 30, "s3", "[]", "[]", now + 2),
                    ],
                )
                conn.execute(
                    """
                    UPDATE memory_state
                    SET unsummarized_start_msg_id = ?, last_summary_msg_id = ?, updated_at = ?
                    WHERE conversation_key = ?
                    """,
                    (31, 30, now + 2, key),
                )

            result = engine.run_retention_prune(conversation_key=key, force=True)
            self.assertEqual(result.scanned_keys, 1)
            self.assertEqual(result.pruned_summaries, 2)

            status = engine.get_status(key)
            self.assertEqual(status.summary_count, 1)
            with engine._lock, engine._connect() as conn:
                state = conn.execute(
                    """
                    SELECT last_summary_msg_id
                    FROM memory_state
                    WHERE conversation_key = ?
                    """,
                    (key,),
                ).fetchone()
            self.assertEqual(int(state["last_summary_msg_id"]), 30)

    def test_force_retention_reconciles_once_when_messages_and_summaries_pruned(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "memory.sqlite3")
            key = memory.MemoryEngine.cli_key("reconcile-once")
            engine = memory.MemoryEngine(
                db_path,
                max_messages_per_key=2,
                max_summaries_per_key=1,
                prune_interval_seconds=0,
            )
            with engine._lock, engine._connect() as conn:
                engine._ensure_memory_rows(conn, key)
                now = time.time()
                conn.executemany(
                    """
                    INSERT INTO messages (
                        conversation_key,
                        channel,
                        sender_role,
                        sender_name,
                        text,
                        ts,
                        token_estimate,
                        is_bot
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (key, "telegram", "user", "User", "m1", now + 1, 1, 0),
                        (key, "telegram", "assistant", "Architect", "m2", now + 2, 1, 1),
                        (key, "telegram", "user", "User", "m3", now + 3, 1, 0),
                        (key, "telegram", "assistant", "Architect", "m4", now + 4, 1, 1),
                    ],
                )
                conn.executemany(
                    """
                    INSERT INTO chat_summaries (
                        conversation_key,
                        start_msg_id,
                        end_msg_id,
                        summary_text,
                        key_points_json,
                        open_loops_json,
                        created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (key, 1, 2, "s1", "[]", "[]", now + 10),
                        (key, 3, 4, "s2", "[]", "[]", now + 11),
                    ],
                )
            with mock.patch.object(
                engine,
                "_reconcile_memory_state",
                wraps=engine._reconcile_memory_state,
            ) as reconcile:
                result = engine.run_retention_prune(conversation_key=key, force=True)
            self.assertGreater(result.pruned_messages, 0)
            self.assertGreater(result.pruned_summaries, 0)
            self.assertEqual(reconcile.call_count, 1)


if __name__ == "__main__":
    unittest.main()
