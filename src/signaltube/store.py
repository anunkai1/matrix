from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .models import RankedVideo, VideoCandidate


SCHEMA = """
CREATE TABLE IF NOT EXISTS videos (
  video_id TEXT PRIMARY KEY,
  url TEXT NOT NULL,
  title TEXT NOT NULL,
  channel TEXT NOT NULL DEFAULT '',
  published_at TEXT NOT NULL DEFAULT '',
  thumbnail_url TEXT NOT NULL,
  first_seen TEXT NOT NULL,
  last_seen TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS discoveries (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  topic TEXT NOT NULL,
  video_id TEXT NOT NULL,
  source TEXT NOT NULL,
  discovered_at TEXT NOT NULL,
  UNIQUE(topic, video_id, source)
);

CREATE TABLE IF NOT EXISTS rankings (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  topic TEXT NOT NULL,
  video_id TEXT NOT NULL,
  score REAL NOT NULL,
  reasons TEXT NOT NULL,
  ranked_at TEXT NOT NULL,
  UNIQUE(topic, video_id)
);
"""


class SignalTubeStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def init(self) -> None:
        with self.connect() as db:
            _ensure_schema(db)

    def connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        return db

    def save_ranked(self, topic: str, ranked: list[RankedVideo]) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as db:
            _ensure_schema(db)
            for item in ranked:
                candidate = item.candidate
                db.execute(
                    """
                    INSERT INTO videos (video_id, url, title, channel, published_at, thumbnail_url, first_seen, last_seen)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(video_id) DO UPDATE SET
                      url=excluded.url,
                      title=excluded.title,
                      channel=excluded.channel,
                      published_at=excluded.published_at,
                      thumbnail_url=excluded.thumbnail_url,
                      last_seen=excluded.last_seen
                    """,
                    (
                        candidate.video_id,
                        candidate.url,
                        candidate.title,
                        candidate.channel,
                        candidate.published_at,
                        candidate.thumbnail_url,
                        now,
                        now,
                    ),
                )
                db.execute(
                    """
                    INSERT INTO discoveries (topic, video_id, source, discovered_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(topic, video_id, source) DO UPDATE SET discovered_at=excluded.discovered_at
                    """,
                    (topic, candidate.video_id, candidate.source, now),
                )
                db.execute(
                    """
                    INSERT INTO rankings (topic, video_id, score, reasons, ranked_at)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(topic, video_id) DO UPDATE SET
                      score=excluded.score,
                      reasons=excluded.reasons,
                      ranked_at=excluded.ranked_at
                    """,
                    (topic, candidate.video_id, item.score, ", ".join(item.reasons), now),
                )

    def load_ranked(self, *, topic: str | None = None, limit: int = 80) -> list[RankedVideo]:
        where = ""
        params: list[object] = []
        if topic:
            where = "WHERE r.topic = ?"
            params.append(topic)
        params.append(limit)
        with self.connect() as db:
            _ensure_schema(db)
            rows = db.execute(
                f"""
                SELECT r.topic, r.score, r.reasons, v.video_id, v.url, v.title, v.channel, v.published_at
                FROM rankings r
                JOIN videos v ON v.video_id = r.video_id
                {where}
                ORDER BY r.score DESC, r.ranked_at DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        ranked: list[RankedVideo] = []
        for row in rows:
            candidate = VideoCandidate(
                video_id=row["video_id"],
                url=row["url"],
                title=row["title"],
                channel=row["channel"],
                published_at=row["published_at"],
                source_topic=row["topic"],
            )
            reasons = tuple(part.strip() for part in str(row["reasons"] or "").split(",") if part.strip())
            ranked.append(RankedVideo(candidate=candidate, score=float(row["score"]), reasons=reasons))
        return ranked


def _ensure_schema(db: sqlite3.Connection) -> None:
    db.executescript(SCHEMA)
    video_columns = {str(row["name"]) for row in db.execute("PRAGMA table_info(videos)").fetchall()}
    if "published_at" not in video_columns:
        db.execute("ALTER TABLE videos ADD COLUMN published_at TEXT NOT NULL DEFAULT ''")
