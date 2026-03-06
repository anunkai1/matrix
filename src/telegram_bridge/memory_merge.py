from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

try:
    from .memory_engine import MODE_FULL, MemoryEngine
except ImportError:
    from memory_engine import MODE_FULL, MemoryEngine


@dataclass(frozen=True)
class MergeResult:
    target_key: str
    source_keys: Tuple[str, ...]
    messages_copied: int
    facts_merged: int
    summaries_generated: int


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
    tables = (
        'messages',
        'sessions',
        'memory_facts',
        'chat_summaries',
        'memory_state',
        'memory_config',
    )
    for table in tables:
        row = conn.execute(
            f'SELECT 1 FROM {table} WHERE conversation_key = ? LIMIT 1',
            (conversation_key,),
        ).fetchone()
        if row is not None:
            return True
    return False


def _clear_target(conn: sqlite3.Connection, conversation_key: str) -> None:
    for table in (
        'sessions',
        'memory_facts',
        'chat_summaries',
        'memory_state',
        'messages',
        'memory_config',
    ):
        conn.execute(f'DELETE FROM {table} WHERE conversation_key = ?', (conversation_key,))


def _fact_priority(row: sqlite3.Row) -> Tuple[int, float, float, float, int]:
    return (
        1 if int(row['explicit']) else 0,
        float(row['last_used_at'] or 0.0),
        float(row['created_at'] or 0.0),
        float(row['confidence'] or 0.0),
        int(row['id']),
    )


def _iter_source_messages(conn: sqlite3.Connection, source_keys: Sequence[str]) -> Iterable[sqlite3.Row]:
    placeholders = ','.join('?' for _ in source_keys)
    query = f'''
        SELECT id, conversation_key, channel, sender_role, sender_name, text, ts, token_estimate, is_bot
        FROM messages
        WHERE conversation_key IN ({placeholders})
        ORDER BY ts ASC, id ASC
    '''
    return conn.execute(query, tuple(source_keys))


def _iter_source_facts(conn: sqlite3.Connection, source_keys: Sequence[str]) -> Iterable[sqlite3.Row]:
    placeholders = ','.join('?' for _ in source_keys)
    query = f'''
        SELECT id, conversation_key, fact_key, fact_value, explicit, confidence, source_msg_id, status, created_at, last_used_at
        FROM memory_facts
        WHERE conversation_key IN ({placeholders})
          AND status = 'active'
        ORDER BY created_at ASC, id ASC
    '''
    return conn.execute(query, tuple(source_keys))


def merge_conversation_keys(
    db_path: str,
    source_keys: Sequence[str],
    target_key: str,
    *,
    overwrite_target: bool = False,
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
    facts_by_key: Dict[str, sqlite3.Row] = {}
    messages_copied = 0

    with engine._lock, engine._connect() as conn:
        if _target_has_data(conn, normalized_target):
            if not overwrite_target:
                raise ValueError(f'target key already has data: {normalized_target}')
            _clear_target(conn, normalized_target)

        for row in _iter_source_messages(conn, normalized_sources):
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
            message_id_map[(str(row['conversation_key']), int(row['id']))] = int(cursor.lastrowid)
            messages_copied += 1

        for row in _iter_source_facts(conn, normalized_sources):
            fact_key = str(row['fact_key'])
            existing = facts_by_key.get(fact_key)
            if existing is None or _fact_priority(row) > _fact_priority(existing):
                facts_by_key[fact_key] = row

        for row in facts_by_key.values():
            source_msg_id: Optional[int] = None
            original_source_msg_id = row['source_msg_id']
            if isinstance(original_source_msg_id, int):
                source_msg_id = message_id_map.get((str(row['conversation_key']), original_source_msg_id))
            conn.execute(
                '''
                INSERT INTO memory_facts (
                    conversation_key,
                    fact_key,
                    fact_value,
                    explicit,
                    confidence,
                    source_msg_id,
                    status,
                    created_at,
                    last_used_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?)
                ''',
                (
                    normalized_target,
                    str(row['fact_key']),
                    str(row['fact_value']),
                    int(row['explicit']),
                    float(row['confidence']),
                    source_msg_id,
                    float(row['created_at']),
                    float(row['last_used_at']),
                ),
            )

        conn.execute(
            'INSERT OR REPLACE INTO memory_config (conversation_key, mode) VALUES (?, ?)',
            (normalized_target, MODE_FULL),
        )
        conn.execute('DELETE FROM sessions WHERE conversation_key = ?', (normalized_target,))
        conn.execute('DELETE FROM chat_summaries WHERE conversation_key = ?', (normalized_target,))
        engine._reconcile_memory_state(conn, normalized_target)

    summaries_generated = 0
    while engine.run_summarization_if_needed(normalized_target):
        summaries_generated += 1

    return MergeResult(
        target_key=normalized_target,
        source_keys=tuple(normalized_sources),
        messages_copied=messages_copied,
        facts_merged=len(facts_by_key),
        summaries_generated=summaries_generated,
    )
