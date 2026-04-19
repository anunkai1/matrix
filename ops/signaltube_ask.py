#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.signaltube.browser_lab import BrowserBrainClient, extract_video_candidates
from src.signaltube.metadata import enrich_candidates_with_youtube_metadata
from src.signaltube.models import VideoCandidate
from src.signaltube.ranking import rank_candidates
from src.signaltube.render import render_feed
from src.signaltube.store import SignalTubeStore


ASK_TOPIC_PREFIX = "Ask:"
LEGACY_ASK_TOPIC = "Ask SignalTube"
DEFAULT_STATE = Path("private/signaltube/ask_state.json")
DEFAULT_DB = Path("private/signaltube/signaltube.sqlite")
DEFAULT_HTML = Path("private/signaltube/feed.html")
MAINSTREAM_CHANNEL_HINTS = {
    "abc news",
    "associated press",
    "bbc",
    "bloomberg",
    "cbs",
    "cnn",
    "dw news",
    "fox news",
    "guardian",
    "msnbc",
    "nbc",
    "pbs newshour",
    "reuters",
    "sky news",
    "the times",
    "wall street journal",
    "washington post",
}
VIEWPOINT_TERMS = {
    "iran": ["iran aligned", "iranian perspective", "press tv"],
    "china": ["china aligned", "chinese perspective", "cgtn"],
    "russia": ["russia aligned", "russian perspective", "rt"],
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="SignalTube conversational Ask scanner")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--html", type=Path, default=DEFAULT_HTML)
    parser.add_argument("--browser-brain-url", default="http://127.0.0.1:47832")
    parser.add_argument("--request-file", type=Path, required=True)
    parser.add_argument("--state-file", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--render-limit", type=int, default=200)
    parser.add_argument("--max-candidates-per-query", type=int, default=12)
    parser.add_argument("--skip-youtube-metadata", action="store_true")
    return parser


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    parsed = json.loads(path.read_text(encoding="utf-8") or "{}")
    if not isinstance(parsed, dict):
        return {}
    return parsed


def save_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def normalize_prompt(prompt: str) -> str:
    return re.sub(r"\s+", " ", prompt.strip())


def build_scan_plan(prompt: str, previous: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize_prompt(prompt)
    if not normalized:
        raise ValueError("prompt must not be empty")
    lower = normalized.lower()
    previous_focus = str(previous.get("focus") or "").strip()
    extracted_focus = extract_focus(normalized)
    if extracted_focus:
        focus = extracted_focus
    elif is_followup(lower) and previous_focus:
        focus = previous_focus
    elif previous_focus:
        focus = previous_focus
    else:
        focus = normalized

    remove_mainstream = bool(previous.get("remove_mainstream")) or (
        ("mainstream" in lower or "msm" in lower)
        and any(word in lower for word in ("remove", "less", "too much", "avoid", "no ", "not from"))
    )
    viewpoints = sorted({*previous.get("viewpoints", []), *extract_viewpoints(lower)})
    if "other side" in lower and not viewpoints:
        viewpoints = ["iran", "china", "russia"]
    if "mainstream" in lower and any(word in lower for word in ("ok", "now", "but")) and "remove" not in lower:
        remove_mainstream = bool(previous.get("remove_mainstream"))

    queries = build_queries(focus, remove_mainstream=remove_mainstream, viewpoints=viewpoints)
    return {
        "topic": ask_topic_for_focus(focus),
        "focus": focus,
        "prompt": normalized,
        "remove_mainstream": remove_mainstream,
        "viewpoints": viewpoints,
        "queries": queries,
    }


def ask_topic_for_focus(focus: str) -> str:
    compact = re.sub(r"\s+", " ", focus.strip())[:70].strip()
    return f"{ASK_TOPIC_PREFIX} {compact or 'latest request'}"


def extract_focus(prompt: str) -> str:
    cleaned = prompt.strip()
    patterns = [
        r"(?i)\bvideos?\s+about\s+(.+)$",
        r"(?i)\bsee\s+(?:some\s+)?(?:videos?\s+)?about\s+(.+)$",
        r"(?i)\bshow\s+me\s+(?:some\s+)?(?:videos?\s+)?about\s+(.+)$",
        r"(?i)\bgive\s+me\s+(?:some\s+)?(?:videos?\s+)?about\s+(.+)$",
    ]
    for pattern in patterns:
        match = re.search(pattern, cleaned)
        if match:
            cleaned = match.group(1)
            break
    cleaned = re.sub(r"(?i)\b(that'?s|that is)\b.*$", "", cleaned).strip()
    cleaned = re.sub(r"(?i),?\s+\bbut\s+(?:not from|no|without|avoid|remove).*$", "", cleaned).strip()
    cleaned = re.sub(r"(?i)\b(remove|avoid|less|too much|mainstream|sources?)\b.*$", "", cleaned).strip()
    cleaned = cleaned.strip(" .?!,;:")
    cleaned = re.sub(r"(?i)^(the|a|an)\s+", "", cleaned)
    if cleaned.lower() in {"give me", "show me", "ok", "okay", "but", "now"}:
        return ""
    return cleaned


def is_followup(lower_prompt: str) -> bool:
    followup_markers = (
        "that",
        "those",
        "ok",
        "but",
        "now",
        "remove",
        "avoid",
        "less",
        "too much",
        "other side",
        "mainstream",
        "aligned",
    )
    return any(marker in lower_prompt for marker in followup_markers)


def extract_viewpoints(lower_prompt: str) -> list[str]:
    found: list[str] = []
    for key in VIEWPOINT_TERMS:
        if re.search(rf"\b{re.escape(key)}\s+(?:aligned|perspective|sources?|media)\b", lower_prompt):
            found.append(key)
    return found


def build_queries(focus: str, *, remove_mainstream: bool, viewpoints: list[str]) -> list[str]:
    queries: list[str] = []
    if viewpoints:
        for viewpoint in viewpoints:
            for term in VIEWPOINT_TERMS.get(viewpoint, [viewpoint]):
                queries.append(f"{focus} {term}")
    elif remove_mainstream:
        queries.extend(
            [
                f"{focus} independent analysis",
                f"{focus} alternative media analysis",
                f"{focus} non mainstream perspective",
            ]
        )
    else:
        queries.extend([f"{focus} latest analysis", f"{focus} explained", f"{focus} update"])
    if remove_mainstream and viewpoints:
        queries.append(f"{focus} alternative non western analysis")
    return dedupe(queries)[:8]


def dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        key = item.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(item.strip())
    return out


def is_mainstream_channel(channel: str) -> bool:
    normalized = re.sub(r"\s+", " ", channel.strip().lower())
    return any(hint in normalized for hint in MAINSTREAM_CHANNEL_HINTS)


def collect_ask_candidates(
    *,
    client: BrowserBrainClient,
    plan: dict[str, Any],
    max_candidates_per_query: int,
    skip_youtube_metadata: bool,
) -> list[VideoCandidate]:
    collected: dict[str, VideoCandidate] = {}
    for query in plan["queries"]:
        snapshot = client.open_search_snapshot(str(query))
        candidates = extract_video_candidates(
            snapshot,
            topic=str(query),
            max_candidates=max_candidates_per_query,
        )
        if not skip_youtube_metadata:
            candidates = enrich_candidates_with_youtube_metadata(candidates)
        for candidate in candidates:
            if plan.get("remove_mainstream") and is_mainstream_channel(candidate.channel):
                continue
            collected.setdefault(candidate.video_id, replace(candidate, source_topic=str(plan["topic"])))
    return list(collected.values())


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    request = load_json(args.request_file)
    prompt = str(request.get("prompt") or "")
    previous = load_json(args.state_file)
    plan = build_scan_plan(prompt, previous)

    store = SignalTubeStore(args.db)
    store.init()
    client = BrowserBrainClient(args.browser_brain_url)
    candidates = collect_ask_candidates(
        client=client,
        plan=plan,
        max_candidates_per_query=args.max_candidates_per_query,
        skip_youtube_metadata=args.skip_youtube_metadata,
    )
    blocked_channels = store.load_blocked_channels()
    seen_video_ids = store.load_seen_video_ids()
    candidates = [
        candidate
        for candidate in candidates
        if candidate.channel.strip().lower() not in blocked_channels and candidate.video_id not in seen_video_ids
    ]
    topic = str(plan["topic"])
    ranked = rank_candidates(candidates, topic=topic, feedback_profile=store.load_feedback_profile(topic=topic))
    store.clear_ranked_results(topic=LEGACY_ASK_TOPIC)
    store.clear_ranked_results(topic_prefix=ASK_TOPIC_PREFIX)
    store.save_ranked(topic, ranked)
    render_feed(
        args.html,
        store.load_ranked(limit=args.render_limit),
        db_path=store.path,
        command_path=ROOT / "ops" / "signaltube_ask.py",
    )
    save_json(args.state_file, {**plan, "result_count": len(ranked)})
    print(f"Ask SignalTube focus: {plan['focus']}")
    print(f"Ask SignalTube queries: {' | '.join(plan['queries'])}")
    print(f"Ask SignalTube stored {len(ranked)} ranked candidates")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
