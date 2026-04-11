#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.signaltube.browser_lab import BrowserBrainClient, SignalTubeBrowserLabError, extract_video_candidates
from src.signaltube.metadata import enrich_candidates_with_youtube_metadata
from src.signaltube.ranking import rank_candidates
from src.signaltube.render import render_feed
from src.signaltube.store import SignalTubeStore


DEFAULT_DB = Path("private/signaltube/signaltube.sqlite")
DEFAULT_HTML = Path("private/signaltube/feed.html")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="SignalTube logged-out Browser Brain lab collector")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--html", type=Path, default=DEFAULT_HTML)
    parser.add_argument("--browser-brain-url", default="http://127.0.0.1:47832")
    subparsers = parser.add_subparsers(dest="command", required=True)

    collect = subparsers.add_parser("collect")
    collect.add_argument("--topic", action="append", required=True)
    collect.add_argument("--max-candidates-per-topic", type=int, default=40)
    collect.add_argument("--allow-unverified-logged-out", action="store_true")
    collect.add_argument("--skip-youtube-metadata", action="store_true")

    render = subparsers.add_parser("render")
    render.add_argument("--topic")
    render.add_argument("--limit", type=int, default=80)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    store = SignalTubeStore(args.db)
    store.init()

    if args.command == "collect":
        client = BrowserBrainClient(args.browser_brain_url)
        collected_total = 0
        for topic in args.topic:
            snapshot = client.open_search_snapshot(topic)
            candidates = extract_video_candidates(
                snapshot,
                topic=topic,
                max_candidates=args.max_candidates_per_topic,
                require_logged_out_marker=not args.allow_unverified_logged_out,
            )
            if not args.skip_youtube_metadata:
                candidates = enrich_candidates_with_youtube_metadata(candidates)
            ranked = rank_candidates(candidates, topic=topic)
            store.save_ranked(topic, ranked)
            collected_total += len(ranked)
            print(f"{topic}: stored {len(ranked)} ranked candidates")
        render_feed(args.html, store.load_ranked(limit=200))
        print(f"wrote {args.html} with {collected_total} newly collected candidates")
        return 0

    if args.command == "render":
        ranked = store.load_ranked(topic=args.topic, limit=args.limit)
        render_feed(args.html, ranked)
        print(f"wrote {args.html} with {len(ranked)} candidates")
        return 0

    raise AssertionError(f"Unhandled command: {args.command}")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SignalTubeBrowserLabError as exc:
        print(f"SignalTube lab error: {exc}", file=sys.stderr)
        raise SystemExit(2) from None
