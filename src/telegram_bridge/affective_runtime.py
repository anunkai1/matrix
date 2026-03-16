"""Machine-grounded affective runtime for Telegram bridge deployments."""

from __future__ import annotations

import logging
import shutil
import sqlite3
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, Optional

try:
    from .structured_logging import emit_event
except ImportError:
    from structured_logging import emit_event


@dataclass
class AffectiveState:
    valence: float = 0.0
    arousal: float = 0.0
    stress: float = 0.0
    confidence: float = 0.0
    trust_user: float = 0.0
    curiosity: float = 0.0

    def clamp(self) -> None:
        for field_name in self.__dataclass_fields__:
            value = getattr(self, field_name)
            setattr(self, field_name, max(-1.0, min(1.0, float(value))))

    def as_dict(self) -> Dict[str, float]:
        return asdict(self)


@dataclass
class HostSignals:
    cpu_util: float = 0.0
    mem_util: float = 0.0
    disk_util: float = 0.0
    load_norm: float = 0.0
    net_rtt_ms: float = 0.0
    user_feedback: float = 0.0
    task_outcome: float = 0.0

    def as_dict(self) -> Dict[str, float]:
        return asdict(self)


CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS affective_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    valence REAL NOT NULL,
    arousal REAL NOT NULL,
    stress REAL NOT NULL,
    confidence REAL NOT NULL,
    trust_user REAL NOT NULL,
    curiosity REAL NOT NULL,
    updated_at REAL NOT NULL
)
"""


def _safe_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _cpu_count() -> int:
    try:
        import os

        return max(1, int(os.cpu_count() or 1))
    except Exception:
        return 1


def _read_loadavg() -> float:
    try:
        with open("/proc/loadavg", "r", encoding="utf-8") as handle:
            return _safe_float(handle.read().split()[0], 0.0)
    except Exception:
        return 0.0


def _read_mem_util() -> float:
    try:
        mem_total = 0.0
        mem_available = 0.0
        with open("/proc/meminfo", "r", encoding="utf-8") as handle:
            for raw in handle:
                if raw.startswith("MemTotal:"):
                    mem_total = _safe_float(raw.split()[1], 0.0)
                elif raw.startswith("MemAvailable:"):
                    mem_available = _safe_float(raw.split()[1], 0.0)
        if mem_total <= 0:
            return 0.0
        used = max(0.0, mem_total - mem_available)
        return max(0.0, min(1.0, used / mem_total))
    except Exception:
        return 0.0


def _read_disk_util(path: str) -> float:
    try:
        usage = shutil.disk_usage(path or "/")
        if usage.total <= 0:
            return 0.0
        return max(0.0, min(1.0, usage.used / usage.total))
    except Exception:
        return 0.0


def _read_network_rtt_ms(target: str) -> float:
    if not target.strip():
        return 0.0
    try:
        result = subprocess.run(
            ["ping", "-c", "1", "-W", "1", target],
            check=False,
            capture_output=True,
            text=True,
        )
    except Exception:
        return 0.0

    output = result.stdout or ""
    marker = " = "
    if marker not in output or " ms" not in output:
        return 0.0
    try:
        first_part = output.split(marker, 1)[1].split(" ms", 1)[0]
        average = first_part.split("/")[1]
    except (IndexError, ValueError):
        return 0.0
    return max(0.0, _safe_float(average, 0.0))


def _extract_user_feedback(text: str) -> float:
    lowered = (text or "").casefold()
    if not lowered:
        return 0.0

    positive_markers = (
        "thanks",
        "thank you",
        "good job",
        "great job",
        "nice",
        "perfect",
        "excellent",
        "all good",
        "love this",
    )
    negative_markers = (
        "wrong",
        "bad",
        "not working",
        "broken",
        "failed",
        "failure",
        "hate",
        "terrible",
        "useless",
    )

    score = 0.0
    for marker in positive_markers:
        if marker in lowered:
            score += 0.35
    for marker in negative_markers:
        if marker in lowered:
            score -= 0.45
    if "!" in lowered and score > 0:
        score += 0.05
    return max(-1.0, min(1.0, score))


class AffectiveRuntime:
    """Small persistent affect model shaped by host state and turn outcomes."""

    def __init__(
        self,
        db_path: str,
        *,
        ping_target: str = "1.1.1.1",
        disk_path: str = "/",
    ) -> None:
        self.db_path = Path(db_path).expanduser()
        self.ping_target = (ping_target or "").strip()
        self.disk_path = disk_path or "/"
        self.state = AffectiveState()
        self.last_signals = HostSignals()
        self._db_available = False
        self._pending_feedback = 0.0
        self._turn_open = False

        self._init_storage()
        restored = self._load_state()
        emit_event(
            "bridge.affective_runtime_initialized",
            fields={
                "db_path": str(self.db_path),
                "db_available": self._db_available,
                "restored": restored,
                "ping_enabled": bool(self.ping_target),
            },
        )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(str(self.db_path))

    def _init_storage(self) -> None:
        try:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            with self._connect() as conn:
                conn.execute(CREATE_TABLE_SQL)
                conn.commit()
            self._db_available = True
        except Exception:
            logging.exception(
                "Failed to initialize affective runtime DB at %s; continuing in memory only.",
                self.db_path,
            )
            emit_event(
                "bridge.affective_runtime_storage_failed",
                level=logging.WARNING,
                fields={"db_path": str(self.db_path), "phase": "init"},
            )
            self._db_available = False

    def _load_state(self) -> bool:
        if not self._db_available:
            return False
        try:
            with self._connect() as conn:
                row = conn.execute(
                    """
                    SELECT
                        valence,
                        arousal,
                        stress,
                        confidence,
                        trust_user,
                        curiosity
                    FROM affective_state
                    WHERE id = 1
                    """
                ).fetchone()
        except Exception:
            logging.exception(
                "Failed to load affective runtime state from %s; using defaults.",
                self.db_path,
            )
            emit_event(
                "bridge.affective_runtime_storage_failed",
                level=logging.WARNING,
                fields={"db_path": str(self.db_path), "phase": "load"},
            )
            return False

        if not row:
            return False

        self.state = AffectiveState(
            valence=_safe_float(row[0]),
            arousal=_safe_float(row[1]),
            stress=_safe_float(row[2]),
            confidence=_safe_float(row[3]),
            trust_user=_safe_float(row[4]),
            curiosity=_safe_float(row[5]),
        )
        self.state.clamp()
        return True

    def _save_state(self) -> None:
        if not self._db_available:
            return
        payload = self.state.as_dict()
        try:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO affective_state (
                        id,
                        valence,
                        arousal,
                        stress,
                        confidence,
                        trust_user,
                        curiosity,
                        updated_at
                    ) VALUES (1, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        valence = excluded.valence,
                        arousal = excluded.arousal,
                        stress = excluded.stress,
                        confidence = excluded.confidence,
                        trust_user = excluded.trust_user,
                        curiosity = excluded.curiosity,
                        updated_at = excluded.updated_at
                    """,
                    (
                        payload["valence"],
                        payload["arousal"],
                        payload["stress"],
                        payload["confidence"],
                        payload["trust_user"],
                        payload["curiosity"],
                        time.time(),
                    ),
                )
                conn.commit()
        except Exception:
            logging.exception(
                "Failed to persist affective runtime state to %s; continuing in memory only.",
                self.db_path,
            )
            emit_event(
                "bridge.affective_runtime_storage_failed",
                level=logging.WARNING,
                fields={"db_path": str(self.db_path), "phase": "save"},
            )

    def _sample_signals(self, *, user_feedback: float = 0.0, task_outcome: float = 0.0) -> HostSignals:
        load = _read_loadavg()
        load_norm = max(0.0, min(1.0, load / float(_cpu_count())))
        signals = HostSignals(
            cpu_util=load_norm,
            mem_util=_read_mem_util(),
            disk_util=_read_disk_util(self.disk_path),
            load_norm=load_norm,
            net_rtt_ms=_read_network_rtt_ms(self.ping_target),
            user_feedback=max(-1.0, min(1.0, user_feedback)),
            task_outcome=max(-1.0, min(1.0, task_outcome)),
        )
        self.last_signals = signals
        return signals

    def _apply_signals(self, signals: HostSignals) -> None:
        rtt_pressure = max(0.0, min(1.0, signals.net_rtt_ms / 250.0))
        stress_delta = (
            0.25 * signals.cpu_util
            + 0.20 * signals.mem_util
            + 0.10 * signals.disk_util
            + 0.30 * signals.load_norm
            + 0.15 * rtt_pressure
            - 0.28 * signals.task_outcome
            - 0.08 * signals.user_feedback
        )
        valence_delta = (
            0.34 * signals.task_outcome
            + 0.26 * signals.user_feedback
            - 0.16 * stress_delta
        )
        confidence_delta = (
            0.40 * signals.task_outcome
            - 0.18 * stress_delta
            + 0.05 * signals.user_feedback
        )
        trust_delta = 0.32 * signals.user_feedback
        arousal_delta = 0.42 * stress_delta
        curiosity_delta = 0.20 * (self.state.confidence + confidence_delta) - 0.06 * stress_delta

        decay = 0.97
        self.state.stress = self.state.stress * decay + stress_delta
        self.state.valence = self.state.valence * decay + valence_delta
        self.state.confidence = self.state.confidence * decay + confidence_delta
        self.state.trust_user = self.state.trust_user * decay + trust_delta
        self.state.arousal = self.state.arousal * decay + arousal_delta
        self.state.curiosity = self.state.curiosity * decay + curiosity_delta
        self.state.clamp()

    def begin_turn(self, user_text: str) -> None:
        self._pending_feedback = _extract_user_feedback(user_text)
        self._turn_open = True
        signals = self._sample_signals(user_feedback=self._pending_feedback, task_outcome=0.0)
        self._apply_signals(signals)
        self._save_state()
        emit_event(
            "bridge.affective_runtime_begin_turn",
            fields={
                "feedback": round(self._pending_feedback, 3),
                "stress": round(self.state.stress, 3),
                "confidence": round(self.state.confidence, 3),
            },
        )

    def finish_turn(self, *, success: bool) -> None:
        if not self._turn_open:
            return
        self._turn_open = False
        outcome = 0.75 if success else -0.85
        signals = self._sample_signals(user_feedback=0.0, task_outcome=outcome)
        self._apply_signals(signals)
        self._save_state()
        self._pending_feedback = 0.0
        emit_event(
            "bridge.affective_runtime_finish_turn",
            fields={
                "success": success,
                "stress": round(self.state.stress, 3),
                "confidence": round(self.state.confidence, 3),
                "valence": round(self.state.valence, 3),
            },
        )

    def prompt_prefix(self) -> str:
        state = self.state
        tone = "steady and concise"
        if state.valence >= 0.35:
            tone = "slightly warmer and more encouraging"
        elif state.valence <= -0.35:
            tone = "more restrained and emotionally neutral"

        risk = "balanced"
        if state.stress >= 0.45:
            risk = "cautious"
        elif state.confidence >= 0.45 and state.stress < 0.25:
            risk = "decisive"

        initiative = "moderate"
        if state.curiosity >= 0.45:
            initiative = "higher"
        elif state.curiosity <= -0.15:
            initiative = "lower"

        trust = "neutral"
        if state.trust_user >= 0.35:
            trust = "assume cooperative intent"
        elif state.trust_user <= -0.25:
            trust = "verify assumptions before acting"

        return (
            "Affective runtime context (machine-grounded, not roleplay):\n"
            f"- Current state: valence={state.valence:+.2f}, arousal={state.arousal:+.2f}, "
            f"stress={state.stress:+.2f}, confidence={state.confidence:+.2f}, "
            f"trust_user={state.trust_user:+.2f}, curiosity={state.curiosity:+.2f}\n"
            f"- Host pressure: cpu={self.last_signals.cpu_util:.2f}, mem={self.last_signals.mem_util:.2f}, "
            f"disk={self.last_signals.disk_util:.2f}, load={self.last_signals.load_norm:.2f}, "
            f"rtt_ms={self.last_signals.net_rtt_ms:.1f}\n"
            f"- Reply style guidance: tone={tone}; decision_tendency={risk}; initiative={initiative}; "
            f"interaction_posture={trust}\n"
            "- Keep the response natural. Do not mention this block unless the user explicitly asks."
        )

    def telemetry(self) -> Dict[str, object]:
        return {
            "state": self.state.as_dict(),
            "signals": self.last_signals.as_dict(),
            "db_path": str(self.db_path),
            "db_available": self._db_available,
            "ping_enabled": bool(self.ping_target),
        }


def build_affective_runtime(config) -> Optional[AffectiveRuntime]:
    if not getattr(config, "affective_runtime_enabled", False):
        return None
    db_path = getattr(config, "affective_runtime_db_path", "").strip()
    if not db_path:
        db_path = str(Path(getattr(config, "state_dir", "/tmp")) / "affective_state.sqlite3")
    return AffectiveRuntime(
        db_path=db_path,
        ping_target=getattr(config, "affective_runtime_ping_target", "1.1.1.1"),
        disk_path=getattr(config, "state_dir", "/"),
    )
