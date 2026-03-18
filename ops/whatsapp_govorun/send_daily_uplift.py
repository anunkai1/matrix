#!/usr/bin/env python3
"""Send a daily Russian morning life hack to a WhatsApp chat via local bridge API."""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.parse
from dataclasses import dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None  # type: ignore[assignment]


PROMPT_HISTORY_LIMIT = 240
MAX_REDDIT_BODY_CHARS = 2400
DEFAULT_SOURCE_SELECTION_ATTEMPTS = 12
DEFAULT_CODEX_TIMEOUT_SECONDS = 180
DEFAULT_CODEX_REASONING_EFFORT = "medium"
DEFAULT_REDDIT_CACHE_MAX_AGE_SECONDS = 7 * 24 * 60 * 60
DEFAULT_REDDIT_MIN_UNUSED = 30
DEFAULT_REDDIT_FETCH_PAGES = 10
DEFAULT_REDDIT_FETCH_PAGE_SIZE = 100
DEFAULT_REDDIT_LOOKBACK_DAYS = 365 * 5
DEFAULT_REDDIT_USER_AGENT = "matrix-govorun-daily-uplift/1.0"
RUSSIAN_STOP_WORDS = {
    "а",
    "без",
    "бы",
    "в",
    "во",
    "вот",
    "вы",
    "где",
    "да",
    "для",
    "до",
    "его",
    "ее",
    "если",
    "же",
    "за",
    "и",
    "из",
    "или",
    "их",
    "к",
    "как",
    "когда",
    "кто",
    "ли",
    "на",
    "над",
    "не",
    "но",
    "ну",
    "о",
    "об",
    "от",
    "по",
    "под",
    "при",
    "про",
    "с",
    "со",
    "так",
    "там",
    "то",
    "тот",
    "у",
    "уже",
    "чем",
    "что",
    "чтобы",
    "это",
    "этот",
}
RUSSIAN_TOKEN_ENDINGS = (
    "иями",
    "ями",
    "ами",
    "иях",
    "его",
    "ого",
    "ему",
    "ому",
    "ыми",
    "ими",
    "ее",
    "ие",
    "ые",
    "ое",
    "ей",
    "ий",
    "ый",
    "ой",
    "ем",
    "им",
    "ом",
    "ам",
    "ям",
    "ах",
    "ях",
    "ию",
    "ью",
    "ия",
    "ья",
    "иям",
    "ием",
    "а",
    "я",
    "ы",
    "и",
    "е",
    "у",
    "ю",
    "о",
)
LEGACY_BLOCKED_LIFE_HACKS = (
    (
        "Если чай слишком горячий, в широкой кружке он остывает быстрее - простой уютный лайфхак.",
        "широкая кружка быстрее остужает чай",
        "Чай остывает быстрее в широкой кружке благодаря большей открытой поверхности.",
    ),
    (
        "Капля лимонного сока помогает быстро убрать запах чеснока с рук - маленький кухонный лайфхак.",
        "лимон убирает запах чеснока с рук",
        "Немного лимонного сока помогает убрать чесночный запах с кожи рук.",
    ),
)


@dataclass(frozen=True)
class GeneratedLifeHack:
    hack_text: str
    idea_key: str
    idea_summary: str


@dataclass(frozen=True)
class RedditPost:
    post_id: str
    title: str
    selftext: str
    permalink: str
    score: int
    num_comments: int
    created_utc: int
    over_18: bool
    title_probe: str
    body_probe: str
    cached_at: str


@dataclass(frozen=True)
class SentLifeHack:
    message_text: str
    hack_text: str
    idea_key: str
    idea_summary: str
    source_post_id: Optional[str] = None
    source_title: Optional[str] = None
    source_permalink: Optional[str] = None
    source_score: Optional[int] = None
    source_created_utc: Optional[int] = None


@dataclass(frozen=True)
class HistoryEntry:
    id: int
    sent_at: str
    message_text: str
    hack_text: str
    idea_key: str
    idea_summary: str
    message_probe: str
    hack_probe: str
    idea_key_probe: str
    idea_summary_probe: str
    source_post_id: Optional[str] = None
    source_title: Optional[str] = None
    source_permalink: Optional[str] = None
    source_score: Optional[int] = None
    source_created_utc: Optional[int] = None


@dataclass(frozen=True)
class SimilarityMatch:
    entry: HistoryEntry
    reason: str
    score: float


def now_in_tz(tz_name: str) -> datetime:
    if ZoneInfo is not None:
        try:
            return datetime.now(ZoneInfo(tz_name))
        except Exception:
            pass
    return datetime.now()


def build_daily_message(group_name: str, hack_text: str) -> str:
    return f"Доброе утро, {group_name}! ☀️\n\nДаю справку: {hack_text}"


def build_payload(chat_id: Optional[str], chat_jid: Optional[str], text: str) -> dict[str, str]:
    payload: dict[str, str] = {"text": text}
    if chat_jid:
        payload["chat_jid"] = chat_jid
    elif chat_id:
        payload["chat_id"] = chat_id
    else:
        raise ValueError("chat destination is required")
    return payload


def send_message(api_base: str, auth_token: str, payload: dict[str, str]) -> dict[str, object]:
    endpoint = f"{api_base.rstrip('/')}/messages"
    request = Request(endpoint, data=json.dumps(payload).encode("utf-8"), method="POST")
    request.add_header("Content-Type", "application/json")
    if auth_token:
        request.add_header("Authorization", f"Bearer {auth_token}")
    try:
        with urlopen(request, timeout=20) as response:
            body = response.read().decode("utf-8")
    except HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8")
        except Exception:
            detail = ""
        raise RuntimeError(f"HTTP {exc.code}: {detail or exc.reason}") from exc
    except URLError as exc:
        raise RuntimeError(f"URL error: {exc}") from exc

    if not body:
        return {"ok": True}
    decoded = json.loads(body)
    if not isinstance(decoded, dict):
        raise RuntimeError("unexpected JSON response type")
    if decoded.get("ok") is False:
        raise RuntimeError(str(decoded.get("description") or "unknown bridge error"))
    return decoded


def collapse_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def normalize_probe(text: str) -> str:
    lowered = (text or "").lower().replace("ё", "е")
    lowered = lowered.replace("☀️", " ")
    lowered = re.sub(r"[^0-9a-zа-я]+", " ", lowered)
    return collapse_whitespace(lowered)


def stem_token(token: str) -> str:
    token = normalize_probe(token)
    for ending in RUSSIAN_TOKEN_ENDINGS:
        if len(token) <= len(ending) + 2:
            continue
        if token.endswith(ending):
            return token[: -len(ending)]
    return token


def probe_tokens(text: str) -> set[str]:
    tokens = []
    for token in normalize_probe(text).split():
        if len(token) <= 2:
            continue
        if token in RUSSIAN_STOP_WORDS:
            continue
        stemmed = stem_token(token)
        if len(stemmed) <= 2:
            continue
        tokens.append(stemmed)
    return set(tokens)


def jaccard_similarity(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    union = left | right
    if not union:
        return 0.0
    return len(left & right) / len(union)


def overlap_similarity(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / min(len(left), len(right))


def sequence_similarity(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    return SequenceMatcher(None, left, right).ratio()


def best_similarity(left: str, right: str) -> float:
    left_probe = normalize_probe(left)
    right_probe = normalize_probe(right)
    return max(
        sequence_similarity(left_probe, right_probe),
        jaccard_similarity(probe_tokens(left_probe), probe_tokens(right_probe)),
        overlap_similarity(probe_tokens(left_probe), probe_tokens(right_probe)),
    )


def state_dir_path() -> Path:
    override = os.getenv("WA_DAILY_UPLIFT_STATE_DIR", "").strip()
    if override:
        return Path(override).expanduser()
    return Path.home() / ".local" / "state" / "govorun-whatsapp-daily-uplift"


def uplift_db_path() -> Path:
    override = os.getenv("WA_DAILY_UPLIFT_DB_PATH", "").strip()
    if override:
        return Path(override).expanduser()
    legacy_override = os.getenv("WA_DAILY_UPLIFT_HISTORY_DB_PATH", "").strip()
    if legacy_override:
        return Path(legacy_override).expanduser()
    return state_dir_path() / "daily_uplift.sqlite3"


def reddit_cache_max_age_seconds() -> int:
    raw_value = os.getenv(
        "WA_DAILY_UPLIFT_REDDIT_CACHE_MAX_AGE_SECONDS",
        str(DEFAULT_REDDIT_CACHE_MAX_AGE_SECONDS),
    ).strip()
    try:
        return max(60, int(raw_value))
    except ValueError:
        return DEFAULT_REDDIT_CACHE_MAX_AGE_SECONDS


def reddit_min_unused() -> int:
    raw_value = os.getenv("WA_DAILY_UPLIFT_REDDIT_MIN_UNUSED", str(DEFAULT_REDDIT_MIN_UNUSED)).strip()
    try:
        return max(1, int(raw_value))
    except ValueError:
        return DEFAULT_REDDIT_MIN_UNUSED


def reddit_fetch_pages() -> int:
    raw_value = os.getenv("WA_DAILY_UPLIFT_REDDIT_FETCH_PAGES", str(DEFAULT_REDDIT_FETCH_PAGES)).strip()
    try:
        return max(1, int(raw_value))
    except ValueError:
        return DEFAULT_REDDIT_FETCH_PAGES


def reddit_fetch_page_size() -> int:
    raw_value = os.getenv(
        "WA_DAILY_UPLIFT_REDDIT_FETCH_PAGE_SIZE",
        str(DEFAULT_REDDIT_FETCH_PAGE_SIZE),
    ).strip()
    try:
        return min(100, max(1, int(raw_value)))
    except ValueError:
        return DEFAULT_REDDIT_FETCH_PAGE_SIZE


def reddit_lookback_days() -> int:
    raw_value = os.getenv(
        "WA_DAILY_UPLIFT_REDDIT_LOOKBACK_DAYS",
        str(DEFAULT_REDDIT_LOOKBACK_DAYS),
    ).strip()
    try:
        return max(1, int(raw_value))
    except ValueError:
        return DEFAULT_REDDIT_LOOKBACK_DAYS


def reddit_user_agent() -> str:
    return os.getenv("WA_DAILY_UPLIFT_REDDIT_USER_AGENT", DEFAULT_REDDIT_USER_AGENT).strip() or DEFAULT_REDDIT_USER_AGENT


def recent_cutoff_utc(now_ts: Optional[int] = None) -> int:
    base_ts = now_ts if now_ts is not None else int(time.time())
    return base_ts - reddit_lookback_days() * 24 * 60 * 60


class HistoryStore:
    def __init__(self, db_path: Path):
        self.db_path = db_path

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path), timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    def _column_names(self, conn: sqlite3.Connection, table_name: str) -> set[str]:
        rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
        return {str(row["name"]) for row in rows}

    def _ensure_sent_columns(self, conn: sqlite3.Connection) -> None:
        required_columns = {
            "source_post_id": "TEXT",
            "source_title": "TEXT",
            "source_permalink": "TEXT",
            "source_score": "INTEGER",
            "source_created_utc": "INTEGER",
        }
        existing_columns = self._column_names(conn, "sent_life_hacks")
        for column_name, column_type in required_columns.items():
            if column_name not in existing_columns:
                conn.execute(f"ALTER TABLE sent_life_hacks ADD COLUMN {column_name} {column_type}")

    def ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sent_life_hacks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sent_at TEXT NOT NULL,
                    message_text TEXT NOT NULL,
                    hack_text TEXT NOT NULL,
                    idea_key TEXT NOT NULL,
                    idea_summary TEXT NOT NULL,
                    message_probe TEXT NOT NULL,
                    hack_probe TEXT NOT NULL,
                    idea_key_probe TEXT NOT NULL,
                    idea_summary_probe TEXT NOT NULL
                )
                """
            )
            self._ensure_sent_columns(conn)
            conn.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_sent_life_hacks_message_probe
                ON sent_life_hacks(message_probe)
                """
            )
            conn.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_sent_life_hacks_idea_key_probe
                ON sent_life_hacks(idea_key_probe)
                """
            )
            conn.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_sent_life_hacks_source_post_id
                ON sent_life_hacks(source_post_id)
                """
            )
            conn.commit()

    def load_entries(self) -> list[HistoryEntry]:
        self.ensure_schema()
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    id,
                    sent_at,
                    message_text,
                    hack_text,
                    idea_key,
                    idea_summary,
                    message_probe,
                    hack_probe,
                    idea_key_probe,
                    idea_summary_probe,
                    source_post_id,
                    source_title,
                    source_permalink,
                    source_score,
                    source_created_utc
                FROM sent_life_hacks
                ORDER BY id ASC
                """
            ).fetchall()
        return [
            build_history_entry(
                entry_id=int(row["id"]),
                sent_at=str(row["sent_at"]),
                message_text=str(row["message_text"]),
                hack_text=str(row["hack_text"]),
                idea_key=str(row["idea_key"]),
                idea_summary=str(row["idea_summary"]),
                source_post_id=str(row["source_post_id"]) if row["source_post_id"] is not None else None,
                source_title=str(row["source_title"]) if row["source_title"] is not None else None,
                source_permalink=str(row["source_permalink"]) if row["source_permalink"] is not None else None,
                source_score=int(row["source_score"]) if row["source_score"] is not None else None,
                source_created_utc=int(row["source_created_utc"]) if row["source_created_utc"] is not None else None,
            )
            for row in rows
        ]

    def insert_sent_message(self, sent_at: datetime, message: SentLifeHack) -> None:
        self.ensure_schema()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO sent_life_hacks (
                    sent_at,
                    message_text,
                    hack_text,
                    idea_key,
                    idea_summary,
                    message_probe,
                    hack_probe,
                    idea_key_probe,
                    idea_summary_probe,
                    source_post_id,
                    source_title,
                    source_permalink,
                    source_score,
                    source_created_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    sent_at.isoformat(),
                    message.message_text,
                    message.hack_text,
                    message.idea_key,
                    message.idea_summary,
                    normalize_probe(message.message_text),
                    normalize_probe(message.hack_text),
                    normalize_probe(message.idea_key),
                    normalize_probe(message.idea_summary),
                    message.source_post_id,
                    message.source_title,
                    message.source_permalink,
                    message.source_score,
                    message.source_created_utc,
                ),
            )
            conn.commit()


class RedditCacheStore:
    def __init__(self, db_path: Path):
        self.db_path = db_path

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path), timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    def ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS reddit_cache_posts (
                    post_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    selftext TEXT NOT NULL,
                    permalink TEXT NOT NULL,
                    score INTEGER NOT NULL,
                    num_comments INTEGER NOT NULL,
                    created_utc INTEGER NOT NULL,
                    over_18 INTEGER NOT NULL DEFAULT 0,
                    title_probe TEXT NOT NULL,
                    body_probe TEXT NOT NULL,
                    cached_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_reddit_cache_posts_rank
                ON reddit_cache_posts(score DESC, num_comments DESC, created_utc DESC)
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS daily_uplift_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            conn.commit()

    def load_metadata(self) -> dict[str, str]:
        self.ensure_schema()
        with self._connect() as conn:
            rows = conn.execute("SELECT key, value FROM daily_uplift_metadata").fetchall()
        return {str(row["key"]): str(row["value"]) for row in rows}

    def set_metadata(self, key: str, value: str) -> None:
        self.ensure_schema()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO daily_uplift_metadata(key, value)
                VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value
                """,
                (key, value),
            )
            conn.commit()

    def upsert_posts(self, posts: list[RedditPost], refreshed_at: str) -> None:
        self.ensure_schema()
        with self._connect() as conn:
            for post in posts:
                conn.execute(
                    """
                    INSERT INTO reddit_cache_posts (
                        post_id,
                        title,
                        selftext,
                        permalink,
                        score,
                        num_comments,
                        created_utc,
                        over_18,
                        title_probe,
                        body_probe,
                        cached_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(post_id) DO UPDATE SET
                        title=excluded.title,
                        selftext=excluded.selftext,
                        permalink=excluded.permalink,
                        score=excluded.score,
                        num_comments=excluded.num_comments,
                        created_utc=excluded.created_utc,
                        over_18=excluded.over_18,
                        title_probe=excluded.title_probe,
                        body_probe=excluded.body_probe,
                        cached_at=excluded.cached_at
                    """,
                    (
                        post.post_id,
                        post.title,
                        post.selftext,
                        post.permalink,
                        post.score,
                        post.num_comments,
                        post.created_utc,
                        1 if post.over_18 else 0,
                        post.title_probe,
                        post.body_probe,
                        post.cached_at,
                    ),
                )
            conn.execute("DELETE FROM reddit_cache_posts WHERE created_utc < ?", (recent_cutoff_utc(),))
            conn.commit()
        self.set_metadata("reddit_cache_last_refresh", refreshed_at)
        self.set_metadata("reddit_cache_post_count", str(len(posts)))

    def load_recent_posts(self, cutoff_utc: int) -> list[RedditPost]:
        self.ensure_schema()
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    post_id,
                    title,
                    selftext,
                    permalink,
                    score,
                    num_comments,
                    created_utc,
                    over_18,
                    title_probe,
                    body_probe,
                    cached_at
                FROM reddit_cache_posts
                WHERE created_utc >= ?
                ORDER BY score DESC, num_comments DESC, created_utc DESC
                """,
                (cutoff_utc,),
            ).fetchall()
        return [
            RedditPost(
                post_id=str(row["post_id"]),
                title=str(row["title"]),
                selftext=str(row["selftext"]),
                permalink=str(row["permalink"]),
                score=int(row["score"]),
                num_comments=int(row["num_comments"]),
                created_utc=int(row["created_utc"]),
                over_18=bool(int(row["over_18"])),
                title_probe=str(row["title_probe"]),
                body_probe=str(row["body_probe"]),
                cached_at=str(row["cached_at"]),
            )
            for row in rows
        ]


def build_history_entry(
    entry_id: int,
    sent_at: str,
    message_text: str,
    hack_text: str,
    idea_key: str,
    idea_summary: str,
    source_post_id: Optional[str] = None,
    source_title: Optional[str] = None,
    source_permalink: Optional[str] = None,
    source_score: Optional[int] = None,
    source_created_utc: Optional[int] = None,
) -> HistoryEntry:
    return HistoryEntry(
        id=entry_id,
        sent_at=sent_at,
        message_text=message_text,
        hack_text=hack_text,
        idea_key=idea_key,
        idea_summary=idea_summary,
        message_probe=normalize_probe(message_text),
        hack_probe=normalize_probe(hack_text),
        idea_key_probe=normalize_probe(idea_key),
        idea_summary_probe=normalize_probe(idea_summary),
        source_post_id=source_post_id,
        source_title=source_title,
        source_permalink=source_permalink,
        source_score=source_score,
        source_created_utc=source_created_utc,
    )


def legacy_history_entries(group_name: str) -> list[HistoryEntry]:
    entries: list[HistoryEntry] = []
    for index, (hack_text, idea_key, idea_summary) in enumerate(LEGACY_BLOCKED_LIFE_HACKS, start=1):
        entries.append(
            build_history_entry(
                entry_id=-index,
                sent_at="legacy-rotation",
                message_text=build_daily_message(group_name, hack_text),
                hack_text=hack_text,
                idea_key=idea_key,
                idea_summary=idea_summary,
            )
        )
    return entries


def trim_reddit_selftext(text: str) -> str:
    cleaned = collapse_whitespace(html.unescape(text or ""))
    if not cleaned or cleaned in {"[removed]", "[deleted]"}:
        return ""
    if len(cleaned) <= MAX_REDDIT_BODY_CHARS:
        return cleaned
    return cleaned[: MAX_REDDIT_BODY_CHARS - 3].rstrip() + "..."


def trim_reddit_title(text: str) -> str:
    return collapse_whitespace(html.unescape(text or ""))


def build_reddit_post(item: dict[str, object], cached_at: str) -> Optional[RedditPost]:
    post_id = collapse_whitespace(str(item.get("id") or ""))
    title = trim_reddit_title(str(item.get("title") or ""))
    if not post_id or not title:
        return None
    permalink = collapse_whitespace(str(item.get("permalink") or ""))
    if not permalink:
        permalink = f"/r/LifeProTips/comments/{post_id}/"
    selftext = trim_reddit_selftext(str(item.get("selftext") or ""))
    score = int(item.get("score") or 0)
    num_comments = int(item.get("num_comments") or 0)
    created_utc = int(float(item.get("created_utc") or 0))
    over_18 = bool(item.get("over_18") or False)
    return RedditPost(
        post_id=post_id,
        title=title,
        selftext=selftext,
        permalink=permalink,
        score=score,
        num_comments=num_comments,
        created_utc=created_utc,
        over_18=over_18,
        title_probe=normalize_probe(title),
        body_probe=normalize_probe(selftext),
        cached_at=cached_at,
    )


def fetch_reddit_top_posts() -> list[RedditPost]:
    fetched_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    page_size = reddit_fetch_page_size()
    page_limit = reddit_fetch_pages()
    cutoff_utc = recent_cutoff_utc()
    headers = {"User-Agent": reddit_user_agent()}
    after: Optional[str] = None
    zero_recent_pages = 0
    posts_by_id: dict[str, RedditPost] = {}

    for _ in range(page_limit):
        params = {"t": "all", "limit": str(page_size)}
        if after:
            params["after"] = after
        endpoint = "https://www.reddit.com/r/LifeProTips/top.json?" + urllib.parse.urlencode(params)
        request = Request(endpoint, headers=headers)
        with urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))

        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, dict):
            raise RuntimeError("reddit returned unexpected payload")

        children = data.get("children")
        if not isinstance(children, list) or not children:
            break

        recent_in_page = 0
        for child in children:
            child_data = child.get("data") if isinstance(child, dict) else None
            if not isinstance(child_data, dict):
                continue
            post = build_reddit_post(child_data, fetched_at)
            if post is None:
                continue
            if post.over_18:
                continue
            if post.created_utc < cutoff_utc:
                continue
            recent_in_page += 1
            posts_by_id[post.post_id] = post

        after_value = data.get("after")
        after = str(after_value) if isinstance(after_value, str) and after_value.strip() else None
        if recent_in_page == 0:
            zero_recent_pages += 1
        else:
            zero_recent_pages = 0
        if not after or zero_recent_pages >= 2:
            break

    posts = sorted(
        posts_by_id.values(),
        key=lambda post: (post.score, post.num_comments, post.created_utc),
        reverse=True,
    )
    if not posts:
        raise RuntimeError("reddit cache refresh returned no usable LifeProTips posts")
    return posts


def cache_age_seconds(metadata: dict[str, str]) -> Optional[int]:
    last_refresh = metadata.get("reddit_cache_last_refresh", "").strip()
    if not last_refresh:
        return None
    normalized = last_refresh.replace("Z", "+00:00")
    try:
        refreshed_at = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if refreshed_at.tzinfo is None:
        refreshed_at = refreshed_at.replace(tzinfo=timezone.utc)
    return max(0, int((datetime.now(timezone.utc) - refreshed_at).total_seconds()))


def unused_recent_posts(
    posts: list[RedditPost],
    sent_source_ids: set[str],
) -> list[RedditPost]:
    return [post for post in posts if post.post_id not in sent_source_ids]


def ensure_reddit_cache_ready(
    cache_store: RedditCacheStore,
    sent_source_ids: set[str],
) -> dict[str, object]:
    cutoff_utc = recent_cutoff_utc()
    metadata = cache_store.load_metadata()
    posts = cache_store.load_recent_posts(cutoff_utc)
    unused_posts = unused_recent_posts(posts, sent_source_ids)
    age_seconds = cache_age_seconds(metadata)
    should_refresh = (
        age_seconds is None
        or age_seconds > reddit_cache_max_age_seconds()
        or len(unused_posts) < reddit_min_unused()
    )

    if should_refresh:
        refreshed_posts = fetch_reddit_top_posts()
        refreshed_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        cache_store.upsert_posts(refreshed_posts, refreshed_at)
        metadata = cache_store.load_metadata()
        posts = cache_store.load_recent_posts(cutoff_utc)
        unused_posts = unused_recent_posts(posts, sent_source_ids)
        age_seconds = cache_age_seconds(metadata)

    return {
        "recent_count": len(posts),
        "unused_recent_count": len(unused_posts),
        "last_refresh": metadata.get("reddit_cache_last_refresh"),
        "cache_age_seconds": age_seconds,
        "refreshed": should_refresh,
    }


def build_source_adaptation_prompt(
    group_name: str,
    source_post: RedditPost,
    history_entries: list[HistoryEntry],
) -> str:
    history_slice = history_entries[-PROMPT_HISTORY_LIMIT:]
    if history_slice:
        history_text = "\n".join(
            f"- {entry.idea_key} | {entry.idea_summary}" for entry in history_slice
        )
    else:
        history_text = "- none yet"

    source_block = f"Title: {source_post.title}\n"
    if source_post.selftext:
        source_block += f"Body: {source_post.selftext}\n"
    source_block += (
        f"Score: {source_post.score}\n"
        f"Comments: {source_post.num_comments}"
    )

    return f"""
Translate the full practical advice from this Reddit r/LifeProTips post into one Russian WhatsApp morning message for the group "{group_name}".

Return exactly one JSON object and nothing else. No markdown, no code fences, no commentary.
Required JSON keys:
- hack_text
- idea_key
- idea_summary

Requirements:
- Use the Reddit post below as the source of the life-hack idea.
- Preserve the full source advice in Russian for a family/group chat.
- Do not shorten, compress, summarize, or omit meaningful details from the source advice.
- If the title already contains the full tip, keep the full tip. If the body adds practical details, include those details too.
- Prefer near-complete translation over concise paraphrase.
- If the source contains multiple distinct advice clauses, keep all of them.
- Keep the same amount of practical detail as the source. When in doubt, be longer rather than shorter.
- Do not mention Reddit, subreddits, posts, comments, usernames, votes, links, or that this came from the internet.
- The underlying life-hack idea must still be genuinely different from every prior idea listed below.
- Do not paraphrase or lightly reword a prior idea. If the source overlaps with prior ideas, preserve the source faithfully anyway; the caller will reject overlaps and try another source.
- Keep it warm, light, positive, and useful.
- Use simple Russian.
- hack_text must be 1-7 short sentences and must not include Доброе утро or Даю справку.
- idea_key must be a short canonical description of the exact trick, 4-12 words, plain and specific.
- idea_summary must be 1-2 short sentences that restate the same trick canonically for duplicate detection.

The caller will wrap your hack like this:
Доброе утро, {group_name}! ☀️

Даю справку: <hack_text>

Prior life-hack ideas that must never be repeated or closely reused:
{history_text}

Source Reddit post:
{source_block}
""".strip()


def extract_json_object(raw_text: str) -> dict[str, object]:
    text = (raw_text or "").strip()
    if not text:
        raise RuntimeError("generator returned empty output")

    decoder = json.JSONDecoder()
    for start_index, char in enumerate(text):
        if char != "{":
            continue
        try:
            payload, _ = decoder.raw_decode(text[start_index:])
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    raise RuntimeError(f"generator did not return a JSON object: {text[:400]}")


def clean_generated_field(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise RuntimeError(f"generator field {field_name} must be a string")
    cleaned = collapse_whitespace(value)
    if not cleaned:
        raise RuntimeError(f"generator field {field_name} is empty")
    return cleaned


def parse_generated_life_hack(raw_text: str) -> GeneratedLifeHack:
    payload = extract_json_object(raw_text)
    hack_text = clean_generated_field(payload.get("hack_text"), "hack_text")
    idea_key = clean_generated_field(payload.get("idea_key"), "idea_key")
    idea_summary = clean_generated_field(payload.get("idea_summary"), "idea_summary")

    forbidden_fragments = ("доброе утро", "даю справку")
    lowered_hack = hack_text.lower()
    if any(fragment in lowered_hack for fragment in forbidden_fragments):
        raise RuntimeError("hack_text must not include greeting wrapper text")

    return GeneratedLifeHack(
        hack_text=hack_text,
        idea_key=idea_key,
        idea_summary=idea_summary,
    )


def similarity_against_history(candidate: GeneratedLifeHack, entry: HistoryEntry) -> Optional[SimilarityMatch]:
    key_score = best_similarity(candidate.idea_key, entry.idea_key)
    if key_score >= 0.66:
        return SimilarityMatch(entry=entry, reason="idea_key", score=key_score)

    summary_score = best_similarity(candidate.idea_summary, entry.idea_summary)
    if summary_score >= 0.70:
        return SimilarityMatch(entry=entry, reason="idea_summary", score=summary_score)

    hack_score = best_similarity(candidate.hack_text, entry.hack_text)
    if hack_score >= 0.82:
        return SimilarityMatch(entry=entry, reason="hack_text", score=hack_score)

    candidate_tokens = probe_tokens(candidate.idea_summary) | probe_tokens(candidate.idea_key)
    entry_tokens = probe_tokens(entry.idea_summary) | probe_tokens(entry.idea_key)
    overlap_score = overlap_similarity(candidate_tokens, entry_tokens)
    if overlap_score >= 0.75 and len(candidate_tokens & entry_tokens) >= 3:
        return SimilarityMatch(entry=entry, reason="token_overlap", score=overlap_score)

    return None


def find_similarity_match(
    candidate: GeneratedLifeHack,
    history_entries: list[HistoryEntry],
) -> Optional[SimilarityMatch]:
    best_match: Optional[SimilarityMatch] = None
    for entry in history_entries:
        match = similarity_against_history(candidate, entry)
        if match is None:
            continue
        if best_match is None or match.score > best_match.score:
            best_match = match
    return best_match


def codex_binary() -> str:
    return os.getenv("WA_DAILY_UPLIFT_CODEX_BIN", os.getenv("CODEX_BIN", "codex")).strip() or "codex"


def codex_workdir() -> str:
    override = os.getenv("WA_DAILY_UPLIFT_CODEX_WORKDIR", "").strip()
    if override:
        return override
    runtime_root = os.getenv("TELEGRAM_RUNTIME_ROOT", "").strip()
    if runtime_root:
        return runtime_root
    return os.getcwd()


def codex_model() -> str:
    return os.getenv("WA_DAILY_UPLIFT_CODEX_MODEL", "").strip()


def codex_reasoning_effort() -> str:
    return (
        os.getenv("WA_DAILY_UPLIFT_CODEX_REASONING_EFFORT", DEFAULT_CODEX_REASONING_EFFORT).strip()
        or DEFAULT_CODEX_REASONING_EFFORT
    )


def codex_timeout_seconds() -> int:
    raw_value = os.getenv("WA_DAILY_UPLIFT_CODEX_TIMEOUT_SECONDS", str(DEFAULT_CODEX_TIMEOUT_SECONDS)).strip()
    try:
        return max(30, int(raw_value))
    except ValueError:
        return DEFAULT_CODEX_TIMEOUT_SECONDS


def source_selection_attempt_limit() -> int:
    raw_value = os.getenv(
        "WA_DAILY_UPLIFT_SOURCE_SELECTION_ATTEMPTS",
        str(DEFAULT_SOURCE_SELECTION_ATTEMPTS),
    ).strip()
    try:
        return max(1, int(raw_value))
    except ValueError:
        return DEFAULT_SOURCE_SELECTION_ATTEMPTS


def run_codex_generation(prompt: str) -> str:
    code_bin = codex_binary()
    output_dir = state_dir_path() / "tmp"
    output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        prefix="daily-uplift-",
        suffix=".txt",
        dir=str(output_dir),
        delete=False,
    ) as temp_file:
        output_file = Path(temp_file.name)

    cmd = [
        code_bin,
        "exec",
        "--skip-git-repo-check",
        "--dangerously-bypass-approvals-and-sandbox",
        "--color",
        "never",
        "--output-last-message",
        str(output_file),
    ]
    model = codex_model()
    if model:
        cmd.extend(["--model", model])
    reasoning_effort = codex_reasoning_effort()
    if reasoning_effort:
        cmd.extend(["-c", f'model_reasoning_effort="{reasoning_effort}"'])
    cmd.append("-")

    env = dict(os.environ)
    env["HOME"] = env.get("HOME", str(Path.home()))

    result = subprocess.run(
        cmd,
        input=prompt,
        text=True,
        capture_output=True,
        timeout=codex_timeout_seconds(),
        cwd=codex_workdir(),
        env=env,
        check=False,
    )

    reply = ""
    try:
        if output_file.exists():
            reply = output_file.read_text(encoding="utf-8").strip()
    finally:
        output_file.unlink(missing_ok=True)

    if result.returncode != 0:
        detail = collapse_whitespace(result.stderr or result.stdout or reply)
        raise RuntimeError(
            f"codex generation failed with exit code {result.returncode}: {detail[:500]}"
        )
    if not reply:
        reply = (result.stdout or "").strip()
    if not reply:
        raise RuntimeError("codex generation returned no reply")
    return reply


def choose_source_posts(
    cache_store: RedditCacheStore,
    history_entries: list[HistoryEntry],
) -> tuple[list[RedditPost], dict[str, object]]:
    sent_source_ids = {
        entry.source_post_id
        for entry in history_entries
        if entry.source_post_id
    }
    cache_status = ensure_reddit_cache_ready(cache_store, sent_source_ids)
    recent_posts = cache_store.load_recent_posts(recent_cutoff_utc())
    candidates = unused_recent_posts(recent_posts, sent_source_ids)
    if not candidates:
        raise RuntimeError("reddit cache has no unused LifeProTips posts in the configured lookback window")
    return candidates, cache_status


def generate_reddit_sourced_life_hack(
    group_name: str,
    history_entries: list[HistoryEntry],
    candidate_posts: list[RedditPost],
) -> tuple[GeneratedLifeHack, RedditPost]:
    last_error: Optional[str] = None

    for source_post in candidate_posts[: source_selection_attempt_limit()]:
        prompt = build_source_adaptation_prompt(group_name, source_post, history_entries)
        try:
            candidate = parse_generated_life_hack(run_codex_generation(prompt))
        except Exception as exc:
            last_error = f"{source_post.post_id}: {exc}"
            continue

        match = find_similarity_match(candidate, history_entries)
        if match is not None:
            last_error = (
                f"{source_post.post_id}: candidate overlapped with prior idea "
                f"({match.reason}, score={match.score:.3f})"
            )
            continue

        return candidate, source_post

    raise RuntimeError(last_error or "failed to adapt a unique Reddit life hack")


def cache_status_payload(cache_store: RedditCacheStore, history_entries: list[HistoryEntry]) -> dict[str, object]:
    sent_source_ids = {
        entry.source_post_id
        for entry in history_entries
        if entry.source_post_id
    }
    metadata = cache_store.load_metadata()
    posts = cache_store.load_recent_posts(recent_cutoff_utc())
    return {
        "recent_count": len(posts),
        "unused_recent_count": len(unused_recent_posts(posts, sent_source_ids)),
        "last_refresh": metadata.get("reddit_cache_last_refresh"),
        "cache_age_seconds": cache_age_seconds(metadata),
        "lookback_days": reddit_lookback_days(),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Send daily uplifting WhatsApp life hack (RU).")
    parser.add_argument("--chat-id", default=os.getenv("WA_DAILY_UPLIFT_CHAT_ID", "").strip())
    parser.add_argument("--chat-jid", default=os.getenv("WA_DAILY_UPLIFT_CHAT_JID", "").strip())
    parser.add_argument("--test", action="store_true", help="Wrap payload as 1:1 preview text.")
    parser.add_argument("--dry-run", action="store_true", help="Print message without sending.")
    parser.add_argument(
        "--refresh-cache-only",
        action="store_true",
        help="Refresh the local Reddit cache and print status without generating a message.",
    )
    parser.add_argument(
        "--cache-status",
        action="store_true",
        help="Print local Reddit cache status without refreshing or sending.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    api_base = os.getenv("WA_DAILY_UPLIFT_API_BASE", "http://127.0.0.1:8787").strip()
    auth_token = os.getenv("WA_DAILY_UPLIFT_AUTH_TOKEN", "").strip()
    tz_name = os.getenv("WA_DAILY_UPLIFT_TZ", "Australia/Brisbane").strip()
    group_name = os.getenv("WA_DAILY_UPLIFT_GROUP_NAME", "Путиловы").strip() or "Путиловы"

    now_dt = now_in_tz(tz_name)
    db_path = uplift_db_path()
    history_store = HistoryStore(db_path)
    cache_store = RedditCacheStore(db_path)
    history_entries = legacy_history_entries(group_name) + history_store.load_entries()

    if args.cache_status:
        print(json.dumps(cache_status_payload(cache_store, history_entries), ensure_ascii=False))
        return 0

    if args.refresh_cache_only:
        sent_source_ids = {
            entry.source_post_id
            for entry in history_entries
            if entry.source_post_id
        }
        status = ensure_reddit_cache_ready(cache_store, sent_source_ids)
        print(json.dumps(status, ensure_ascii=False))
        return 0

    candidate_posts, _cache_status = choose_source_posts(cache_store, history_entries)
    life_hack, source_post = generate_reddit_sourced_life_hack(group_name, history_entries, candidate_posts)
    daily_message = build_daily_message(group_name, life_hack.hack_text)

    text = daily_message
    if args.test:
        text = (
            "Тест 1:1. Так будет выглядеть ежедневное сообщение в 09:00 для группы:\n\n"
            f"{daily_message}"
        )

    if args.dry_run:
        print(text)
        return 0

    payload = build_payload(args.chat_id or None, args.chat_jid or None, text)
    response = send_message(api_base, auth_token, payload)
    if not args.test:
        history_store.insert_sent_message(
            now_dt,
            SentLifeHack(
                message_text=daily_message,
                hack_text=life_hack.hack_text,
                idea_key=life_hack.idea_key,
                idea_summary=life_hack.idea_summary,
                source_post_id=source_post.post_id,
                source_title=source_post.title,
                source_permalink=f"https://www.reddit.com{source_post.permalink}",
                source_score=source_post.score,
                source_created_utc=source_post.created_utc,
            ),
        )
    print(json.dumps({"sent": True, "payload": payload, "response": response}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"send_daily_uplift failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
