import importlib.util
import json
import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "ops" / "telegram-bridge" / "latency_benchmark.py"

spec = importlib.util.spec_from_file_location("telegram_bridge_latency_benchmark", MODULE_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError("Failed to load latency benchmark module")
latency_benchmark = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = latency_benchmark
spec.loader.exec_module(latency_benchmark)


class TelegramBridgeLatencyBenchmarkTests(unittest.TestCase):
    def test_run_benchmark_reports_summary(self) -> None:
        cases = [
            latency_benchmark.BenchmarkCase(
                name="fast_case",
                prompt="Hello",
                expected_reply="Reply one.",
                engine_output="Reply one.",
                engine_delay_ms=1,
            ),
            latency_benchmark.BenchmarkCase(
                name="slow_case",
                prompt="Hello again",
                expected_reply="Reply two.",
                engine_output="Reply two.",
                engine_delay_ms=3,
            ),
        ]

        summary = latency_benchmark.run_benchmark(cases, iterations=3)

        self.assertEqual(summary["cases"], 2)
        self.assertEqual(summary["iterations_per_case"], 3)
        self.assertEqual(summary["total_samples"], 6)
        self.assertIn("fast_case", summary["per_case"])
        self.assertIn("slow_case", summary["per_case"])
        self.assertGreaterEqual(summary["overall"]["time_to_final_reply_ms"]["p50"], 0.0)
        self.assertGreaterEqual(summary["overall"]["bridge_overhead_ms"]["p50"], 0.0)

    def test_load_corpus_and_main_json_output(self) -> None:
        payload = [
            {
                "name": "json_case",
                "prompt": "Ping",
                "expected_reply": "Pong",
                "engine_output": "Pong",
                "engine_delay_ms": 0,
            }
        ]
        with tempfile.TemporaryDirectory() as tmp_dir:
            corpus_path = Path(tmp_dir) / "corpus.json"
            corpus_path.write_text(json.dumps(payload), encoding="utf-8")
            loaded = latency_benchmark.load_corpus(corpus_path)
            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded[0].name, "json_case")

            stdout_buffer = io.StringIO()
            with redirect_stdout(stdout_buffer):
                exit_code = latency_benchmark.main(
                    ["--corpus", str(corpus_path), "--iterations", "2", "--json"]
                )
            self.assertEqual(exit_code, 0)

    def test_run_case_once_rejects_output_mismatch(self) -> None:
        case = latency_benchmark.BenchmarkCase(
            name="bad_case",
            prompt="Hello",
            expected_reply="Expected",
            engine_output="Actual",
        )
        config = latency_benchmark.build_benchmark_config(tempfile.mkdtemp(prefix="bench-config-"))
        with self.assertRaises(ValueError):
            latency_benchmark.run_case_once(case, iteration=0, base_config=config)


if __name__ == "__main__":
    unittest.main()
