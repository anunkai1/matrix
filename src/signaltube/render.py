from __future__ import annotations

import html
from collections import defaultdict
from pathlib import Path

from .models import RankedVideo


def render_feed(path: Path, ranked: list[RankedVideo], *, title: str = "SignalTube Lab") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    by_topic: dict[str, list[RankedVideo]] = defaultdict(list)
    for item in ranked:
        by_topic[item.candidate.source_topic or "Discovered"].append(item)
    sections = "\n".join(_render_section(topic, items) for topic, items in by_topic.items())
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
    .score {{ color: #d4e157; font-size: 12px; margin-top: 8px; }}
    .actions {{ display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; }}
    button {{ border: 1px solid #4a5260; border-radius: 6px; background: #20242d; color: #f5f5f5; padding: 6px 8px; }}
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
</body>
</html>
""",
        encoding="utf-8",
    )


def _render_section(topic: str, items: list[RankedVideo]) -> str:
    cards = "\n".join(_render_card(item) for item in items)
    return f"""<section>
  <h2>{html.escape(topic)}</h2>
  <div class="grid">{cards}</div>
</section>"""


def _render_card(item: RankedVideo) -> str:
    candidate = item.candidate
    reasons = ", ".join(item.reasons)
    return f"""<article class="card">
  <a href="{html.escape(candidate.url)}"><img class="thumb" src="{html.escape(candidate.thumbnail_url)}" alt=""></a>
  <div class="body">
    <a class="title" href="{html.escape(candidate.url)}">{html.escape(candidate.title)}</a>
    <div class="meta">{html.escape(candidate.channel or "YouTube")} · {html.escape(candidate.video_id)}</div>
    <div class="score">Score {item.score:.0f} · {html.escape(reasons)}</div>
    <div class="actions">
      <button>More like this</button><button>Less like this</button><button>Too clickbait</button><button>Save</button>
    </div>
  </div>
</article>"""
