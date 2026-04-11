from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .models import FeedbackProfile, RankedVideo, TopicConfig, VideoCandidate


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

CREATE TABLE IF NOT EXISTS topic_configs (
  topic TEXT PRIMARY KEY,
  enabled INTEGER NOT NULL DEFAULT 1,
  max_candidates INTEGER NOT NULL DEFAULT 40,
  sort_order INTEGER NOT NULL DEFAULT 100,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  last_collected_at TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS feedback_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  topic TEXT NOT NULL,
  video_id TEXT NOT NULL,
  signal TEXT NOT NULL,
  weight REAL NOT NULL,
  note TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
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
            db.execute(
                """
                INSERT INTO topic_configs (topic, enabled, max_candidates, sort_order, created_at, updated_at, last_collected_at)
                VALUES (?, 1, 40, 100, ?, ?, ?)
                ON CONFLICT(topic) DO UPDATE SET
                  updated_at=excluded.updated_at,
                  last_collected_at=excluded.last_collected_at
                """,
                (topic, now, now, now),
            )
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

    def upsert_topic(
        self,
        topic: str,
        *,
        enabled: bool = True,
        max_candidates: int = 40,
        sort_order: int = 100,
    ) -> None:
        topic = topic.strip()
        if not topic:
            raise ValueError("topic must not be empty")
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as db:
            _ensure_schema(db)
            db.execute(
                """
                INSERT INTO topic_configs (topic, enabled, max_candidates, sort_order, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(topic) DO UPDATE SET
                  enabled=excluded.enabled,
                  max_candidates=excluded.max_candidates,
                  sort_order=excluded.sort_order,
                  updated_at=excluded.updated_at
                """,
                (topic, 1 if enabled else 0, max(1, max_candidates), sort_order, now, now),
            )

    def set_topic_enabled(self, topic: str, *, enabled: bool) -> bool:
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as db:
            _ensure_schema(db)
            result = db.execute(
                "UPDATE topic_configs SET enabled = ?, updated_at = ? WHERE topic = ?",
                (1 if enabled else 0, now, topic.strip()),
            )
            return result.rowcount > 0

    def delete_topic(self, topic: str) -> bool:
        with self.connect() as db:
            _ensure_schema(db)
            result = db.execute("DELETE FROM topic_configs WHERE topic = ?", (topic.strip(),))
            return result.rowcount > 0

    def list_topics(self, *, enabled_only: bool = False) -> list[TopicConfig]:
        where = "WHERE enabled = 1" if enabled_only else ""
        with self.connect() as db:
            _ensure_schema(db)
            rows = db.execute(
                f"""
                SELECT topic, enabled, max_candidates, sort_order, last_collected_at
                FROM topic_configs
                {where}
                ORDER BY sort_order ASC, topic COLLATE NOCASE ASC
                """
            ).fetchall()
        return [
            TopicConfig(
                topic=row["topic"],
                enabled=bool(row["enabled"]),
                max_candidates=int(row["max_candidates"]),
                sort_order=int(row["sort_order"]),
                last_collected_at=str(row["last_collected_at"] or ""),
            )
            for row in rows
        ]

    def add_feedback(
        self,
        *,
        topic: str,
        video_id: str,
        signal: str,
        weight: float,
        note: str = "",
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as db:
            _ensure_schema(db)
            db.execute(
                """
                INSERT INTO feedback_events (topic, video_id, signal, weight, note, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (topic.strip(), video_id.strip(), signal.strip(), weight, note.strip(), now),
            )

    def load_feedback_profile(self, *, topic: str) -> FeedbackProfile:
        topic = topic.strip()
        with self.connect() as db:
            _ensure_schema(db)
            video_topic = _load_score_map(
                db,
                """
                SELECT video_id AS key, SUM(weight) AS score
                FROM feedback_events
                WHERE topic = ?
                GROUP BY video_id
                """,
                (topic,),
            )
            video_global = _load_score_map(
                db,
                """
                SELECT video_id AS key, SUM(weight) AS score
                FROM feedback_events
                GROUP BY video_id
                """
            )
            channel_topic = _load_score_map(
                db,
                """
                SELECT COALESCE(NULLIF(v.channel, ''), '__unknown__') AS key, SUM(f.weight) AS score
                FROM feedback_events f
                JOIN videos v ON v.video_id = f.video_id
                WHERE f.topic = ?
                GROUP BY COALESCE(NULLIF(v.channel, ''), '__unknown__')
                """,
                (topic,),
            )
            channel_global = _load_score_map(
                db,
                """
                SELECT COALESCE(NULLIF(v.channel, ''), '__unknown__') AS key, SUM(f.weight) AS score
                FROM feedback_events f
                JOIN videos v ON v.video_id = f.video_id
                GROUP BY COALESCE(NULLIF(v.channel, ''), '__unknown__')
                """
            )
        return FeedbackProfile(
            video_scores=_blend_score_maps(video_topic, video_global, fallback_weight=0.35),
            channel_scores=_blend_score_maps(channel_topic, channel_global, fallback_weight=0.35),
        )

    def load_feedback_events(self, *, topic: str | None = None) -> list[sqlite3.Row]:
        where = ""
        params: list[object] = []
        if topic:
            where = "WHERE topic = ?"
            params.append(topic)
        with self.connect() as db:
            _ensure_schema(db)
            return db.execute(
                f"""
                SELECT id, topic, video_id, signal, weight, note, created_at
                FROM feedback_events
                {where}
                ORDER BY created_at DESC, id DESC
                """,
                params,
            ).fetchall()


def _ensure_schema(db: sqlite3.Connection) -> None:
    db.executescript(SCHEMA)
    video_columns = {str(row["name"]) for row in db.execute("PRAGMA table_info(videos)").fetchall()}
    if "published_at" not in video_columns:
        db.execute("ALTER TABLE videos ADD COLUMN published_at TEXT NOT NULL DEFAULT ''")
    topic_columns = {str(row["name"]) for row in db.execute("PRAGMA table_info(topic_configs)").fetchall()}
    if topic_columns and "last_collected_at" not in topic_columns:
        db.execute("ALTER TABLE topic_configs ADD COLUMN last_collected_at TEXT NOT NULL DEFAULT ''")


def _load_score_map(
    db: sqlite3.Connection,
    query: str,
    params: tuple[object, ...] = (),
) -> dict[str, float]:
    rows = db.execute(query, params).fetchall()
    return {str(row["key"]): float(row["score"] or 0.0) for row in rows if str(row["key"] or "").strip()}


def _blend_score_maps(primary: dict[str, float], fallback: dict[str, float], *, fallback_weight: float) -> dict[str, float]:
    keys = set(primary) | set(fallback)
    return {
        key: round(primary.get(key, 0.0) + (fallback.get(key, 0.0) * fallback_weight), 4)
        for key in keys
        if primary.get(key, 0.0) or fallback.get(key, 0.0)
    }
