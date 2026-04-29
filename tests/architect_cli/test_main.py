import importlib.util
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / 'src' / 'architect_cli' / 'main.py'
MODULE_DIR = MODULE_PATH.parent

spec = importlib.util.spec_from_file_location('architect_cli_main', MODULE_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError('Failed to load architect CLI module spec')
module = importlib.util.module_from_spec(spec)
import sys
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))
spec.loader.exec_module(module)


class ArchitectCliMainTests(unittest.TestCase):
    def test_build_conversation_key_defaults_to_shared_archive(self):
        args = SimpleNamespace(
            conversation_key='',
            profile='default',
            memory_namespace='architect',
        )
        self.assertEqual(module.build_conversation_key(args), 'shared:architect:main')

    def test_build_conversation_key_respects_explicit_override(self):
        args = SimpleNamespace(
            conversation_key='shared:architect:main',
            profile='ignored',
            memory_namespace='ignored',
        )
        self.assertEqual(module.build_conversation_key(args), 'shared:architect:main')

    def test_main_routes_natural_language_memory_query_without_running_codex(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / 'memory.sqlite3')
            engine = module.MemoryEngine(db_path)
            key = 'shared:architect:main'

            for user_text in ('first note', 'second note'):
                turn = engine.begin_turn(
                    conversation_key=key,
                    channel='cli',
                    sender_name='CLI User',
                    user_input=user_text,
                )
                engine.finish_turn(
                    turn,
                    channel='cli',
                    assistant_text=f'reply to {user_text}',
                    new_thread_id='thread-cli',
                )

            args = SimpleNamespace(
                launcher_name='architect',
                assistant_name='Architect',
                memory_namespace='architect',
                profile='default',
                conversation_key='',
                state_dir=tmpdir,
                memory_db=db_path,
                timeout_seconds=30,
                codex_bin='codex',
            )

            with mock.patch.object(module, 'parse_args', return_value=args), \
                mock.patch.object(module, 'resolve_input', return_value='what were the last 2 messages i sent you?'), \
                mock.patch.object(module, 'run_codex') as run_codex, \
                mock.patch('builtins.print') as print_mock:
                rc = module.main()

            self.assertEqual(rc, 0)
            run_codex.assert_not_called()
            print_mock.assert_called_once()
            self.assertIn('Your last 2 messages in memory are:', print_mock.call_args[0][0])
