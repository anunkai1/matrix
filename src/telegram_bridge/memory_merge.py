from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

try:
    from .memory_engine import MemoryEngine
except ImportError:
    from memory_engine import MemoryEngine


@dataclass(frozen=True)
class MergeResult:
    target_key: str
    source_keys: Tuple[str, ...]
    messages_copied: int
    facts_merged: int = 0
    summaries_generated: int = 0


def _normalize_keys(keys: Sequence[str]) -> List[str]:
    normalized: List[str] = []
    seen = set()
    for key in keys:
        candidate = (key or '').strip()
        if not candidate or candidate in seen:
            continue
        normalized.append(candidate)
        seen.add(candidate)
    return normalized


def _target_has_data(conn: sqlite3.Connection, conversation_key: str) -> bool:
    for table in ('messages', 'sessions'):
        row = conn.execute(
            f'SELECT 1 FROM {table} WHERE conversation_key = ? LIMIT 1',
            (conversation_key,),
        ).fetchone()
        if row is not None:
            return True
    return False


def _clear_target(conn: sqlite3.Connection, conversation_key: str) -> None:
    for table in ('sessions', 'messages'):
        conn.execute(f'DELETE FROM {table} WHERE conversation_key = ?', (conversation_key,))


def _iter_source_messages(conn: sqlite3.Connection, source_keys: Sequence[str]) -> Iterable[sqlite3.Row]:
    placeholders = ','.join('?' for _ in source_keys)
    query = f'''
        SELECT id, conversation_key, channel, sender_role, sender_name, text, ts, token_estimate, is_bot
        FROM messages
        WHERE conversation_key IN ({placeholders})
        ORDER BY ts ASC, id ASC
    '''
    return conn.execute(query, tuple(source_keys))


def _message_signature(row: sqlite3.Row) -> Tuple[str, str, str, str, float, int, int]:
    return (
        str(row['channel']),
        str(row['sender_role']),
        str(row['sender_name']),
        str(row['text']),
        float(row['ts']),
        int(row['token_estimate']),
        int(row['is_bot']),
    )


def merge_conversation_keys(
    db_path: str,
    source_keys: Sequence[str],
    target_key: str,
    *,
    overwrite_target: bool = False,
    allow_existing_target: bool = False,
    force_summarize_target: bool = False,
    min_message_score: Optional[float] = None,
) -> MergeResult:
    normalized_target = (target_key or '').strip()
    if not normalized_target:
        raise ValueError('target_key is required')

    normalized_sources = _normalize_keys(source_keys)
    if not normalized_sources:
        raise ValueError('at least one source key is required')
    if normalized_target in normalized_sources:
        raise ValueError('target_key cannot also be a source key')

    engine = MemoryEngine(db_path)
    message_id_map: Dict[Tuple[str, int], int] = {}
    messages_copied = 0

    with engine._lock, engine._connect() as conn:
        if _target_has_data(conn, normalized_target):
            if not overwrite_target and not allow_existing_target:
                raise ValueError(f'target key already has data: {normalized_target}')
            if overwrite_target:
                _clear_target(conn, normalized_target)

        existing_target_message_map: Dict[Tuple[str, str, str, str, float, int, int], int] = {}
        if allow_existing_target:
            for row in conn.execute(
                '''
                SELECT id, channel, sender_role, sender_name, text, ts, token_estimate, is_bot
                FROM messages
                WHERE conversation_key = ?
                ORDER BY id ASC
                ''',
                (normalized_target,),
            ):
                existing_target_message_map[_message_signature(row)] = int(row['id'])

        for row in _iter_source_messages(conn, normalized_sources):
            signature = _message_signature(row)
            existing_message_id = existing_target_message_map.get(signature)
            if existing_message_id is not None:
                message_id_map[(str(row['conversation_key']), int(row['id']))] = existing_message_id
                continue
            cursor = conn.execute(
                '''
                INSERT INTO messages (
                    conversation_key,
                    channel,
                    sender_role,
                    sender_name,
                    text,
                    ts,
                    token_estimate,
                    is_bot
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''',
                (
                    normalized_target,
                    str(row['channel']),
                    str(row['sender_role']),
                    str(row['sender_name']),
                    str(row['text']),
                    float(row['ts']),
                    int(row['token_estimate']),
                    int(row['is_bot']),
                ),
            )
            inserted_message_id = int(cursor.lastrowid)
            message_id_map[(str(row['conversation_key']), int(row['id']))] = inserted_message_id
            existing_target_message_map[signature] = inserted_message_id
            messages_copied += 1

    return MergeResult(
        target_key=normalized_target,
        source_keys=tuple(normalized_sources),
        messages_copied=messages_copied,
    )
