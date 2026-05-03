import re
import sqlite3
import time
from typing import List, Optional, Sequence, Tuple

URL_PATTERN = re.compile(r"https?://\S+")
MARKDOWN_LINK_PATTERN = re.compile(r"\[([^\]]+)\]\([^)]+\)")


def clean_summary_line(text: str, limit: int = 180) -> str:
    value = (text or "").strip()
    if not value:
        return ""
    value = MARKDOWN_LINK_PATTERN.sub(r"\1", value)
    value = URL_PATTERN.sub("", value)
    value = value.replace("`", "")
    value = " ".join(value.split()).strip(" -")
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 3)].rstrip() + "..."


def is_summary_noise(text: str) -> bool:
    lowered = (text or "").lower()
    if not lowered:
        return True
    if lowered.startswith(("chunk id:", "traceback ", "to https://")):
        return True
    if lowered in {"proceed", "go ahead", "yes"}:
        return True
    if "/home/" in lowered and len(lowered) > 120:
        return True
    return False


def append_unique(items: List[str], value: str, max_items: int) -> None:
    if not value:
        return
    candidate = value.strip()
    if not candidate:
        return
    normalized = candidate.lower()
    if any(existing.lower() == normalized for existing in items):
        return
    if len(items) >= max_items:
        return
    items.append(candidate)


def format_summary_section(title: str, items: Sequence[str], empty_text: str) -> str:
    lines = [f"{title}:"]
    if items:
        lines.extend([f"- {item}" for item in items])
    else:
        lines.append(f"- {empty_text}")
    return "\n".join(lines)


def summary_title(base: str, row: Optional[sqlite3.Row]) -> str:
    if row is None:
        return base
    created_at = row["created_at"]
    if isinstance(created_at, (int, float)) and created_at > 0:
        return f"{base}: {summary_age(float(created_at))}"
    return base


def summary_age(created_at: float) -> str:
    seconds = time.time() - created_at
    if seconds < 120:
        return "just now"
    minutes = int(seconds // 60)
    if minutes < 60:
        return f"{minutes} min ago"
    hours = int(seconds // 3600)
    if hours < 24:
        return f"{hours}h ago"
    days = int(seconds // 86400)
    return f"{days}d ago"


def build_summary_sections(
    current_summary_row: Optional[sqlite3.Row],
    background_summary_row: Optional[sqlite3.Row],
) -> List[Tuple[str, str]]:
    current_summary = str(current_summary_row["summary_text"] or "").strip() if current_summary_row else ""
    background_summary = (
        str(background_summary_row["summary_text"] or "").strip() if background_summary_row else ""
    )
    if not background_summary:
        return [(summary_title("Conversation Summary", current_summary_row), current_summary)] if current_summary else []
    if not current_summary:
        return [(summary_title("Conversation Summary", background_summary_row), background_summary)]
    return [(summary_title("Conversation Summary", current_summary_row), current_summary)]


def summarize_rows(rows: Sequence[sqlite3.Row]) -> Tuple[str, List[str], List[str]]:
    parsed_rows: List[Tuple[str, str]] = []
    for row in rows:
        cleaned = clean_summary_line(str(row["text"] or ""))
        if not cleaned or is_summary_noise(cleaned):
            continue
        role = str(row["sender_role"] or "user").strip().lower() or "user"
        parsed_rows.append((role, cleaned))

    objective: List[str] = []
    decisions: List[str] = []
    current_state: List[str] = []
    open_items: List[str] = []
    preferences: List[str] = []
    risks: List[str] = []
    question_candidates: List[str] = []

    objective_terms = (
        "i want",
        "we need",
        "please",
        "can you",
        "could you",
        "goal",
        "objective",
    )
    decision_terms = (
        "proceed with these changes",
        "accepted risk",
        "as designed",
        "change it to",
        "rename",
        "remove it",
    )
    preference_terms = (
        "i prefer",
        "we prefer",
        "don't want",
        "do not want",
        "leave as is",
        "as designed",
    )
    state_terms = (
        "done",
        "completed",
        "implemented",
        "fixed",
        "pushed",
        "restarted",
        "active",
        "running",
        "updated",
        "removed",
        "renamed",
        "added",
    )
    risk_terms = ("blocked", "error", "failed", "denied", "risk", "warning", "not found")
    open_terms = ("pending", "need approval", "waiting", "follow-up", "next step", "todo")

    for role, text in parsed_rows:
        lowered = text.lower()
        if role == "assistant":
            if any(term in lowered for term in state_terms):
                append_unique(current_state, text, 3)
            if any(term in lowered for term in risk_terms):
                append_unique(risks, text, 3)
            if any(term in lowered for term in open_terms):
                append_unique(open_items, text, 3)
            if any(term in lowered for term in decision_terms):
                append_unique(decisions, text, 3)
        else:
            if any(term in lowered for term in objective_terms):
                append_unique(objective, text, 2)
            if any(term in lowered for term in decision_terms):
                append_unique(decisions, text, 3)
            if any(term in lowered for term in preference_terms):
                append_unique(preferences, text, 3)
            if "?" in text:
                append_unique(question_candidates, text, 4)
            if any(term in lowered for term in risk_terms):
                append_unique(risks, text, 3)

    if not objective:
        for role, text in parsed_rows:
            if role != "assistant":
                append_unique(objective, text, 1)
                break

    if not current_state:
        for role, text in reversed(parsed_rows):
            if role == "assistant":
                append_unique(current_state, text, 1)
                break

    if not open_items:
        for candidate in question_candidates[-2:]:
            lowered = candidate.lower()
            if "anything else" in lowered or "what next" in lowered or "next step" in lowered:
                append_unique(open_items, candidate, 2)

    summary_sections = [
        format_summary_section("Objective", objective, "No explicit objective captured."),
        format_summary_section("Decisions Made", decisions, "No explicit decision captured."),
        format_summary_section("Current State", current_state, "No clear status update captured."),
        format_summary_section("Open Items", open_items, "No open item detected."),
        format_summary_section("User Preferences", preferences, "No durable preference detected."),
        format_summary_section("Risks/Blockers", risks, "No blocker detected."),
    ]
    summary_text = "\n\n".join(summary_sections)

    key_points_source = objective + decisions + current_state + preferences + risks
    key_points: List[str] = []
    for point in key_points_source:
        append_unique(key_points, point, 8)

    open_loops: List[str] = []
    for item in open_items:
        append_unique(open_loops, item, 6)
    return summary_text, key_points, open_loops
