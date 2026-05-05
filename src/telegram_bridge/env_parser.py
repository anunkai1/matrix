"""Typed environment-variable parsing utilities.

Centralizes the common pattern of reading an env var, parsing it,
validating it, and falling back to a sensible default.
"""

from __future__ import annotations

import os
from typing import List, Optional, Set, Tuple


class Env:
    """Fluent builder for reading a single environment variable with typed parsing.

    Usage::

        timeout = Env("TIMEOUT").as_int(default=30, min=1)
        enabled = Env("FEATURE_ENABLED").as_bool(default=False)
        items   = Env("ITEMS").as_list(default=["a", "b"])
    """

    __slots__ = ("_name",)

    def __init__(self, name: str) -> None:
        self._name = name

    # -- typed accessors ----------------------------------------------------

    def as_int(self, default: int, *, min: int = 1) -> int:
        raw = os.getenv(self._name)
        if raw is None:
            return default
        try:
            parsed = int(raw)
        except ValueError as exc:
            raise ValueError(f"{self._name} must be an integer") from exc
        if parsed < min:
            raise ValueError(f"{self._name} must be >= {min}")
        return parsed

    def as_bool(self, default: bool) -> bool:
        raw = os.getenv(self._name)
        if raw is None:
            return default
        v = raw.strip().lower()
        if v in ("1", "true", "yes", "on"):
            return True
        if v in ("0", "false", "no", "off"):
            return False
        raise ValueError(f"{self._name} must be a boolean value")

    def as_float(
        self,
        default: float,
        *,
        min: Optional[float] = None,
        max: Optional[float] = None,
    ) -> float:
        raw = os.getenv(self._name)
        if raw is None:
            return default
        try:
            parsed = float(raw)
        except ValueError as exc:
            raise ValueError(f"{self._name} must be a float") from exc
        if min is not None and parsed < min:
            raise ValueError(f"{self._name} must be >= {min}")
        if max is not None and parsed > max:
            raise ValueError(f"{self._name} must be <= {max}")
        return parsed

    def as_str(self, default: str) -> str:
        """Return the env value (stripped) or *default* if unset/blank."""
        raw = os.getenv(self._name)
        if raw is None:
            return default
        stripped = raw.strip()
        return stripped if stripped else default

    def as_list(self, default: List[str], *, sep: str = ",", dedupe: bool = True) -> List[str]:
        """Parse a comma-separated list, removing blanks and duplicates."""
        raw = os.getenv(self._name)
        if raw is None or not raw.strip():
            return list(default)
        values = [v.strip() for v in raw.split(sep) if v.strip()]
        if not dedupe:
            return values or list(default)
        seen: Set[str] = set()
        out: List[str] = []
        for v in values:
            if v in seen:
                continue
            seen.add(v)
            out.append(v)
        return out or list(default)

    def as_lower_list(self, default: List[str], *, sep: str = ",") -> List[str]:
        """Like as_list but normalizes each entry to lowercase."""
        raw = os.getenv(self._name)
        if raw is None or not raw.strip():
            return list(default)
        seen: Set[str] = set()
        out: List[str] = []
        for v in (s.strip() for s in raw.split(sep) if s.strip()):
            key = v.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(key)
        return out or list(default)

    def as_prefix_list(self) -> List[str]:
        """Parse a deduplicated prefix list (casefold for dedup, preserve case)."""
        raw = os.getenv(self._name, "").strip()
        if not raw:
            return []
        seen: Set[str] = set()
        out: List[str] = []
        for v in (s.strip() for s in raw.split(",") if s.strip()):
            key = v.casefold()
            if key in seen:
                continue
            seen.add(key)
            out.append(v)
        return out

    def as_voice_alias_replacements(self) -> List[Tuple[str, str]]:
        """Parse 'source=>target' pairs separated by ';'."""
        raw = os.getenv(self._name, "").strip()
        if not raw:
            return []
        out: List[Tuple[str, str]] = []
        for entry in (s.strip() for s in raw.split(";") if s.strip()):
            if "=>" not in entry:
                raise ValueError(
                    f"{self._name} entry must use 'source=>target' format: {entry!r}"
                )
            source, target = entry.split("=>", 1)
            source = source.strip()
            target = target.strip()
            if not source or not target:
                raise ValueError(
                    f"{self._name} entry must include non-empty source and target: {entry!r}"
                )
            out.append((source, target))
        return out

    def as_allowed_chat_ids(self) -> Set[int]:
        """Parse comma-separated Telegram chat IDs."""
        raw = os.getenv(self._name, "").strip()
        if not raw:
            raise ValueError(f"{self._name} is empty")
        values = [v.strip() for v in raw.split(",") if v.strip()]
        if not values:
            raise ValueError(f"{self._name} is empty")
        parsed: Set[int] = set()
        for v in values:
            try:
                parsed.add(int(v))
            except ValueError as exc:
                raise ValueError(
                    f"Invalid {self._name} value: {v!r}"
                ) from exc
        return parsed


def _voice_alias_defaults() -> List[Tuple[str, str]]:
    return [
        ("master broom", "master bedroom"),
        ("master room", "master bedroom"),
        ("air con", "aircon"),
        ("air conditioner", "aircon"),
        ("clode code", "claude code"),
        ("hall way", "hallway"),
    ]


def build_voice_alias_replacements() -> List[Tuple[str, str]]:
    """Merge built-in defaults with env overrides."""
    merged: Dict[str, Tuple[str, str]] = {}
    for source, target in _voice_alias_defaults():
        merged[source.casefold()] = (source, target)
    custom = Env("TELEGRAM_VOICE_ALIAS_REPLACEMENTS").as_voice_alias_replacements()
    for source, target in custom:
        merged[source.casefold()] = (source, target)
    return list(merged.values())
