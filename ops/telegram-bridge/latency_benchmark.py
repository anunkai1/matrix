#!/usr/bin/env python3
"""Deterministic latency benchmark harness for the shared Telegram bridge.

This replays a fixed corpus of Telegram-like updates through the real
``handle_update`` path while replacing the executor with a deterministic mock
engine. The goal is to measure bridge overhead and reply timing on the same
machine with the same corpus over repeated runs.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import statistics
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Iterable, List, Optional


REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

import telegram_bridge.handlers as bridge_handlers
import telegram_bridge.auth_state as bridge_auth_state
import telegram_bridge.state_store as bridge_state_store


CHUNK_PREFIX_RE = re.compile(r"^\[\d+/\d+\]\n", re.MULTILINE)


@dataclass(frozen=True)
class BenchmarkCase:
    name: str
    prompt: str
    expected_reply: str
    engine_output: str
    engine_delay_ms: float = 0.0
    chat_id: int = 1
    actor_user_id: int = 1001
    chat_type: str = "private"
    message_thread_id: Optional[int] = None

    @classmethod
    def from_dict(cls, payload: Dict[str, object]) -> "BenchmarkCase":
        if not isinstance(payload, dict):
            raise ValueError(f"Benchmark case must be an object, got {type(payload).__name__}")
        name = str(payload.get("name") or "").strip()
        prompt = str(payload.get("prompt") or "").strip()
        if not name:
            raise ValueError("Benchmark case is missing a non-empty 'name'")
        if not prompt:
            raise ValueError(f"Benchmark case {name!r} is missing a non-empty 'prompt'")
        expected_reply = str(payload.get("expected_reply") or "").strip()
        if not expected_reply:
            raise ValueError(f"Benchmark case {name!r} is missing 'expected_reply'")
        engine_output = str(payload.get("engine_output") or expected_reply).strip()
        raw_delay = payload.get("engine_delay_ms", 0.0)
        try:
            engine_delay_ms = float(raw_delay)
        except Exception as exc:
            raise ValueError(
                f"Benchmark case {name!r} has invalid engine_delay_ms={raw_delay!r}"
            ) from exc
        if engine_delay_ms < 0:
            raise ValueError(f"Benchmark case {name!r} has negative engine_delay_ms")
        chat_id = int(payload.get("chat_id", 1))
        actor_user_id = int(payload.get("actor_user_id", 1001))
        chat_type = str(payload.get("chat_type") or "private").strip() or "private"
        raw_thread_id = payload.get("message_thread_id")
        message_thread_id = int(raw_thread_id) if isinstance(raw_thread_id, int) else None
        return cls(
            name=name,
            prompt=prompt,
            expected_reply=expected_reply,
            engine_output=engine_output,
            engine_delay_ms=engine_delay_ms,
            chat_id=chat_id,
            actor_user_id=actor_user_id,
            chat_type=chat_type,
            message_thread_id=message_thread_id,
        )


@dataclass(frozen=True)
class SampleResult:
    case_name: str
    total_ms: float
    time_to_progress_ms: Optional[float]
    time_to_final_reply_ms: Optional[float]
    engine_ms: float
    bridge_overhead_ms: float
    reply_chars: int
    send_count: int


class BenchmarkClient:
    channel_name = "telegram"
    supports_message_edits = False

    def __init__(self) -> None:
        self.progress_messages: List[Dict[str, object]] = []
        self.messages: List[Dict[str, object]] = []
        self.photos: List[Dict[str, object]] = []
        self.documents: List[Dict[str, object]] = []
        self.audios: List[Dict[str, object]] = []
        self.voices: List[Dict[str, object]] = []
        self.chat_actions: List[Dict[str, object]] = []

    def send_message_get_id(
        self,
        chat_id,
        text,
        reply_to_message_id=None,
        message_thread_id=None,
    ):
        self.progress_messages.append(
            {
                "ts": time.perf_counter(),
                "chat_id": chat_id,
                "text": text,
                "reply_to_message_id": reply_to_message_id,
                "message_thread_id": message_thread_id,
            }
        )
        return len(self.progress_messages)

    def send_message(self, chat_id, text, reply_to_message_id=None, message_thread_id=None):
        self.messages.append(
            {
                "ts": time.perf_counter(),
                "chat_id": chat_id,
                "text": text,
                "reply_to_message_id": reply_to_message_id,
                "message_thread_id": message_thread_id,
            }
        )

    def send_photo(
        self,
        chat_id,
        photo,
        caption=None,
        reply_to_message_id=None,
        message_thread_id=None,
    ):
        self.photos.append(
            {
                "ts": time.perf_counter(),
                "chat_id": chat_id,
                "photo": photo,
                "caption": caption,
                "reply_to_message_id": reply_to_message_id,
                "message_thread_id": message_thread_id,
            }
        )

    def send_document(
        self,
        chat_id,
        document,
        caption=None,
        reply_to_message_id=None,
        message_thread_id=None,
    ):
        self.documents.append(
            {
                "ts": time.perf_counter(),
                "chat_id": chat_id,
                "document": document,
                "caption": caption,
                "reply_to_message_id": reply_to_message_id,
                "message_thread_id": message_thread_id,
            }
        )

    def send_audio(
        self,
        chat_id,
        audio,
        caption=None,
        reply_to_message_id=None,
        message_thread_id=None,
    ):
        self.audios.append(
            {
                "ts": time.perf_counter(),
                "chat_id": chat_id,
                "audio": audio,
                "caption": caption,
                "reply_to_message_id": reply_to_message_id,
                "message_thread_id": message_thread_id,
            }
        )

    def send_voice(
        self,
        chat_id,
        voice,
        caption=None,
        reply_to_message_id=None,
        message_thread_id=None,
    ):
        self.voices.append(
            {
                "ts": time.perf_counter(),
                "chat_id": chat_id,
                "voice": voice,
                "caption": caption,
                "reply_to_message_id": reply_to_message_id,
                "message_thread_id": message_thread_id,
            }
        )

    def send_chat_action(self, chat_id, action="typing", message_thread_id=None):
        self.chat_actions.append(
            {
                "ts": time.perf_counter(),
                "chat_id": chat_id,
                "action": action,
                "message_thread_id": message_thread_id,
            }
        )


class DeterministicEngineAdapter:
    engine_name = "benchmark_mock"

    def __init__(self, case: BenchmarkCase) -> None:
        self.case = case
        self.last_duration_ms = 0.0

    def run(
        self,
        config,
        prompt: str,
        thread_id: Optional[str],
        session_key: Optional[str] = None,
        channel_name: Optional[str] = None,
        actor_chat_id: Optional[int] = None,
        actor_user_id: Optional[int] = None,
        image_path: Optional[str] = None,
        image_paths: Optional[List[str]] = None,
        progress_callback=None,
        cancel_event=None,
    ) -> subprocess.CompletedProcess[str]:
        del config, prompt, thread_id, session_key, channel_name, actor_chat_id, actor_user_id
        del image_path, image_paths, progress_callback, cancel_event
        start = time.perf_counter()
        if self.case.engine_delay_ms > 0:
            time.sleep(self.case.engine_delay_ms / 1000.0)
        self.last_duration_ms = (time.perf_counter() - start) * 1000.0
        stdout = f"THREAD_ID=benchmark-thread\nOUTPUT_BEGIN\n{self.case.engine_output}"
        return subprocess.CompletedProcess(
            args=["benchmark_mock"],
            returncode=0,
            stdout=stdout,
            stderr="",
        )


def build_benchmark_config(state_dir: str):
    return SimpleNamespace(
        token="benchmark-token",
        allowed_chat_ids={1, 2, 3, 4, 5, 999},
        api_base="https://api.telegram.org",
        poll_timeout_seconds=1,
        retry_sleep_seconds=0.1,
        exec_timeout_seconds=5,
        max_input_chars=4096,
        max_output_chars=20000,
        max_image_bytes=4096,
        max_voice_bytes=4096,
        max_document_bytes=4096,
        attachment_retention_seconds=14 * 24 * 60 * 60,
        attachment_max_total_bytes=10 * 1024 * 1024,
        rate_limit_per_minute=1000,
        executor_cmd=["/bin/echo"],
        voice_transcribe_cmd=[],
        voice_transcribe_timeout_seconds=10,
        voice_not_configured_message="Voice transcription is not configured.",
        voice_download_error_message="Voice download failed.",
        voice_transcribe_error_message="Voice transcription failed.",
        voice_transcribe_empty_message="Voice transcription was empty.",
        image_download_error_message="Image download failed.",
        document_download_error_message="Document download failed.",
        voice_alias_replacements=[],
        voice_alias_learning_enabled=False,
        voice_alias_learning_path=str(Path(state_dir) / "voice_alias_learning.json"),
        voice_alias_learning_min_examples=2,
        voice_alias_learning_confirmation_window_seconds=900,
        voice_low_confidence_confirmation_enabled=False,
        voice_low_confidence_threshold=0.45,
        voice_low_confidence_message="Voice transcript confidence is low, resend.",
        state_dir=state_dir,
        persistent_workers_enabled=False,
        persistent_workers_max=2,
        persistent_workers_idle_timeout_seconds=120,
        persistent_workers_policy_files=[],
        canonical_sessions_enabled=False,
        canonical_legacy_mirror_enabled=False,
        canonical_sqlite_enabled=False,
        canonical_sqlite_path=str(Path(state_dir) / "chat_sessions.sqlite3"),
        canonical_json_mirror_enabled=False,
        memory_sqlite_path=str(Path(state_dir) / "memory.sqlite3"),
        memory_max_messages_per_key=4000,
        memory_max_summaries_per_key=80,
        memory_prune_interval_seconds=300,
        required_prefixes=[],
        required_prefix_ignore_case=True,
        require_prefix_in_private=True,
        allow_private_chats_unlisted=False,
        allow_group_chats_unlisted=False,
        assistant_name="AgentSmith",
        shared_memory_key="",
        channel_plugin="telegram",
        engine_plugin="codex",
        whatsapp_plugin_enabled=False,
        whatsapp_bridge_api_base="http://127.0.0.1:8787",
        whatsapp_bridge_auth_token="",
        whatsapp_poll_timeout_seconds=20,
        signal_plugin_enabled=False,
        signal_bridge_api_base="http://127.0.0.1:18797",
        signal_bridge_auth_token="",
        signal_poll_timeout_seconds=20,
        keyword_routing_enabled=True,
        diary_mode_enabled=False,
        diary_capture_quiet_window_seconds=75,
        diary_timezone="Australia/Brisbane",
        diary_local_root=str(Path(state_dir) / "diary"),
        diary_nextcloud_enabled=False,
        denied_message="This chat is not allowed.",
        busy_message="Busy. Please wait.",
        timeout_message="Timed out.",
        generic_error_message="Something went wrong.",
        empty_output_message="(empty output)",
        progress_label="",
        progress_elapsed_prefix="Already",
        progress_elapsed_suffix="s",
    )


def load_corpus(path: Path) -> List[BenchmarkCase]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("Benchmark corpus root must be a JSON array")
    cases = [BenchmarkCase.from_dict(item) for item in payload]
    if not cases:
        raise ValueError("Benchmark corpus must contain at least one case")
    return cases


def percentile(values: Iterable[float], q: float) -> float:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        raise ValueError("Cannot compute percentile of empty sequence")
    if len(ordered) == 1:
        return ordered[0]
    position = max(0.0, min(1.0, q)) * (len(ordered) - 1)
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] + ((ordered[upper] - ordered[lower]) * fraction)


def summarize_metric(values: Iterable[float]) -> Dict[str, float]:
    numbers = [float(value) for value in values]
    if not numbers:
        return {"avg": 0.0, "min": 0.0, "max": 0.0, "p50": 0.0, "p95": 0.0}
    return {
        "avg": statistics.fmean(numbers),
        "min": min(numbers),
        "max": max(numbers),
        "p50": percentile(numbers, 0.50),
        "p95": percentile(numbers, 0.95),
    }


def build_update(case: BenchmarkCase, update_id: int, message_id: int) -> Dict[str, object]:
    message: Dict[str, object] = {
        "message_id": message_id,
        "date": 0,
        "chat": {"id": case.chat_id, "type": case.chat_type},
        "from": {"id": case.actor_user_id, "first_name": "Benchmark"},
        "text": case.prompt,
    }
    if case.message_thread_id is not None:
        message["message_thread_id"] = case.message_thread_id
    return {"update_id": update_id, "message": message}


def normalize_delivered_text(parts: List[str]) -> str:
    joined = "\n".join(part for part in parts if part)
    return CHUNK_PREFIX_RE.sub("", joined).strip()


@contextmanager
def synchronous_worker_mode():
    original_start_message_worker = bridge_handlers.start_message_worker
    original_start_youtube_worker = bridge_handlers.start_youtube_worker

    def sync_start_message_worker(*args, **kwargs):
        return bridge_handlers.process_message_worker(*args, **kwargs)

    def sync_start_youtube_worker(*args, **kwargs):
        return bridge_handlers.process_youtube_worker(*args, **kwargs)

    bridge_handlers.start_message_worker = sync_start_message_worker
    bridge_handlers.start_youtube_worker = sync_start_youtube_worker
    try:
        yield
    finally:
        bridge_handlers.start_message_worker = original_start_message_worker
        bridge_handlers.start_youtube_worker = original_start_youtube_worker


def run_case_once(
    case: BenchmarkCase,
    *,
    iteration: int,
    base_config,
) -> SampleResult:
    config = SimpleNamespace(**vars(base_config))
    config.allowed_chat_ids = set(getattr(base_config, "allowed_chat_ids", set())) | {case.chat_id}
    state = bridge_state_store.State()
    state.auth_fingerprint = bridge_auth_state.compute_current_auth_fingerprint()
    state.auth_fingerprint_path = str(Path(config.state_dir) / "auth_fingerprint.txt")
    client = BenchmarkClient()
    engine = DeterministicEngineAdapter(case)
    update = build_update(case, update_id=iteration + 1, message_id=(iteration + 1) * 100)
    started_at = time.perf_counter()
    with synchronous_worker_mode():
        bridge_handlers.handle_update(state, config, client, update, engine=engine)
    finished_at = time.perf_counter()
    delivered_text = normalize_delivered_text(
        [str(message["text"]) for message in client.messages if isinstance(message.get("text"), str)]
    )
    if delivered_text != case.expected_reply:
        raise ValueError(
            f"Benchmark case {case.name!r} produced unexpected reply.\n"
            f"expected: {case.expected_reply!r}\n"
            f"actual:   {delivered_text!r}"
        )

    progress_ms: Optional[float] = None
    if client.progress_messages:
        progress_ms = (client.progress_messages[0]["ts"] - started_at) * 1000.0

    final_reply_ms: Optional[float] = None
    if client.messages:
        final_reply_ms = (client.messages[-1]["ts"] - started_at) * 1000.0

    total_ms = (finished_at - started_at) * 1000.0
    return SampleResult(
        case_name=case.name,
        total_ms=total_ms,
        time_to_progress_ms=progress_ms,
        time_to_final_reply_ms=final_reply_ms,
        engine_ms=engine.last_duration_ms,
        bridge_overhead_ms=max(0.0, total_ms - engine.last_duration_ms),
        reply_chars=len(delivered_text),
        send_count=len(client.messages),
    )


def run_benchmark(
    cases: List[BenchmarkCase],
    *,
    iterations: int,
) -> Dict[str, object]:
    if iterations <= 0:
        raise ValueError("iterations must be >= 1")
    with tempfile.TemporaryDirectory(prefix="telegram-bridge-bench-") as state_dir:
        config = build_benchmark_config(state_dir)
        samples: List[SampleResult] = []
        per_case: Dict[str, List[SampleResult]] = {}
        for case in cases:
            for iteration in range(iterations):
                result = run_case_once(case, iteration=iteration, base_config=config)
                samples.append(result)
                per_case.setdefault(case.name, []).append(result)

    def collect(metric_name: str, subset: List[SampleResult]) -> Dict[str, float]:
        values = [
            float(value)
            for value in (
                getattr(sample, metric_name)
                for sample in subset
            )
            if value is not None
        ]
        return summarize_metric(values)

    per_case_summary: Dict[str, object] = {}
    for case_name, case_samples in per_case.items():
        per_case_summary[case_name] = {
            "samples": len(case_samples),
            "time_to_progress_ms": collect("time_to_progress_ms", case_samples),
            "time_to_final_reply_ms": collect("time_to_final_reply_ms", case_samples),
            "total_ms": collect("total_ms", case_samples),
            "engine_ms": collect("engine_ms", case_samples),
            "bridge_overhead_ms": collect("bridge_overhead_ms", case_samples),
            "avg_reply_chars": statistics.fmean(sample.reply_chars for sample in case_samples),
            "avg_send_count": statistics.fmean(sample.send_count for sample in case_samples),
        }

    return {
        "cases": len(cases),
        "iterations_per_case": iterations,
        "total_samples": len(samples),
        "overall": {
            "time_to_progress_ms": collect("time_to_progress_ms", samples),
            "time_to_final_reply_ms": collect("time_to_final_reply_ms", samples),
            "total_ms": collect("total_ms", samples),
            "engine_ms": collect("engine_ms", samples),
            "bridge_overhead_ms": collect("bridge_overhead_ms", samples),
            "avg_reply_chars": statistics.fmean(sample.reply_chars for sample in samples),
            "avg_send_count": statistics.fmean(sample.send_count for sample in samples),
        },
        "per_case": per_case_summary,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a deterministic latency benchmark for the shared Telegram bridge."
    )
    parser.add_argument(
        "--corpus",
        required=True,
        help="Path to a JSON corpus file containing benchmark cases.",
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=10,
        help="How many times to replay each case. Default: 10.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON instead of human text.",
    )
    return parser


def render_text_report(summary: Dict[str, object]) -> str:
    overall = summary["overall"]
    lines = [
        "Telegram Bridge Latency Benchmark",
        f"Cases: {summary['cases']}",
        f"Iterations per case: {summary['iterations_per_case']}",
        f"Total samples: {summary['total_samples']}",
        "",
        "Overall",
        (
            "  final reply ms: "
            f"p50={overall['time_to_final_reply_ms']['p50']:.2f} "
            f"p95={overall['time_to_final_reply_ms']['p95']:.2f} "
            f"avg={overall['time_to_final_reply_ms']['avg']:.2f}"
        ),
        (
            "  progress ms: "
            f"p50={overall['time_to_progress_ms']['p50']:.2f} "
            f"p95={overall['time_to_progress_ms']['p95']:.2f} "
            f"avg={overall['time_to_progress_ms']['avg']:.2f}"
        ),
        (
            "  total ms: "
            f"p50={overall['total_ms']['p50']:.2f} "
            f"p95={overall['total_ms']['p95']:.2f} "
            f"avg={overall['total_ms']['avg']:.2f}"
        ),
        (
            "  engine ms: "
            f"p50={overall['engine_ms']['p50']:.2f} "
            f"p95={overall['engine_ms']['p95']:.2f} "
            f"avg={overall['engine_ms']['avg']:.2f}"
        ),
        (
            "  bridge overhead ms: "
            f"p50={overall['bridge_overhead_ms']['p50']:.2f} "
            f"p95={overall['bridge_overhead_ms']['p95']:.2f} "
            f"avg={overall['bridge_overhead_ms']['avg']:.2f}"
        ),
        "",
        "Per case",
    ]
    for case_name, case_summary in summary["per_case"].items():
        lines.append(
            (
                f"  {case_name}: final_reply_p50={case_summary['time_to_final_reply_ms']['p50']:.2f} "
                f"final_reply_p95={case_summary['time_to_final_reply_ms']['p95']:.2f} "
                f"overhead_p50={case_summary['bridge_overhead_ms']['p50']:.2f} "
                f"samples={case_summary['samples']}"
            )
        )
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    corpus_path = Path(args.corpus).resolve()
    cases = load_corpus(corpus_path)
    summary = run_benchmark(cases, iterations=args.iterations)
    if args.json:
        print(json.dumps(summary, indent=2, sort_keys=True))
    else:
        print(render_text_report(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
