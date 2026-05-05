import hashlib
import json
import re
import time
from pathlib import Path
from typing import Optional


def _session_mode(config) -> str:
    return str(getattr(config, "pi_session_mode", "none") or "none").strip().lower()


def _session_base_dir(config) -> Path:
    configured_dir = str(getattr(config, "pi_session_dir", "") or "").strip()
    if configured_dir:
        return Path(configured_dir).expanduser()
    return Path.home() / ".pi" / "agent" / "telegram-sessions"


def _provider_scoped_session_key(config, session_key: str) -> str:
    provider = str(getattr(config, "pi_provider", "ollama") or "ollama").strip().lower() or "ollama"
    model = str(getattr(config, "pi_model", "qwen3-coder:30b") or "qwen3-coder:30b").strip() or "qwen3-coder:30b"
    return f"{session_key}|provider:{provider}|model:{model}"


def _safe_session_filename(session_key: str) -> str:
    digest = hashlib.sha256(session_key.encode("utf-8")).hexdigest()[:12]
    label = re.sub(r"[^A-Za-z0-9._-]+", "_", session_key).strip("._-")
    if not label:
        label = "telegram_scope"
    return f"{label[:80]}-{digest}.jsonl"


def _resolve_session_path(config, session_key: str) -> Path:
    base_dir = _session_base_dir(config)
    scoped_session_key = _provider_scoped_session_key(config, session_key)
    return base_dir / _safe_session_filename(scoped_session_key)


def _session_archive_dir(config, base_dir: Path) -> Path:
    configured_dir = str(getattr(config, "pi_session_archive_dir", "") or "").strip()
    if configured_dir:
        return Path(configured_dir).expanduser()
    return base_dir / ".archive"


def _cleanup_session_archive_dir(archive_dir: Path, retention_seconds: int) -> None:
    if retention_seconds <= 0 or not archive_dir.exists():
        return
    cutoff = time.time() - retention_seconds
    for archive_path in archive_dir.glob("*.rotated.*.jsonl"):
        try:
            stat = archive_path.stat()
        except OSError:
            continue
        if stat.st_mtime < cutoff:
            try:
                archive_path.unlink()
            except OSError:
                continue


def _rotate_session_file_if_needed(config, base_dir: Path, session_path: Path) -> None:
    max_bytes = int(getattr(config, "pi_session_max_bytes", 0) or 0)
    max_age_seconds = int(getattr(config, "pi_session_max_age_seconds", 0) or 0)
    retention_seconds = int(getattr(config, "pi_session_archive_retention_seconds", 0) or 0)
    archive_dir = _session_archive_dir(config, base_dir)
    if not session_path.exists():
        _cleanup_session_archive_dir(archive_dir, retention_seconds)
        return
    try:
        stat = session_path.stat()
    except OSError:
        return
    should_rotate = False
    if max_bytes > 0 and stat.st_size >= max_bytes:
        should_rotate = True
    if max_age_seconds > 0 and (time.time() - stat.st_mtime) >= max_age_seconds:
        should_rotate = True
    if should_rotate:
        archive_dir.mkdir(parents=True, exist_ok=True)
        timestamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        archive_path = archive_dir / f"{session_path.stem}.rotated.{timestamp}{session_path.suffix}"
        try:
            session_path.replace(archive_path)
        except OSError:
            pass
    _cleanup_session_archive_dir(archive_dir, retention_seconds)


def build_session_args(config, session_key: Optional[str]) -> list[str]:
    mode = _session_mode(config)
    if mode in {"", "none", "off", "disabled", "no_session"}:
        return ["--no-session"]
    if mode not in {"telegram_scope", "scope", "session_key"}:
        raise RuntimeError(f"Unsupported Pi session mode: {mode}")
    if not session_key:
        return ["--no-session"]
    base_dir = _session_base_dir(config)
    session_path = _resolve_session_path(config, session_key)
    _rotate_session_file_if_needed(config, base_dir, session_path)
    return ["--session-dir", str(base_dir), "--session", str(session_path)]


def clear_scope_session_files(config, scope_key: str) -> int:
    mode = _session_mode(config)
    if mode in {"", "none", "off", "disabled", "no_session"}:
        return 0
    base_dir = _session_base_dir(config)
    if not base_dir.is_dir():
        return 0
    scope_label = re.sub(r"[^A-Za-z0-9._-]+", "_", scope_key).strip("._-")
    if not scope_label:
        return 0
    archive_dir = base_dir / ".archive"
    timestamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    archived = 0
    for file_path in list(base_dir.glob(f"{scope_label}*.jsonl")):
        if file_path.parent == archive_dir:
            continue
        archive_dir.mkdir(parents=True, exist_ok=True)
        archive_path = archive_dir / f"{file_path.stem}.reset.{timestamp}{file_path.suffix}"
        try:
            file_path.rename(archive_path)
            archived += 1
        except OSError:
            pass
    return archived


def sanitize_session_images(config, session_key: str) -> None:
    try:
        session_path = _resolve_session_path(config, session_key)
    except Exception:
        return
    if not session_path.is_file():
        return
    try:
        lines = session_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    sanitized_lines: list[str] = []
    changed = False
    for line in lines:
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            sanitized_lines.append(line)
            continue
        if entry.get("type") != "message":
            sanitized_lines.append(line)
            continue
        message = entry.get("message")
        if not isinstance(message, dict):
            sanitized_lines.append(line)
            continue
        if message.get("role") != "user":
            sanitized_lines.append(line)
            continue
        content = message.get("content")
        if not isinstance(content, list):
            sanitized_lines.append(line)
            continue
        filtered = [block for block in content if block.get("type") != "image"]
        if len(filtered) == len(content):
            sanitized_lines.append(line)
            continue
        if not filtered:
            changed = True
            continue
        entry["message"]["content"] = filtered
        sanitized_lines.append(json.dumps(entry, ensure_ascii=False))
        changed = True
    if not changed:
        return
    try:
        raw = "\n".join(sanitized_lines) + ("\n" if sanitized_lines else "")
        session_path.write_text(raw, encoding="utf-8")
    except OSError:
        pass
