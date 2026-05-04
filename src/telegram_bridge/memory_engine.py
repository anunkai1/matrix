import re
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence


RECENT_WINDOW_MAX_MESSAGES = None
RECENT_WINDOW_TOKEN_BUDGET = 10000


@dataclass
class TurnContext:
    conversation_key: str
    mode: str
    stateless: bool
    thread_id: Optional[str]
    prompt_text: str
    user_message_id: Optional[int]


@dataclass
class CommandResult:
    handled: bool
    response: Optional[str] = None
    run_prompt: Optional[str] = None
    stateless: bool = False


@dataclass
class MemoryStatus:
    conversation_key: str
    session_active: bool
    message_count: int


class MemoryEngine:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self._lock = threading.RLock()
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.ensure_schema()

    @staticmethod
    def telegram_key(chat_id: int) -> str:
        return f"tg:{chat_id}"

    @staticmethod
    def channel_key(channel: str, chat_id: int) -> str:
        normalized = (channel or "telegram").strip().lower()
        if normalized == "whatsapp":
            prefix = "wa"
        elif normalized == "signal":
            prefix = "sig"
        elif normalized == "telegram":
            prefix = "tg"
        else:
            safe = re.sub(r"[^a-z0-9]+", "_", normalized).strip("_")
            prefix = safe or "ch"
        return f"{prefix}:{chat_id}"

    @staticmethod
    def cli_key(profile_name: str = "default", namespace: str = "architect") -> str:
        profile = (profile_name or "default").strip() or "default"
        scope = (namespace or "architect").strip() or "architect"
        return f"cli:{scope}:{profile}"

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    @staticmethod
    def estimate_tokens(text: str) -> int:
        content = (text or "").strip()
        if not content:
            return 1
        return max(1, len(content) // 4)

    def ensure_schema(self) -> None:
        with self._lock, self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation_key TEXT NOT NULL,
                    channel TEXT NOT NULL,
                    sender_role TEXT NOT NULL,
                    sender_name TEXT NOT NULL,
                    text TEXT NOT NULL,
                    ts REAL NOT NULL,
                    token_estimate INTEGER NOT NULL,
                    is_bot INTEGER NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS sessions (
                    conversation_key TEXT PRIMARY KEY,
                    thread_id TEXT NOT NULL DEFAULT '',
                    updated_at REAL NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_messages_key_id
                    ON messages (conversation_key, id);
                CREATE INDEX IF NOT EXISTS idx_messages_key_ts
                    ON messages (conversation_key, ts);
                """
            )

    def get_session_thread_id(self, conversation_key: str) -> Optional[str]:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT thread_id FROM sessions WHERE conversation_key = ?",
                (conversation_key,),
            ).fetchone()
        if not row:
            return None
        thread_id = str(row["thread_id"] or "").strip()
        return thread_id or None

    def set_session_thread_id(self, conversation_key: str, thread_id: str) -> None:
        now = time.time()
        normalized = (thread_id or "").strip()
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO sessions (conversation_key, thread_id, updated_at)
                VALUES (?, ?, ?)
                """,
                (conversation_key, normalized, now),
            )

    def clear_session_thread_id(self, conversation_key: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM sessions WHERE conversation_key = ?", (conversation_key,))

    def clear_session(self, conversation_key: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM sessions WHERE conversation_key = ?", (conversation_key,))
            conn.execute("DELETE FROM messages WHERE conversation_key = ?", (conversation_key,))

    def _append_message(
        self,
        conn: sqlite3.Connection,
        conversation_key: str,
        channel: str,
        sender_role: str,
        sender_name: str,
        text: str,
        is_bot: bool,
    ) -> int:
        now = time.time()
        token_estimate = self.estimate_tokens(text)
        row = conn.execute(
            """
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
            """,
            (
                conversation_key,
                channel,
                sender_role,
                sender_name,
                text,
                now,
                token_estimate,
                1 if is_bot else 0,
            ),
        )
        return int(row.lastrowid)

    _CONTEXT_BLOCK_PATTERN = re.compile(
        r"Current Telegram Context:.+?Current User Message:\s*",
        re.DOTALL,
    )

    @classmethod
    def _strip_context_block(cls, text: str) -> str:
        stripped = cls._CONTEXT_BLOCK_PATTERN.sub("", (text or "")).strip()
        return stripped or (text or "").strip()

    def _load_recent_messages(
        self,
        conn: sqlite3.Connection,
        conversation_key: str,
        max_messages: Optional[int] = RECENT_WINDOW_MAX_MESSAGES,
        token_budget: int = RECENT_WINDOW_TOKEN_BUDGET,
    ) -> List[sqlite3.Row]:
        rows = conn.execute(
            """
            SELECT id, sender_role, sender_name, text, token_estimate
            FROM messages
            WHERE conversation_key = ?
            ORDER BY id DESC
            LIMIT 240
            """,
            (conversation_key,),
        ).fetchall()
        return self._select_recent_rows(rows, max_messages=max_messages, token_budget=token_budget)

    @staticmethod
    def _select_recent_rows(
        rows: Sequence[sqlite3.Row],
        *,
        max_messages: Optional[int],
        token_budget: int,
    ) -> List[sqlite3.Row]:
        selected: List[sqlite3.Row] = []
        token_total = 0
        for row in rows:
            row_tokens = max(1, int(row["token_estimate"] or 1))
            if max_messages is not None and selected and len(selected) >= max_messages:
                break
            if selected and token_total + row_tokens > token_budget:
                break
            selected.append(row)
            token_total += row_tokens
        selected.reverse()
        return selected

    def begin_turn(
        self,
        conversation_key: str,
        channel: str,
        sender_name: str,
        user_input: str,
        stateless: bool = False,
        thread_id_override: Optional[str] = None,
    ) -> TurnContext:
        clean_input = (user_input or "").strip()
        if not clean_input:
            raise ValueError("Input is empty")
        if stateless:
            return TurnContext(
                conversation_key=conversation_key,
                mode="stateless",
                stateless=True,
                thread_id=None,
                prompt_text=clean_input,
                user_message_id=None,
            )

        with self._lock, self._connect() as conn:
            recent_rows = self._load_recent_messages(conn, conversation_key)

            if thread_id_override is not None:
                thread_id = (thread_id_override or "").strip() or None
            else:
                thread_row = conn.execute(
                    "SELECT thread_id FROM sessions WHERE conversation_key = ?",
                    (conversation_key,),
                ).fetchone()
                thread_id = str(thread_row["thread_id"] if thread_row else "").strip() or None

            sections: List[str] = []
            if recent_rows:
                lines: List[str] = []
                for row in recent_rows:
                    role = str(row["sender_role"] or "user")
                    sender = str(row["sender_name"] or role)
                    raw_text = str(row["text"] or "")
                    clean_text = self._strip_context_block(raw_text)
                    text = " ".join(clean_text.split())
                    lines.append(f"- [{role}] {sender}: {text}")
                sections.append("Recent Messages:\n" + "\n".join(lines))
            sections.append(f"Current User Input:\n{clean_input.strip()}")
            prompt_text = "\n\n".join(sections).strip()

            user_message_id = self._append_message(
                conn,
                conversation_key=conversation_key,
                channel=channel,
                sender_role="user",
                sender_name=sender_name,
                text=clean_input,
                is_bot=False,
            )

        return TurnContext(
            conversation_key=conversation_key,
            mode="all_context",
            stateless=False,
            thread_id=thread_id,
            prompt_text=prompt_text,
            user_message_id=user_message_id,
        )

    def finish_turn(
        self,
        turn: TurnContext,
        channel: str,
        assistant_text: str,
        new_thread_id: Optional[str],
        assistant_name: str = "Architect",
    ) -> None:
        if turn.stateless:
            return
        normalized_assistant_name = (assistant_name or "").strip() or "Architect"
        text = (assistant_text or "").strip()
        if not text:
            text = f"(No output from {normalized_assistant_name})"

        with self._lock, self._connect() as conn:
            self._append_message(
                conn,
                conversation_key=turn.conversation_key,
                channel=channel,
                sender_role="assistant",
                sender_name=normalized_assistant_name,
                text=text,
                is_bot=True,
            )
            if new_thread_id and new_thread_id.strip():
                now = time.time()
                conn.execute(
                    """
                    INSERT OR REPLACE INTO sessions (conversation_key, thread_id, updated_at)
                    VALUES (?, ?, ?)
                    """,
                    (turn.conversation_key, new_thread_id.strip(), now),
                )

    def clear_all_session_threads(self) -> int:
        with self._lock, self._connect() as conn:
            count = int(
                conn.execute(
                    "SELECT COUNT(*) FROM sessions WHERE TRIM(thread_id) <> ''"
                ).fetchone()[0]
            )
            conn.execute("DELETE FROM sessions")
            return count

    def get_status(self, conversation_key: str) -> MemoryStatus:
        with self._lock, self._connect() as conn:
            session_row = conn.execute(
                "SELECT thread_id FROM sessions WHERE conversation_key = ?",
                (conversation_key,),
            ).fetchone()
            session = str(session_row["thread_id"] if session_row else "").strip()
            message_count = conn.execute(
                "SELECT COUNT(*) AS c FROM messages WHERE conversation_key = ?",
                (conversation_key,),
            ).fetchone()["c"]
        return MemoryStatus(
            conversation_key=conversation_key,
            session_active=bool(session.strip()),
            message_count=int(message_count),
        )

    def hard_reset_memory(self, conversation_key: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM sessions WHERE conversation_key = ?", (conversation_key,))
            conn.execute("DELETE FROM messages WHERE conversation_key = ?", (conversation_key,))

    def hard_reset_all_memory(self) -> dict:
        with self._lock, self._connect() as conn:
            counts = {
                "sessions": int(conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]),
                "messages": int(conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]),
            }
            conn.execute("DELETE FROM sessions")
            conn.execute("DELETE FROM messages")
            return counts

    def checkpoint_and_vacuum(self) -> None:
        with self._lock, self._connect() as conn:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            conn.execute("VACUUM")


def handle_memory_command(engine: MemoryEngine, conversation_key: str, text: str) -> CommandResult:
    raw = (text or "").strip()
    if not raw.startswith("/"):
        return CommandResult(handled=False)

    command = raw.split(maxsplit=1)[0].split("@", maxsplit=1)[0].lower()

    if command == "/ask":
        tail = raw.split(maxsplit=1)[1].strip() if len(raw.split(maxsplit=1)) > 1 else ""
        if not tail:
            return CommandResult(handled=True, response="Usage: /ask <prompt>")
        return CommandResult(handled=True, run_prompt=tail, stateless=True)

    if command in {"/memory", "/remember", "/forget", "/forget-all", "/reset-session", "/hard-reset-memory"}:
        return CommandResult(handled=True, response="Memory commands have been simplified. Use /reset to clear this chat.")

    return CommandResult(handled=False)


def build_memory_help_lines() -> List[str]:
    return []


def parse_natural_language_memory_intent(text: str) -> None:
    return None


def handle_natural_language_memory_query(engine, conversation_key, text, now=None) -> None:
    return None
