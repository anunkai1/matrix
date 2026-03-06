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
