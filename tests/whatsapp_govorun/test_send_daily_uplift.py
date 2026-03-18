import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "ops" / "whatsapp_govorun" / "send_daily_uplift.py"

spec = importlib.util.spec_from_file_location("send_daily_uplift", MODULE_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError("Failed to load send_daily_uplift module")
uplift = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = uplift
spec.loader.exec_module(uplift)


class SendDailyUpliftTests(unittest.TestCase):
    def test_build_daily_message_keeps_fixed_wrapper(self):
        message = uplift.build_daily_message("Путиловы", "Поставьте ложку в банку с мёдом, чтобы край не лип.")
        self.assertEqual(
            message,
            "Доброе утро, Путиловы! ☀️\n\nДаю справку: Поставьте ложку в банку с мёдом, чтобы край не лип.",
        )

    def test_parse_generated_life_hack_rejects_wrapper_text(self):
        with self.assertRaises(RuntimeError):
            uplift.parse_generated_life_hack(
                '{"hack_text":"Доброе утро, Путиловы!","idea_key":"ложка в меде","idea_summary":"ложка не дает липнуть меду"}'
            )

    def test_find_similarity_match_rejects_similar_underlying_life_hack(self):
        entry = uplift.HistoryEntry(
            id=1,
            sent_at="2026-03-18T09:00:00+10:00",
            message_text="Доброе утро, Путиловы! ☀️\n\nДаю справку: Кладите деревянную ложку поперек кастрюли, чтобы пена не убегала.",
            hack_text="Кладите деревянную ложку поперек кастрюли, чтобы пена не убегала.",
            idea_key="деревянная ложка против убегающей пены",
            idea_summary="Деревянная ложка на кастрюле помогает сдержать пену при закипании.",
            message_probe=uplift.normalize_probe("Доброе утро, Путиловы! ☀️\n\nДаю справку: Кладите деревянную ложку поперек кастрюли, чтобы пена не убегала."),
            hack_probe=uplift.normalize_probe("Кладите деревянную ложку поперек кастрюли, чтобы пена не убегала."),
            idea_key_probe=uplift.normalize_probe("деревянная ложка против убегающей пены"),
            idea_summary_probe=uplift.normalize_probe("Деревянная ложка на кастрюле помогает сдержать пену при закипании."),
        )
        candidate = uplift.GeneratedLifeHack(
            hack_text="Если молоко вот-вот убежит, положите деревянную ложку сверху кастрюли: она помогает сбить пену.",
            idea_key="ложка на кастрюле от пены",
            idea_summary="Положите деревянную ложку поперек кастрюли, чтобы молочная пена не так быстро убегала.",
        )
        match = uplift.find_similarity_match(candidate, [entry])
        self.assertIsNotNone(match)
        assert match is not None
        self.assertGreaterEqual(match.score, 0.66)

    def test_history_store_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = uplift.HistoryStore(Path(tmp_dir) / "history.sqlite3")
            sent_at = uplift.now_in_tz("Australia/Brisbane")
            store.insert_sent_message(
                sent_at,
                uplift.SentLifeHack(
                    message_text="Доброе утро, Путиловы! ☀️\n\nДаю справку: Храните зелень в банке с крышкой и салфеткой, чтобы она дольше оставалась сухой.",
                    hack_text="Храните зелень в банке с крышкой и салфеткой, чтобы она дольше оставалась сухой.",
                    idea_key="зелень в банке с салфеткой",
                    idea_summary="Салфетка в закрытой банке помогает зелени дольше оставаться свежей.",
                ),
            )
            entries = store.load_entries()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].idea_key, "зелень в банке с салфеткой")

    def test_legacy_history_entries_seed_old_life_hacks(self):
        entries = uplift.legacy_history_entries("Путиловы")
        self.assertGreaterEqual(len(entries), 2)
        self.assertTrue(any("широкая кружка" in entry.idea_key for entry in entries))


if __name__ == "__main__":
    unittest.main()
