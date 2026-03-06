import importlib.util
import unittest
from pathlib import Path
from types import SimpleNamespace

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
    def test_build_conversation_key_defaults_to_cli_namespace(self):
        args = SimpleNamespace(
            conversation_key='',
            profile='default',
            memory_namespace='architect',
        )
        self.assertEqual(module.build_conversation_key(args), 'cli:architect:default')

    def test_build_conversation_key_respects_explicit_override(self):
        args = SimpleNamespace(
            conversation_key='shared:architect:main',
            profile='ignored',
            memory_namespace='ignored',
        )
        self.assertEqual(module.build_conversation_key(args), 'shared:architect:main')
