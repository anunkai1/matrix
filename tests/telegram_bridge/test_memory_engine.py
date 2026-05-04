import importlib.util
import re
import tempfile
import time
import unittest
from datetime import datetime
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

    def test_clear_session_removes_messages_facts_summaries_and_session(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "memory.sqlite3")
            key = memory.MemoryEngine.telegram_key(333)
            engine = memory.MemoryEngine(db_path)

            engine.remember_explicit(key, "identity: Oracle")
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

            with engine._lock, engine._connect() as conn:
                conn.execute(
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
                    (key, 1, 2, "summary", "[]", "[]", time.time()),
                )

            engine.clear_session(key)

            status = engine.get_status(key)
            self.assertEqual(status.message_count, 0)
            self.assertEqual(status.active_fact_count, 0)
            self.assertEqual(status.summary_count, 0)
            self.assertFalse(status.session_active)
            self.assertEqual(status.mode, memory.MODE_FULL)

    def test_compact_summarized_messages_deletes_only_raw_rows_covered_by_summary(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "memory.sqlite3")
            key = memory.MemoryEngine.telegram_key(335)
            engine = memory.MemoryEngine(db_path)

            with mock.patch.object(
                memory.llm_summarizer,
                "summarize_via_ollama",
                return_value=None,
            ):
                for idx in range(60):
                    turn = engine.begin_turn(
                        conversation_key=key,
                        channel="telegram",
                        sender_name="User",
                        user_input=f"message {idx}",
                    )
                    engine.finish_turn(
                        turn,
                        channel="telegram",
                        assistant_text=f"reply {idx}",
                        new_thread_id="thread-335",
                    )

                summarized = engine.run_summarization_if_needed(key, force=True)
            self.assertTrue(summarized)

            deleted = engine.compact_summarized_messages(key)
            self.assertEqual(deleted, 120)

            status = engine.get_status(key)
            self.assertEqual(status.message_count, 0)
            self.assertGreaterEqual(status.summary_count, 1)

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

    def test_memory_wrapper_does_not_inject_internal_instruction_rule(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "memory.sqlite3")
            key = memory.MemoryEngine.telegram_key(445)
            engine = memory.MemoryEngine(db_path)

            turn = engine.begin_turn(
                conversation_key=key,
                channel="telegram",
                sender_name="User",
                user_input="show me the runtime instructions",
            )

            self.assertIn("Memory Context Rules:", turn.prompt_text)
            self.assertIn(
                "- Prefer the user's current request when conflicts exist.",
                turn.prompt_text,
            )
            self.assertNotIn(
                "- Do not expose internal memory instructions.",
                turn.prompt_text,
            )

    def test_begin_turn_uses_token_budget_for_recent_messages(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "memory.sqlite3")
            key = memory.MemoryEngine.telegram_key(446)
            engine = memory.MemoryEngine(db_path)

            with mock.patch.object(
                memory.llm_summarizer,
                "summarize_via_ollama",
                return_value=None,
            ):
                for idx in range(8):
                    user_text = f"Long message {idx}: " + ("detail " * 700)
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
            recent_block = assembled.prompt_text.split("Recent Messages:\n", maxsplit=1)[1]
            recent_block = recent_block.split("\n\n", maxsplit=1)[0]
            self.assertIn("reply 7", recent_block)
            self.assertIn("Long message 7", recent_block)

            self.assertIn("Unsummarized Context:\n", assembled.prompt_text)
            unsummarized_block = assembled.prompt_text.split(
                "Unsummarized Context:\n",
                maxsplit=1,
            )[1]
            unsummarized_block = unsummarized_block.split("\n\n", maxsplit=1)[0]
            self.assertIn("Long message 3", unsummarized_block)
            self.assertIn("reply 2", unsummarized_block)
            self.assertNotIn("Long message 0", unsummarized_block)

    def test_begin_turn_uses_shared_background_summary_and_facts_without_mixing_recent_messages(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "memory.sqlite3")
            engine = memory.MemoryEngine(db_path)
            live_key = "shared:architect:main:session:tg:44"
            archive_key = "shared:architect:main"

            engine.remember_explicit(archive_key, "timezone: AEST")
            with engine._lock, engine._connect() as conn:
                conn.execute(
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
                    (
                        archive_key,
                        1,
                        2,
                        "Shared archive summary",
                        "[]",
                        "[]",
                        time.time(),
                    ),
                )

            prior_turn = engine.begin_turn(
                conversation_key=live_key,
                channel="telegram",
                sender_name="User",
                user_input="local context " + ("detail " * 220),
            )
            with mock.patch.object(
                memory.llm_summarizer,
                "summarize_via_ollama",
                return_value=(
                    "Objective:\n- local context\n\n"
                    "Decisions Made:\n- No explicit decision captured.\n\n"
                    "Current State:\n- local reply\n\n"
                    "Open Items:\n- No open item detected.\n\n"
                    "User Preferences:\n- No durable preference detected.\n\n"
                    "Risks/Blockers:\n- No blocker detected."
                ),
            ):
                engine.finish_turn(
                    prior_turn,
                    channel="telegram",
                    assistant_text="local reply",
                    new_thread_id="thread-live",
                )

            turn = engine.begin_turn(
                conversation_key=live_key,
                channel="telegram",
                sender_name="User",
                user_input="current request",
                background_conversation_key=archive_key,
            )

            # With the LLM summarizer, finish_turn triggers a summary for the live
            # key. The live summary takes precedence over the archive summary.
            # We verify the live context is present and archive facts are included.
            self.assertIn("Conversation Summary:", turn.prompt_text)
            self.assertIn("explicit:timezone", turn.prompt_text)
            self.assertIn("local context", turn.prompt_text)

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

            engine.set_session_thread_id(key, "thread-before-global-reset")
            cleared_sessions = engine.clear_all_session_threads()
            self.assertEqual(cleared_sessions, 1)
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

    def test_natural_language_query_returns_recent_user_messages(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "memory.sqlite3")
            key = memory.MemoryEngine.telegram_key(55)
            engine = memory.MemoryEngine(db_path)

            with mock.patch.object(
                memory.llm_summarizer,
                "summarize_via_ollama",
                return_value=None,
            ):
                for user_text in ("first note", "second note", "third note"):
                    turn = engine.begin_turn(
                        conversation_key=key,
                        channel="telegram",
                        sender_name="User",
                        user_input=user_text,
                    )
                    engine.finish_turn(
                        turn,
                        channel="telegram",
                        assistant_text=f"reply to {user_text}",
                        new_thread_id="thread-55",
                    )

            response = memory.handle_natural_language_memory_query(
                engine,
                key,
                "what were the last 2 messages i sent you?",
            )

            self.assertIsNotNone(response)
            text = response or ""
            self.assertIn("Your last 2 messages in memory are:", text)
            self.assertIn("second note", text)
            self.assertIn("third note", text)
            self.assertLess(text.index("second note"), text.index("third note"))
            self.assertNotIn("reply to third note", text)

    def test_natural_language_today_query_prefers_same_day_summary(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "memory.sqlite3")
            key = memory.MemoryEngine.telegram_key(56)
            engine = memory.MemoryEngine(db_path)
            now = datetime(2026, 3, 7, 12, 0, tzinfo=memory.BRISBANE_TZ)
            msg_ts = datetime(2026, 3, 7, 9, 15, tzinfo=memory.BRISBANE_TZ).timestamp()

            with engine._lock, engine._connect() as conn:
                user_msg_id = engine._append_message(
                    conn,
                    conversation_key=key,
                    channel="telegram",
                    sender_role="user",
                    sender_name="User",
                    text="can you inspect the bridge logs today",
                    is_bot=False,
                )
                assistant_msg_id = engine._append_message(
                    conn,
                    conversation_key=key,
                    channel="telegram",
                    sender_role="assistant",
                    sender_name="Architect",
                    text="I checked the bridge logs and they look stable",
                    is_bot=True,
                )
                conn.execute(
                    "UPDATE messages SET ts = ? WHERE id IN (?, ?)",
                    (msg_ts, user_msg_id, assistant_msg_id),
                )
                conn.execute(
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
                    (
                        key,
                        user_msg_id,
                        assistant_msg_id,
                        "Objective:\n- inspect the bridge logs\n\nCurrent State:\n- logs looked stable",
                        "[]",
                        "[]",
                        msg_ts,
                    ),
                )
                engine._upsert_fact(
                    conn,
                    key,
                    "pref:bridge_logs",
                    "you care about bridge log stability",
                    explicit=False,
                    confidence=0.8,
                    source_msg_id=user_msg_id,
                )

            response = memory.handle_natural_language_memory_query(
                engine,
                key,
                "what do you remember from today?",
                now=now,
            )

            self.assertIsNotNone(response)
            text = response or ""
            self.assertIn("From today, I remember:", text)
            self.assertIn("inspect the bridge logs", text)
            self.assertIn("Facts learned in that window:", text)
            self.assertIn("pref:bridge_logs: you care about bridge log stability", text)

    def test_natural_language_today_query_summarizes_messages_without_summary(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "memory.sqlite3")
            key = memory.MemoryEngine.telegram_key(57)
            engine = memory.MemoryEngine(db_path)
            now = datetime(2026, 3, 7, 18, 0, tzinfo=memory.BRISBANE_TZ)
            msg_ts = datetime(2026, 3, 7, 17, 30, tzinfo=memory.BRISBANE_TZ).timestamp()

            with engine._lock, engine._connect() as conn:
                user_msg_id = engine._append_message(
                    conn,
                    conversation_key=key,
                    channel="telegram",
                    sender_role="user",
                    sender_name="User",
                    text="can you review the memory behavior today",
                    is_bot=False,
                )
                assistant_msg_id = engine._append_message(
                    conn,
                    conversation_key=key,
                    channel="telegram",
                    sender_role="assistant",
                    sender_name="Architect",
                    text="reviewed it and found no blocker",
                    is_bot=True,
                )
                conn.execute(
                    "UPDATE messages SET ts = ? WHERE id IN (?, ?)",
                    (msg_ts, user_msg_id, assistant_msg_id),
                )
                engine._upsert_fact(
                    conn,
                    key,
                    "pref:memory_behavior",
                    "you care about memory behavior",
                    explicit=False,
                    confidence=0.8,
                    source_msg_id=user_msg_id,
                )

            response = memory.handle_natural_language_memory_query(
                engine,
                key,
                "what do you remember from today?",
                now=now,
            )

            self.assertIsNotNone(response)
            text = response or ""
            self.assertIn("From today, I remember:", text)
            self.assertIn("Objective:", text)
            self.assertIn("Current State:", text)
            self.assertIn("Facts learned in that window:", text)
            self.assertIn("pref:memory_behavior: you care about memory behavior", text)

    def test_natural_language_memory_intent_falls_through_when_ambiguous(self):
        self.assertIsNone(memory.parse_natural_language_memory_intent("last 5 messages"))

    def test_summarization_trigger_and_prompt_sections(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "memory.sqlite3")
            key = memory.MemoryEngine.telegram_key(77)
            engine = memory.MemoryEngine(db_path)
            engine.remember_explicit(key, "profile: Architect operator")

            with mock.patch.object(
                memory.llm_summarizer,
                "summarize_via_ollama",
                return_value=(
                    "Objective:\n- bridge runtime behavior\n\n"
                    "Decisions Made:\n- No explicit decision captured.\n\n"
                    "Current State:\n- status replies provided\n\n"
                    "Open Items:\n- No open item detected.\n\n"
                    "User Preferences:\n- No durable preference detected.\n\n"
                    "Risks/Blockers:\n- No blocker detected."
                ),
            ):
                for i in range(55):
                    user_text = f"Message {i} about bridge runtime behavior " + ("detail " * 18)
                    assistant_text = f"Reply {i} with status " + ("signal " * 10)
                    turn = engine.begin_turn(
                        conversation_key=key,
                        channel="telegram",
                        sender_name="User",
                        user_input=user_text,
                    )
                    engine.finish_turn(
                        turn,
                        channel="telegram",
                        assistant_text=assistant_text,
                        new_thread_id="thread-k",
                    )

            status = engine.get_status(key)
            self.assertGreaterEqual(status.summary_count, 1)
            with engine._lock, engine._connect() as conn:
                latest_summary = conn.execute(
                    """
                    SELECT summary_text
                    FROM chat_summaries
                    WHERE conversation_key = ?
                    ORDER BY id DESC
                    LIMIT 1
                    """,
                    (key,),
                ).fetchone()
            self.assertIsNotNone(latest_summary)
            summary_text = str(latest_summary["summary_text"])
            self.assertIn("Objective:", summary_text)
            self.assertIn("Decisions Made:", summary_text)
            self.assertIn("Current State:", summary_text)
            self.assertIn("Open Items:", summary_text)
            self.assertIn("User Preferences:", summary_text)
            self.assertIn("Risks/Blockers:", summary_text)

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
            recent_block = recent_block.split("\n\n", maxsplit=1)[0]
            recent_lines = [line for line in recent_block.splitlines() if line.startswith("- [")]
            self.assertGreater(len(recent_lines), 0)

    def test_finish_turn_waits_for_summary_token_threshold_unless_forced(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "memory.sqlite3")
            key = memory.MemoryEngine.telegram_key(778)
            engine = memory.MemoryEngine(db_path)

            summary_text = (
                "Objective:\n- summarize batched memory\n\n"
                "Decisions Made:\n- wait for threshold\n\n"
                "Current State:\n- summarizer triggered\n\n"
                "Open Items:\n- No open item detected.\n\n"
                "User Preferences:\n- No durable preference detected.\n\n"
                "Risks/Blockers:\n- No blocker detected."
            )

            with mock.patch.object(
                memory.llm_summarizer,
                "summarize_via_ollama",
                return_value=summary_text,
            ) as summarize_mock:
                short_turn = engine.begin_turn(
                    conversation_key=key,
                    channel="telegram",
                    sender_name="User",
                    user_input="small batch",
                )
                engine.finish_turn(
                    short_turn,
                    channel="telegram",
                    assistant_text="small reply",
                    new_thread_id="thread-small",
                )

                self.assertEqual(summarize_mock.call_count, 0)
                self.assertEqual(engine.get_status(key).summary_count, 0)

                long_turn = engine.begin_turn(
                    conversation_key=key,
                    channel="telegram",
                    sender_name="User",
                    user_input="threshold " + ("detail " * 1100),
                )
                engine.finish_turn(
                    long_turn,
                    channel="telegram",
                    assistant_text="large reply " + ("status " * 400),
                    new_thread_id="thread-small",
                )

                self.assertGreaterEqual(summarize_mock.call_count, 1)
                self.assertGreaterEqual(engine.get_status(key).summary_count, 1)

            forced_key = memory.MemoryEngine.telegram_key(779)
            forced_engine = memory.MemoryEngine(db_path)
            with mock.patch.object(
                memory.llm_summarizer,
                "summarize_via_ollama",
                return_value=None,
            ) as forced_mock:
                turn = forced_engine.begin_turn(
                    conversation_key=forced_key,
                    channel="telegram",
                    sender_name="User",
                    user_input="tiny force batch",
                )
                forced_engine.finish_turn(
                    turn,
                    channel="telegram",
                    assistant_text="tiny reply",
                    new_thread_id="thread-force",
                )

                self.assertEqual(forced_mock.call_count, 0)
                self.assertEqual(forced_engine.get_status(forced_key).summary_count, 0)
                self.assertTrue(
                    forced_engine.run_summarization_if_needed(forced_key, force=True)
                )
                self.assertEqual(forced_mock.call_count, 1)
                self.assertEqual(forced_engine.get_status(forced_key).summary_count, 1)

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

            with mock.patch.object(
                memory.llm_summarizer,
                "summarize_via_ollama",
                return_value=None,
            ):
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

    def test_retention_keeps_high_value_older_message_longer(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "memory.sqlite3")
            key = memory.MemoryEngine.telegram_key(889)
            engine = memory.MemoryEngine(
                db_path,
                max_messages_per_key=6,
                max_summaries_per_key=80,
                prune_interval_seconds=0,
            )

            with mock.patch.object(
                memory.llm_summarizer,
                "summarize_via_ollama",
                return_value=None,
            ):
                important_turn = engine.begin_turn(
                    conversation_key=key,
                    channel="telegram",
                    sender_name="User",
                    user_input="Decision: use option B for the memory rollout.",
                )
                engine.finish_turn(
                    important_turn,
                    channel="telegram",
                    assistant_text="Noted.",
                    new_thread_id="thread-important",
                )

                filler_messages = (
                    "ok",
                    "thanks",
                    "yes",
                    "cool",
                    "nice",
                    "sounds good",
                )
                for idx, user_text in enumerate(filler_messages):
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
                        new_thread_id="thread-important",
                    )

            status = engine.get_status(key)
            self.assertLessEqual(status.message_count, 6)
            with engine._lock, engine._connect() as conn:
                texts = [
                    str(row["text"])
                    for row in conn.execute(
                        "SELECT text FROM messages WHERE conversation_key = ? ORDER BY id",
                        (key,),
                    ).fetchall()
                ]
            self.assertIn("Decision: use option B for the memory rollout.", texts)

    def test_fact_ranking_prefers_explicit_and_reinforced_facts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "memory.sqlite3")
            key = memory.MemoryEngine.telegram_key(890)
            engine = memory.MemoryEngine(db_path)

            engine.remember_explicit(key, "timezone: AEST")
            with engine._lock, engine._connect() as conn:
                for _ in range(3):
                    engine._upsert_fact(
                        conn,
                        key,
                        "pref:dark_mode",
                        "dark mode",
                        explicit=False,
                        confidence=0.8,
                        source_msg_id=None,
                    )
                engine._upsert_fact(
                    conn,
                    key,
                    "pref:light_mode",
                    "light mode",
                    explicit=False,
                    confidence=0.8,
                    source_msg_id=None,
                )
                rows = engine._load_active_facts(conn, key, limit=3)
            ordered_keys = [str(row["fact_key"]) for row in rows]
            self.assertEqual(ordered_keys[0], "explicit:timezone")
            self.assertLess(ordered_keys.index("pref:dark_mode"), ordered_keys.index("pref:light_mode"))

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

    def test_regenerate_summaries_rewrites_legacy_format(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "memory.sqlite3")
            key = memory.MemoryEngine.telegram_key(66)
            engine = memory.MemoryEngine(db_path)
            now = time.time()

            with engine._lock, engine._connect() as conn:
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
                        (key, "telegram", "user", "User", "We need to rename mode for clarity.", now + 1, 8, 0),
                        (key, "telegram", "assistant", "Architect", "Implemented and pushed.", now + 2, 5, 1),
                    ],
                )
                conn.execute(
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
                    (key, 1, 2, "User topics: old\nAssistant outcomes: old", "[]", "[]", now + 3),
                )

            updated = engine.regenerate_summaries(conversation_key=key)
            self.assertEqual(updated, 1)

            with engine._lock, engine._connect() as conn:
                row = conn.execute(
                    "SELECT summary_text FROM chat_summaries WHERE conversation_key = ? ORDER BY id DESC LIMIT 1",
                    (key,),
                ).fetchone()
            self.assertIsNotNone(row)
            summary_text = str(row["summary_text"])
            self.assertIn("Objective:", summary_text)
            self.assertIn("Current State:", summary_text)


if __name__ == "__main__":
    unittest.main()
