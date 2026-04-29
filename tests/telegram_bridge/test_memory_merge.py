import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / 'src' / 'telegram_bridge' / 'memory_merge.py'
MODULE_DIR = MODULE_PATH.parent

spec = importlib.util.spec_from_file_location('bridge_memory_merge', MODULE_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError('Failed to load memory merge module spec')
module = importlib.util.module_from_spec(spec)
import sys
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))
sys.modules[spec.name] = module
spec.loader.exec_module(module)

from memory_engine import MemoryEngine


class MemoryMergeTests(unittest.TestCase):
    def test_merge_conversation_keys_copies_messages_and_facts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / 'memory.sqlite3')
            engine = MemoryEngine(db_path)
            for key, channel in (
                ('tg:1', 'telegram'),
                ('tg:2', 'telegram'),
                ('cli:architect:default', 'cli'),
            ):
                turn = engine.begin_turn(
                    conversation_key=key,
                    channel=channel,
                    sender_name='User',
                    user_input=f'hello from {key}',
                )
                engine.finish_turn(turn, channel=channel, assistant_text='ack', new_thread_id=f'thread-{key}')
            engine.remember_explicit('tg:1', 'timezone: AEST')
            engine.remember_explicit('tg:2', 'timezone: UTC')
            result = module.merge_conversation_keys(
                db_path=db_path,
                source_keys=['tg:1', 'tg:2', 'cli:architect:default'],
                target_key='shared:architect:main',
            )
            status = engine.get_status('shared:architect:main')
            self.assertEqual(result.messages_copied, 6)
            self.assertEqual(result.facts_merged, 1)
            self.assertEqual(status.message_count, 6)
            self.assertFalse(status.session_active)

    def test_merge_requires_empty_target_unless_overwrite_enabled(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / 'memory.sqlite3')
            engine = MemoryEngine(db_path)
            turn = engine.begin_turn(
                conversation_key='tg:1',
                channel='telegram',
                sender_name='User',
                user_input='hello',
            )
            engine.finish_turn(turn, channel='telegram', assistant_text='ack', new_thread_id='thread-a')
            turn = engine.begin_turn(
                conversation_key='shared:architect:main',
                channel='cli',
                sender_name='User',
                user_input='existing',
            )
            engine.finish_turn(turn, channel='cli', assistant_text='ack', new_thread_id='thread-b')
            with self.assertRaises(ValueError):
                module.merge_conversation_keys(
                    db_path=db_path,
                    source_keys=['tg:1'],
                    target_key='shared:architect:main',
                )

    def test_merge_can_append_into_existing_target_without_resetting_target_session(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / 'memory.sqlite3')
            engine = MemoryEngine(db_path)

            source_turn = engine.begin_turn(
                conversation_key='shared:architect:main:session:tg:1',
                channel='telegram',
                sender_name='User',
                user_input='source message',
            )
            engine.finish_turn(
                source_turn,
                channel='telegram',
                assistant_text='source reply',
                new_thread_id='thread-source',
            )
            engine.remember_explicit('shared:architect:main:session:tg:1', 'topic: source')

            target_turn = engine.begin_turn(
                conversation_key='shared:architect:main',
                channel='cli',
                sender_name='CLI User',
                user_input='archive seed',
            )
            engine.finish_turn(
                target_turn,
                channel='cli',
                assistant_text='archive reply',
                new_thread_id='thread-archive',
            )

            result = module.merge_conversation_keys(
                db_path=db_path,
                source_keys=['shared:architect:main:session:tg:1'],
                target_key='shared:architect:main',
                allow_existing_target=True,
                force_summarize_target=True,
            )

            status = engine.get_status('shared:architect:main')
            self.assertEqual(engine.get_session_thread_id('shared:architect:main'), 'thread-archive')
            self.assertEqual(result.messages_copied, 2)
            self.assertGreaterEqual(status.summary_count, 1)
            facts = engine.export_facts('shared:architect:main')
            self.assertEqual(len([row for row in facts if row['status'] == 'active']), 1)

    def test_merge_can_filter_low_value_messages_for_shared_archive(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / 'memory.sqlite3')
            engine = MemoryEngine(db_path)
            key = 'shared:architect:main:session:tg:9'

            for user_text, assistant_text in (
                ('ok', 'thanks'),
                ('Decision: switch to option B.', 'I will use option B.'),
            ):
                turn = engine.begin_turn(
                    conversation_key=key,
                    channel='telegram',
                    sender_name='User',
                    user_input=user_text,
                )
                engine.finish_turn(
                    turn,
                    channel='telegram',
                    assistant_text=assistant_text,
                    new_thread_id='thread-9',
                )

            result = module.merge_conversation_keys(
                db_path=db_path,
                source_keys=[key],
                target_key='shared:architect:main',
                min_message_score=0.75,
            )

            self.assertEqual(result.messages_copied, 2)
            with engine._lock, engine._connect() as conn:
                texts = [
                    str(row['text'])
                    for row in conn.execute(
                        "SELECT text FROM messages WHERE conversation_key = ? ORDER BY id",
                        ('shared:architect:main',),
                    ).fetchall()
                ]
            self.assertIn('Decision: switch to option B.', texts)
            self.assertIn('I will use option B.', texts)
            self.assertNotIn('ok', texts)
            self.assertNotIn('thanks', texts)
