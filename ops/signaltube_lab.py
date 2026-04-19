#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.signaltube.browser_lab import BrowserBrainClient, SignalTubeBrowserLabError, extract_video_candidates
from src.signaltube.metadata import enrich_candidates_with_youtube_metadata
from src.signaltube.publish import SignalTubePublishError, build_publish_config, publish_html
from src.signaltube.ranking import feedback_weight_for_signal, rank_candidates
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

    scheduled = subparsers.add_parser("scheduled-collect")
    scheduled.add_argument("--topic", action="append", default=[])
    scheduled.add_argument("--max-candidates-per-topic", type=int)
    scheduled.add_argument("--render-limit", type=int, default=200)
    scheduled.add_argument("--clear-existing-results", action="store_true")
    scheduled.add_argument("--allow-unverified-logged-out", action="store_true")
    scheduled.add_argument("--skip-youtube-metadata", action="store_true")

    render = subparsers.add_parser("render")
    render.add_argument("--topic")
    render.add_argument("--limit", type=int, default=80)

    publish = subparsers.add_parser("publish")
    publish.add_argument("--base-url")
    publish.add_argument("--public-base-url")
    publish.add_argument("--username")
    publish.add_argument("--password")
    publish.add_argument("--remote-dir", default="SignalTube")
    publish.add_argument("--remote-name", default="index.html")
    publish.add_argument("--playwright-python", type=Path)

    feedback = subparsers.add_parser("feedback")
    feedback.add_argument("--topic", required=True)
    feedback.add_argument("--video-id", required=True)
    feedback.add_argument(
        "--signal",
        required=True,
        choices=["more_like_this", "less_like_this", "too_clickbait", "save"],
    )
    feedback.add_argument("--note", default="")

    topics = subparsers.add_parser("topics")
    topic_subparsers = topics.add_subparsers(dest="topics_command", required=True)

    topics_add = topic_subparsers.add_parser("add")
    topics_add.add_argument("--topic", required=True)
    topics_add.add_argument("--max-candidates", type=int, default=40)
    topics_add.add_argument("--sort-order", type=int, default=100)
    topics_add.add_argument("--disabled", action="store_true")

    topics_list = topic_subparsers.add_parser("list")
    topics_list.add_argument("--enabled-only", action="store_true")

    topics_enable = topic_subparsers.add_parser("enable")
    topics_enable.add_argument("--topic", required=True)

    topics_disable = topic_subparsers.add_parser("disable")
    topics_disable.add_argument("--topic", required=True)

    topics_remove = topic_subparsers.add_parser("remove")
    topics_remove.add_argument("--topic", required=True)

    channels = subparsers.add_parser("channels")
    channel_subparsers = channels.add_subparsers(dest="channels_command", required=True)

    channels_block = channel_subparsers.add_parser("block")
    channels_block.add_argument("--channel", required=True)
    channels_block.add_argument("--note", default="")

    channels_unblock = channel_subparsers.add_parser("unblock")
    channels_unblock.add_argument("--channel", required=True)

    channel_subparsers.add_parser("list")

    videos = subparsers.add_parser("videos")
    video_subparsers = videos.add_subparsers(dest="videos_command", required=True)

    videos_seen = video_subparsers.add_parser("seen")
    videos_seen.add_argument("--video-id", required=True)
    videos_seen.add_argument("--note", default="")

    videos_unsee = video_subparsers.add_parser("unsee")
    videos_unsee.add_argument("--video-id", required=True)

    video_subparsers.add_parser("list")

    return parser


def collect_for_topics(
    store: SignalTubeStore,
    client: BrowserBrainClient,
    *,
    topics: list[tuple[str, int]],
    html_path: Path,
    render_limit: int,
    allow_unverified_logged_out: bool,
    skip_youtube_metadata: bool,
) -> int:
    collected_total = 0
    for topic, max_candidates in topics:
        snapshot = client.open_search_snapshot(topic)
        candidates = extract_video_candidates(
            snapshot,
            topic=topic,
            max_candidates=max_candidates,
            require_logged_out_marker=not allow_unverified_logged_out,
        )
        if not skip_youtube_metadata:
            candidates = enrich_candidates_with_youtube_metadata(candidates)
        blocked_channels = store.load_blocked_channels()
        seen_video_ids = store.load_seen_video_ids()
        candidates = [
            candidate
            for candidate in candidates
            if candidate.channel.strip().lower() not in blocked_channels and candidate.video_id not in seen_video_ids
        ]
        feedback_profile = store.load_feedback_profile(topic=topic)
        ranked = rank_candidates(candidates, topic=topic, feedback_profile=feedback_profile)
        store.save_ranked(topic, ranked)
        collected_total += len(ranked)
        print(f"{topic}: stored {len(ranked)} ranked candidates")
    render_feed(
        html_path,
        store.load_ranked(limit=render_limit),
        db_path=store.path,
        command_path=ROOT / "ops" / "signaltube_lab.py",
    )
    print(f"wrote {html_path} with {collected_total} newly collected candidates")
    maybe_publish_rendered_html(html_path)
    return collected_total


def maybe_publish_rendered_html(html_path: Path) -> str | None:
    config = build_publish_config()
    if config is None:
        return None
    public_url = publish_html(html_path, config)
    print(f"published {html_path} to {public_url}")
    return public_url


def resolve_scheduled_topics(
    store: SignalTubeStore,
    *,
    cli_topics: list[str],
    max_candidates_override: int | None,
) -> list[tuple[str, int]]:
    configured = store.list_topics(enabled_only=True)
    resolved: dict[str, int] = {}
    for item in configured:
        resolved[item.topic] = max_candidates_override or item.max_candidates
    env_topics = [
        topic.strip()
        for topic in os.environ.get("SIGNALTUBE_LAB_TOPICS", "").split("||")
        if topic.strip()
    ]
    for topic in env_topics:
        resolved[topic] = max_candidates_override or resolved.get(topic, 40)
    for raw_topic in cli_topics:
        topic = raw_topic.strip()
        if topic:
            resolved[topic] = max_candidates_override or resolved.get(topic, 40)
    return list(resolved.items())


def handle_topics_command(store: SignalTubeStore, args: argparse.Namespace) -> int:
    if args.topics_command == "add":
        store.upsert_topic(
            args.topic,
            enabled=not args.disabled,
            max_candidates=args.max_candidates,
            sort_order=args.sort_order,
        )
        print(
            f"saved topic '{args.topic.strip()}' "
            f"(enabled={str(not args.disabled).lower()} max_candidates={max(1, args.max_candidates)})"
        )
        return 0

    if args.topics_command == "list":
        topics = store.list_topics(enabled_only=args.enabled_only)
        if not topics:
            print("no topics configured")
            return 0
        for item in topics:
            print(
                f"{item.topic}\tenabled={str(item.enabled).lower()}\tmax_candidates={item.max_candidates}\t"
                f"sort_order={item.sort_order}\tlast_collected_at={item.last_collected_at or '-'}"
            )
        return 0

    if args.topics_command in {"enable", "disable"}:
        changed = store.set_topic_enabled(args.topic, enabled=args.topics_command == "enable")
        if not changed:
            print(f"topic not found: {args.topic}", file=sys.stderr)
            return 1
        print(f"{args.topics_command}d topic '{args.topic.strip()}'")
        return 0

    if args.topics_command == "remove":
        deleted = store.delete_topic(args.topic)
        if not deleted:
            print(f"topic not found: {args.topic}", file=sys.stderr)
            return 1
        print(f"removed topic '{args.topic.strip()}'")
        return 0

    raise AssertionError(f"Unhandled topics command: {args.topics_command}")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    store = SignalTubeStore(args.db)
    store.init()

    if args.command == "collect":
        client = BrowserBrainClient(args.browser_brain_url)
        collect_for_topics(
            store,
            client,
            topics=[(topic, args.max_candidates_per_topic) for topic in args.topic],
            html_path=args.html,
            render_limit=200,
            allow_unverified_logged_out=args.allow_unverified_logged_out,
            skip_youtube_metadata=args.skip_youtube_metadata,
        )
        return 0

    if args.command == "scheduled-collect":
        topics = resolve_scheduled_topics(
            store,
            cli_topics=args.topic,
            max_candidates_override=args.max_candidates_per_topic,
        )
        if not topics:
            print(
                "SignalTube lab error: no scheduled topics configured. "
                "Use 'topics add --topic ...' or pass --topic.",
                file=sys.stderr,
            )
            return 2
        if args.clear_existing_results:
            store.clear_ranked_results()
            print("cleared existing SignalTube ranked results")
        client = BrowserBrainClient(args.browser_brain_url)
        collect_for_topics(
            store,
            client,
            topics=topics,
            html_path=args.html,
            render_limit=args.render_limit,
            allow_unverified_logged_out=args.allow_unverified_logged_out,
            skip_youtube_metadata=args.skip_youtube_metadata,
        )
        return 0

    if args.command == "render":
        ranked = store.load_ranked(topic=args.topic, limit=args.limit)
        render_feed(
            args.html,
            ranked,
            db_path=store.path,
            command_path=ROOT / "ops" / "signaltube_lab.py",
        )
        print(f"wrote {args.html} with {len(ranked)} candidates")
        maybe_publish_rendered_html(args.html)
        return 0

    if args.command == "publish":
        config = build_publish_config(
            username=args.username,
            password=args.password,
            base_url=args.base_url,
            public_base_url=args.public_base_url,
            remote_dir=args.remote_dir,
            remote_name=args.remote_name,
            playwright_python=args.playwright_python,
        )
        if config is None:
            print(
                "SignalTube publish error: missing credentials. "
                "Pass --username/--password or set SIGNALTUBE_PUBLISH_USERNAME/SIGNALTUBE_PUBLISH_PASSWORD.",
                file=sys.stderr,
            )
            return 2
        public_url = publish_html(args.html, config)
        print(f"published {args.html} to {public_url}")
        return 0

    if args.command == "feedback":
        weight = feedback_weight_for_signal(args.signal)
        store.add_feedback(
            topic=args.topic,
            video_id=args.video_id,
            signal=args.signal,
            weight=weight,
            note=args.note,
        )
        print(
            f"stored feedback topic={args.topic.strip()} video_id={args.video_id.strip()} "
            f"signal={args.signal} weight={weight:+.1f}"
        )
        return 0

    if args.command == "topics":
        return handle_topics_command(store, args)

    if args.command == "channels":
        if args.channels_command == "block":
            store.block_channel(args.channel, note=args.note)
            print(f"blocked channel '{args.channel.strip()}'")
            return 0
        if args.channels_command == "unblock":
            removed = store.unblock_channel(args.channel)
            if not removed:
                print(f"channel not blocked: {args.channel}", file=sys.stderr)
                return 1
            print(f"unblocked channel '{args.channel.strip()}'")
            return 0
        if args.channels_command == "list":
            channels = store.list_blocked_channels()
            if not channels:
                print("no blocked channels")
                return 0
            for row in channels:
                note = str(row["note"] or "").strip() or "-"
                print(f"{row['channel']}\tnote={note}\tcreated_at={row['created_at']}")
            return 0

    if args.command == "videos":
        if args.videos_command == "seen":
            store.mark_video_seen(args.video_id, note=args.note)
            print(f"marked video seen '{args.video_id.strip()}'")
            return 0
        if args.videos_command == "unsee":
            removed = store.unsee_video(args.video_id)
            if not removed:
                print(f"video not marked seen: {args.video_id}", file=sys.stderr)
                return 1
            print(f"unmarked video seen '{args.video_id.strip()}'")
            return 0
        if args.videos_command == "list":
            videos = store.list_seen_videos()
            if not videos:
                print("no seen videos")
                return 0
            for row in videos:
                note = str(row["note"] or "").strip() or "-"
                print(f"{row['video_id']}\tnote={note}\tcreated_at={row['created_at']}")
            return 0

    raise AssertionError(f"Unhandled command: {args.command}")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SignalTubeBrowserLabError as exc:
        print(f"SignalTube lab error: {exc}", file=sys.stderr)
        raise SystemExit(2) from None
    except SignalTubePublishError as exc:
        print(f"SignalTube publish error: {exc}", file=sys.stderr)
        raise SystemExit(2) from None
