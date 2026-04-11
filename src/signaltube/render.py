from __future__ import annotations

import html
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .models import RankedVideo


BRISBANE_TZ = ZoneInfo("Australia/Brisbane")


def render_feed(
    path: Path,
    ranked: list[RankedVideo],
    *,
    title: str = "SignalTube Lab",
    db_path: Path | None = None,
    command_path: Path | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    db_path = (db_path or Path("private/signaltube/signaltube.sqlite")).resolve()
    command_path = (command_path or Path("ops/signaltube_lab.py")).resolve()
    by_topic: dict[str, list[RankedVideo]] = defaultdict(list)
    for item in ranked:
        by_topic[item.candidate.source_topic or "Discovered"].append(item)
    sections = "\n".join(_render_section(topic, items, db_path, command_path) for topic, items in by_topic.items())
    path.write_text(
        f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)}</title>
  <style>
    body {{ margin: 0; font-family: Arial, sans-serif; background: #0f1014; color: #f5f5f5; }}
    header {{ padding: 20px 28px 12px; border-bottom: 1px solid #2f3440; }}
    h1 {{ margin: 0 0 8px; font-size: 28px; }}
    .note {{ color: #b8beca; }}
    main {{ padding: 18px 28px 40px; }}
    h2 {{ margin: 26px 0 14px; font-size: 20px; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 18px; }}
    .card {{ background: #181a20; border: 1px solid #2f3440; border-radius: 8px; overflow: hidden; }}
    .thumb {{ aspect-ratio: 16 / 9; width: 100%; object-fit: cover; background: #242833; display: block; }}
    .body {{ padding: 10px 12px 12px; }}
    .title {{ font-weight: 700; line-height: 1.25; color: #fff; text-decoration: none; }}
    .meta {{ color: #aab1bf; font-size: 13px; margin-top: 8px; }}
    .published {{ color: #d7dde8; font-size: 13px; margin-top: 6px; }}
    .score {{ color: #d4e157; font-size: 12px; margin-top: 8px; }}
    .actions {{ display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; }}
    button {{ border: 1px solid #4a5260; border-radius: 6px; background: #20242d; color: #f5f5f5; padding: 6px 8px; cursor: pointer; }}
    .status {{ color: #9fb4cc; font-size: 12px; margin-top: 10px; min-height: 1em; }}
  </style>
</head>
<body>
  <header>
    <h1>{html.escape(title)}</h1>
    <div class="note">Lab feed from logged-out browser discovery. No downloads, no account automation.</div>
  </header>
  <main>
    {sections}
  </main>
  <script>
    document.querySelectorAll('[data-feedback-command]').forEach((button) => {{
      button.addEventListener('click', async () => {{
        const command = button.getAttribute('data-feedback-command') || '';
        const status = button.closest('.body')?.querySelector('.status');
        try {{
          await navigator.clipboard.writeText(command);
          if (status) status.textContent = 'Copied feedback command';
        }} catch (error) {{
          if (status) status.textContent = command;
        }}
      }});
    }});
  </script>
</body>
</html>
""",
        encoding="utf-8",
    )


def _render_section(topic: str, items: list[RankedVideo], db_path: Path, command_path: Path) -> str:
    cards = "\n".join(_render_card(item, db_path=db_path, command_path=command_path) for item in items)
    return f"""<section>
  <h2>{html.escape(topic)}</h2>
  <div class="grid">{cards}</div>
</section>"""


def _render_card(item: RankedVideo, *, db_path: Path, command_path: Path) -> str:
    candidate = item.candidate
    reasons = ", ".join(item.reasons)
    published = _format_published_at(candidate.published_at)
    actions = "\n".join(
        _render_feedback_button(
            label=label,
            signal=signal,
            topic=candidate.source_topic or "Discovered",
            video_id=candidate.video_id,
            db_path=db_path,
            command_path=command_path,
        )
        for label, signal in (
            ("More like this", "more_like_this"),
            ("Less like this", "less_like_this"),
            ("Too clickbait", "too_clickbait"),
            ("Save", "save"),
        )
    )
    channel_action = _render_channel_block_button(
        channel=candidate.channel or "YouTube",
        db_path=db_path,
        command_path=command_path,
    )
    seen_action = _render_seen_button(
        video_id=candidate.video_id,
        db_path=db_path,
        command_path=command_path,
    )
    return f"""<article class="card">
  <a href="{html.escape(candidate.url)}"><img class="thumb" src="{html.escape(candidate.thumbnail_url)}" alt=""></a>
  <div class="body">
    <a class="title" href="{html.escape(candidate.url)}">{html.escape(candidate.title)}</a>
    <div class="meta">{html.escape(candidate.channel or "YouTube")} · {html.escape(_format_duration(candidate.duration_text))} · {html.escape(candidate.video_id)}</div>
    <div class="published">Published: {html.escape(published)}</div>
    <div class="score">Score {item.score:.0f} · {html.escape(reasons)}</div>
    <div class="actions">
      {actions}
      {channel_action}
      {seen_action}
    </div>
    <div class="status"></div>
  </div>
</article>"""


def _render_feedback_button(
    *,
    label: str,
    signal: str,
    topic: str,
    video_id: str,
    db_path: Path,
    command_path: Path,
) -> str:
    command = (
        f"python3 {command_path} --db {db_path} "
        f"feedback --topic {quote_arg(topic)} --video-id {quote_arg(video_id)} --signal {signal}"
    )
    return (
        f'<button data-feedback-command="{html.escape(command)}">{html.escape(label)}</button>'
    )


def _render_channel_block_button(*, channel: str, db_path: Path, command_path: Path) -> str:
    command = (
        f"python3 {command_path} --db {db_path} "
        f"channels block --channel {quote_arg(channel)}"
    )
    return f'<button data-feedback-command="{html.escape(command)}">Don&#x27;t recommend this channel</button>'


def _render_seen_button(*, video_id: str, db_path: Path, command_path: Path) -> str:
    command = (
        f"python3 {command_path} --db {db_path} "
        f"videos seen --video-id {quote_arg(video_id)}"
    )
    return f'<button data-feedback-command="{html.escape(command)}">Seen</button>'


def quote_arg(value: str) -> str:
    escaped = value.replace("'", "'\"'\"'")
    return f"'{escaped}'"


def _format_published_at(value: str) -> str:
    if not value:
        return "unavailable"
    if len(value) == 10:
        return f"{value} (date only)"
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return value
    if parsed.tzinfo is None:
        return parsed.strftime("%Y-%m-%d %H:%M")
    return f"{parsed.astimezone(BRISBANE_TZ).strftime('%Y-%m-%d %H:%M')} AEST"


def _format_duration(value: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        return "duration unavailable"
    return cleaned
