from __future__ import annotations

import json
import tempfile
import time
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple


def _normalize_phrase(value: str) -> str:
    return " ".join((value or "").strip().split()).casefold()


def _pair_key(source: str, target: str) -> str:
    return f"{_normalize_phrase(source)}=>{_normalize_phrase(target)}"


@dataclass
class VoiceAliasSuggestion:
    suggestion_id: int
    source: str
    target: str
    count: int
    created_at: float
    last_seen_at: float


@dataclass
class VoiceAliasLearningResult:
    consumed: bool
    suggestion_created: List[VoiceAliasSuggestion]
    extracted_pairs: List[Tuple[str, str]]


class VoiceAliasLearningStore:
    def __init__(
        self,
        *,
        path: str,
        min_examples: int = 2,
        confirmation_window_seconds: int = 900,
        max_phrase_words: int = 5,
    ) -> None:
        self.path = path
        self.min_examples = max(1, int(min_examples))
        self.confirmation_window_seconds = max(30, int(confirmation_window_seconds))
        self.max_phrase_words = max(1, int(max_phrase_words))

        self._next_id = 1
        self._counts: Dict[str, int] = {}
        self._pending: Dict[int, VoiceAliasSuggestion] = {}
        self._approved: Dict[str, Tuple[str, str]] = {}
        self._ignored: Dict[str, float] = {}
        self._pending_confirmation_by_chat: Dict[int, Dict[str, object]] = {}
        self._load()

    def _load(self) -> None:
        data_path = Path(self.path)
        if not data_path.exists():
            return
        raw = json.loads(data_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return
        self._next_id = int(raw.get("next_id", 1) or 1)

        counts = raw.get("counts")
        if isinstance(counts, dict):
            for key, value in counts.items():
                if not isinstance(key, str):
                    continue
                if not isinstance(value, int):
                    continue
                if value <= 0:
                    continue
                self._counts[key] = value

        approved = raw.get("approved")
        if isinstance(approved, list):
            for item in approved:
                if not isinstance(item, dict):
                    continue
                source = item.get("source")
                target = item.get("target")
                if not isinstance(source, str) or not isinstance(target, str):
                    continue
                source = " ".join(source.strip().split())
                target = " ".join(target.strip().split())
                if not source or not target:
                    continue
                self._approved[_pair_key(source, target)] = (source, target)

        ignored = raw.get("ignored")
        if isinstance(ignored, dict):
            for key, value in ignored.items():
                if not isinstance(key, str):
                    continue
                if not isinstance(value, (int, float)):
                    continue
                self._ignored[key] = float(value)

        pending = raw.get("pending")
        if isinstance(pending, list):
            for item in pending:
                if not isinstance(item, dict):
                    continue
                suggestion_id = item.get("id")
                source = item.get("source")
                target = item.get("target")
                count = item.get("count")
                created_at = item.get("created_at")
                last_seen_at = item.get("last_seen_at")
                if not isinstance(suggestion_id, int):
                    continue
                if not isinstance(source, str) or not isinstance(target, str):
                    continue
                if not isinstance(count, int):
                    continue
                if not isinstance(created_at, (int, float)):
                    continue
                if not isinstance(last_seen_at, (int, float)):
                    continue
                suggestion = VoiceAliasSuggestion(
                    suggestion_id=suggestion_id,
                    source=source,
                    target=target,
                    count=count,
                    created_at=float(created_at),
                    last_seen_at=float(last_seen_at),
                )
                self._pending[suggestion_id] = suggestion

    def _persist(self) -> None:
        data = {
            "version": 1,
            "next_id": self._next_id,
            "counts": dict(sorted(self._counts.items())),
            "approved": [
                {"source": source, "target": target}
                for source, target in sorted(self._approved.values(), key=lambda item: item[0].casefold())
            ],
            "ignored": dict(sorted(self._ignored.items())),
            "pending": [
                {
                    "id": suggestion.suggestion_id,
                    "source": suggestion.source,
                    "target": suggestion.target,
                    "count": suggestion.count,
                    "created_at": suggestion.created_at,
                    "last_seen_at": suggestion.last_seen_at,
                }
                for suggestion in sorted(self._pending.values(), key=lambda value: value.suggestion_id)
            ],
        }
        destination = Path(self.path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=str(destination.parent),
            prefix=f".{destination.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            json.dump(data, handle, ensure_ascii=True, indent=2, sort_keys=True)
            handle.write("\n")
            temp_name = handle.name
        Path(temp_name).replace(destination)

    def register_low_confidence_transcript(
        self,
        *,
        chat_id: int,
        transcript: str,
        confidence: Optional[float],
    ) -> None:
        transcript_value = " ".join((transcript or "").strip().split())
        if not transcript_value:
            return
        self._pending_confirmation_by_chat[chat_id] = {
            "transcript": transcript_value,
            "confidence": float(confidence) if isinstance(confidence, (int, float)) else None,
            "created_at": time.time(),
        }

    def _extract_pairs(self, source_text: str, confirmed_text: str) -> List[Tuple[str, str]]:
        source_words = source_text.split()
        target_words = confirmed_text.split()
        matcher = SequenceMatcher(a=[word.casefold() for word in source_words], b=[word.casefold() for word in target_words])

        seen: set[str] = set()
        pairs: List[Tuple[str, str]] = []
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag != "replace":
                continue
            source_tokens = source_words[i1:i2]
            target_tokens = target_words[j1:j2]

            # For single-token replacements, include one stable neighbor when available.
            if (
                len(source_tokens) == 1
                and len(target_tokens) == 1
                and i1 > 0
                and j1 > 0
                and source_words[i1 - 1].casefold() == target_words[j1 - 1].casefold()
            ):
                source_tokens = [source_words[i1 - 1], source_tokens[0]]
                target_tokens = [target_words[j1 - 1], target_tokens[0]]
            elif (
                len(source_tokens) == 1
                and len(target_tokens) == 1
                and i2 < len(source_words)
                and j2 < len(target_words)
                and source_words[i2].casefold() == target_words[j2].casefold()
            ):
                source_tokens = [source_tokens[0], source_words[i2]]
                target_tokens = [target_tokens[0], target_words[j2]]

            source_phrase = " ".join(source_tokens).strip()
            target_phrase = " ".join(target_tokens).strip()
            if not source_phrase or not target_phrase:
                continue
            if _normalize_phrase(source_phrase) == _normalize_phrase(target_phrase):
                continue
            if len(source_phrase.split()) > self.max_phrase_words:
                continue
            if len(target_phrase.split()) > self.max_phrase_words:
                continue
            key = _pair_key(source_phrase, target_phrase)
            if key in seen:
                continue
            seen.add(key)
            pairs.append((source_phrase, target_phrase))
        return pairs

    def consume_confirmation(
        self,
        *,
        chat_id: int,
        confirmed_text: str,
        active_replacements: Iterable[Tuple[str, str]],
    ) -> VoiceAliasLearningResult:
        pending = self._pending_confirmation_by_chat.pop(chat_id, None)
        if not isinstance(pending, dict):
            return VoiceAliasLearningResult(consumed=False, suggestion_created=[], extracted_pairs=[])

        created_at = pending.get("created_at")
        if not isinstance(created_at, (int, float)):
            return VoiceAliasLearningResult(consumed=False, suggestion_created=[], extracted_pairs=[])
        if (time.time() - float(created_at)) > float(self.confirmation_window_seconds):
            return VoiceAliasLearningResult(consumed=False, suggestion_created=[], extracted_pairs=[])

        source_text = str(pending.get("transcript") or "").strip()
        confirmed_value = " ".join((confirmed_text or "").strip().split())
        if not source_text or not confirmed_value:
            return VoiceAliasLearningResult(consumed=False, suggestion_created=[], extracted_pairs=[])

        active_keys = {_pair_key(source, target) for source, target in active_replacements}
        extracted = self._extract_pairs(source_text, confirmed_value)
        created: List[VoiceAliasSuggestion] = []
        changed = False
        now = time.time()
        for source_phrase, target_phrase in extracted:
            key = _pair_key(source_phrase, target_phrase)
            if key in active_keys:
                continue
            if key in self._approved:
                continue
            if key in self._ignored:
                continue
            count = self._counts.get(key, 0) + 1
            self._counts[key] = count
            changed = True

            existing_pending = next(
                (item for item in self._pending.values() if _pair_key(item.source, item.target) == key),
                None,
            )
            if existing_pending is not None:
                existing_pending.count = count
                existing_pending.last_seen_at = now
                continue

            if count < self.min_examples:
                continue

            suggestion = VoiceAliasSuggestion(
                suggestion_id=self._next_id,
                source=source_phrase,
                target=target_phrase,
                count=count,
                created_at=now,
                last_seen_at=now,
            )
            self._next_id += 1
            self._pending[suggestion.suggestion_id] = suggestion
            created.append(suggestion)

        if changed:
            self._persist()
        return VoiceAliasLearningResult(consumed=True, suggestion_created=created, extracted_pairs=extracted)

    def list_pending(self) -> List[VoiceAliasSuggestion]:
        return sorted(self._pending.values(), key=lambda item: item.suggestion_id)

    def get_approved_replacements(self) -> List[Tuple[str, str]]:
        return sorted(self._approved.values(), key=lambda item: item[0].casefold())

    def approve(self, suggestion_id: int) -> Optional[VoiceAliasSuggestion]:
        suggestion = self._pending.pop(suggestion_id, None)
        if suggestion is None:
            return None
        self._approved[_pair_key(suggestion.source, suggestion.target)] = (suggestion.source, suggestion.target)
        self._persist()
        return suggestion

    def reject(self, suggestion_id: int) -> Optional[VoiceAliasSuggestion]:
        suggestion = self._pending.pop(suggestion_id, None)
        if suggestion is None:
            return None
        self._ignored[_pair_key(suggestion.source, suggestion.target)] = time.time()
        self._persist()
        return suggestion

    def add_manual(self, source: str, target: str) -> Tuple[str, str]:
        source_value = " ".join((source or "").strip().split())
        target_value = " ".join((target or "").strip().split())
        if not source_value or not target_value:
            raise ValueError("source and target must be non-empty")
        self._approved[_pair_key(source_value, target_value)] = (source_value, target_value)
        self._persist()
        return source_value, target_value

    def observe_pair(self, *, source: str, target: str) -> List[VoiceAliasSuggestion]:
        source_value = " ".join((source or "").strip().split())
        target_value = " ".join((target or "").strip().split())
        if not source_value or not target_value:
            return []
        if len(source_value.split()) > self.max_phrase_words:
            return []
        if len(target_value.split()) > self.max_phrase_words:
            return []
        if _normalize_phrase(source_value) == _normalize_phrase(target_value):
            return []

        key = _pair_key(source_value, target_value)
        if key in self._approved:
            return []
        if key in self._ignored:
            return []

        count = self._counts.get(key, 0) + 1
        self._counts[key] = count
        now = time.time()
        created: List[VoiceAliasSuggestion] = []

        existing_pending = next(
            (item for item in self._pending.values() if _pair_key(item.source, item.target) == key),
            None,
        )
        if existing_pending is not None:
            existing_pending.count = count
            existing_pending.last_seen_at = now
            self._persist()
            return []

        if count >= self.min_examples:
            suggestion = VoiceAliasSuggestion(
                suggestion_id=self._next_id,
                source=source_value,
                target=target_value,
                count=count,
                created_at=now,
                last_seen_at=now,
            )
            self._next_id += 1
            self._pending[suggestion.suggestion_id] = suggestion
            created.append(suggestion)

        self._persist()
        return created
