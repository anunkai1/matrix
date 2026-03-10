from __future__ import annotations

import hashlib
import os
import shutil
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


SUMMARY_MAX_CHARS = 4000


@dataclass(frozen=True)
class AttachmentRecord:
    channel: str
    file_id: str
    media_kind: str
    local_path: str
    file_name: str
    mime_type: str
    file_size: int
    created_at: float
    expires_at: float
    summary: str


class AttachmentStore:
    def __init__(
        self,
        db_path: str,
        files_dir: str,
        *,
        retention_seconds: int,
        max_total_bytes: int,
    ) -> None:
        self.db_path = db_path
        self.files_dir = files_dir
        self.retention_seconds = max(0, int(retention_seconds))
        self.max_total_bytes = max(0, int(max_total_bytes))
        self._lock = threading.RLock()
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        Path(files_dir).mkdir(parents=True, exist_ok=True)
        self.ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def ensure_schema(self) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS attachments (
                    channel TEXT NOT NULL,
                    file_id TEXT NOT NULL,
                    media_kind TEXT NOT NULL,
                    local_path TEXT NOT NULL,
                    file_name TEXT NOT NULL DEFAULT '',
                    mime_type TEXT NOT NULL DEFAULT '',
                    file_size INTEGER NOT NULL DEFAULT 0,
                    sha256 TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL,
                    last_used_at REAL NOT NULL,
                    expires_at REAL NOT NULL,
                    summary TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY (channel, file_id)
                )
                """
            )
            conn.commit()

    def _expire_binary(self, conn: sqlite3.Connection, channel: str, file_id: str, local_path: str) -> None:
        row = conn.execute(
            "SELECT summary FROM attachments WHERE channel = ? AND file_id = ?",
            (channel, file_id),
        ).fetchone()
        summary = str(row["summary"] or "").strip() if row is not None else ""
        if summary:
            conn.execute(
                """
                UPDATE attachments
                SET local_path = '', file_size = 0, expires_at = 0, last_used_at = ?
                WHERE channel = ? AND file_id = ?
                """,
                (time.time(), channel, file_id),
            )
        else:
            conn.execute(
                "DELETE FROM attachments WHERE channel = ? AND file_id = ?",
                (channel, file_id),
            )
        try:
            if local_path:
                os.remove(local_path)
        except OSError:
            pass

    def prune(self) -> None:
        with self._lock, self._connect() as conn:
            now = time.time()
            rows = conn.execute(
                """
                SELECT channel, file_id, local_path, file_size, expires_at
                FROM attachments
                ORDER BY last_used_at ASC, created_at ASC
                """
            ).fetchall()

            total_bytes = 0
            live_rows = []
            for row in rows:
                local_path = str(row["local_path"] or "")
                expires_at = float(row["expires_at"] or 0)
                if expires_at and expires_at < now:
                    self._expire_binary(conn, str(row["channel"]), str(row["file_id"]), local_path)
                    continue
                if not local_path or not os.path.exists(local_path):
                    self._expire_binary(
                        conn,
                        str(row["channel"]),
                        str(row["file_id"]),
                        local_path,
                    )
                    continue
                file_size = int(row["file_size"] or 0)
                total_bytes += max(0, file_size)
                live_rows.append(row)

            if self.max_total_bytes > 0:
                while total_bytes > self.max_total_bytes and live_rows:
                    victim = live_rows.pop(0)
                    file_size = int(victim["file_size"] or 0)
                    total_bytes -= max(0, file_size)
                    self._expire_binary(
                        conn,
                        str(victim["channel"]),
                        str(victim["file_id"]),
                        str(victim["local_path"] or ""),
                    )

            conn.commit()

    def remember_file(
        self,
        *,
        channel: str,
        file_id: str,
        media_kind: str,
        source_path: str,
        file_name: str = "",
        mime_type: str = "",
    ) -> AttachmentRecord:
        normalized_channel = (channel or "telegram").strip().lower() or "telegram"
        normalized_file_id = (file_id or "").strip()
        if not normalized_file_id:
            raise ValueError("file_id is required")
        if not source_path or not os.path.exists(source_path):
            raise FileNotFoundError(source_path)

        self.prune()
        source = Path(source_path)
        suffix = Path(file_name).suffix or source.suffix
        sha256 = hashlib.sha256()
        with source.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                sha256.update(chunk)
        digest = sha256.hexdigest()
        local_path = str(Path(self.files_dir) / f"{digest}{suffix}")
        if not os.path.exists(local_path):
            shutil.copy2(source_path, local_path)

        stat = os.stat(local_path)
        now = time.time()
        expires_at = now + self.retention_seconds if self.retention_seconds > 0 else float("inf")

        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO attachments (
                    channel, file_id, media_kind, local_path, file_name, mime_type,
                    file_size, sha256, created_at, last_used_at, expires_at, summary
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, COALESCE(
                    (SELECT summary FROM attachments WHERE channel = ? AND file_id = ?),
                    ''
                ))
                ON CONFLICT(channel, file_id) DO UPDATE SET
                    media_kind = excluded.media_kind,
                    local_path = excluded.local_path,
                    file_name = excluded.file_name,
                    mime_type = excluded.mime_type,
                    file_size = excluded.file_size,
                    sha256 = excluded.sha256,
                    last_used_at = excluded.last_used_at,
                    expires_at = excluded.expires_at
                """,
                (
                    normalized_channel,
                    normalized_file_id,
                    media_kind,
                    local_path,
                    file_name.strip(),
                    mime_type.strip(),
                    int(stat.st_size),
                    digest,
                    now,
                    now,
                    expires_at,
                    normalized_channel,
                    normalized_file_id,
                ),
            )
            conn.commit()

        self.prune()
        record = self.get_record(normalized_channel, normalized_file_id)
        if record is None:
            raise RuntimeError("Attachment record was not persisted")
        return record

    def get_record(self, channel: str, file_id: str) -> Optional[AttachmentRecord]:
        self.prune()
        normalized_channel = (channel or "telegram").strip().lower() or "telegram"
        normalized_file_id = (file_id or "").strip()
        if not normalized_file_id:
            return None
        with self._lock, self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                    channel, file_id, media_kind, local_path, file_name, mime_type,
                    file_size, created_at, expires_at, summary
                FROM attachments
                WHERE channel = ? AND file_id = ?
                """,
                (normalized_channel, normalized_file_id),
            ).fetchone()
            if row is None:
                return None
            local_path = str(row["local_path"] or "")
            if not local_path or not os.path.exists(local_path):
                conn.commit()
                return None
            conn.execute(
                "UPDATE attachments SET last_used_at = ? WHERE channel = ? AND file_id = ?",
                (time.time(), normalized_channel, normalized_file_id),
            )
            conn.commit()
            return AttachmentRecord(
                channel=str(row["channel"]),
                file_id=str(row["file_id"]),
                media_kind=str(row["media_kind"]),
                local_path=local_path,
                file_name=str(row["file_name"] or ""),
                mime_type=str(row["mime_type"] or ""),
                file_size=int(row["file_size"] or 0),
                created_at=float(row["created_at"] or 0),
                expires_at=float(row["expires_at"] or 0),
                summary=str(row["summary"] or ""),
            )

    def get_summary(self, channel: str, file_id: str) -> str:
        normalized_channel = (channel or "telegram").strip().lower() or "telegram"
        normalized_file_id = (file_id or "").strip()
        if not normalized_file_id:
            return ""
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT summary FROM attachments WHERE channel = ? AND file_id = ?",
                (normalized_channel, normalized_file_id),
            ).fetchone()
            if row is None:
                return ""
            return str(row["summary"] or "").strip()

    def update_summary(self, channel: str, file_id: str, summary: str) -> None:
        normalized_channel = (channel or "telegram").strip().lower() or "telegram"
        normalized_file_id = (file_id or "").strip()
        if not normalized_file_id:
            return
        clean_summary = (summary or "").strip()
        if not clean_summary:
            return
        clean_summary = clean_summary[:SUMMARY_MAX_CHARS]
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                UPDATE attachments
                SET summary = ?, last_used_at = ?
                WHERE channel = ? AND file_id = ?
                """,
                (clean_summary, time.time(), normalized_channel, normalized_file_id),
            )
            conn.commit()
