from __future__ import annotations

import re
from datetime import UTC, datetime

from .models import FeedbackProfile, RankedVideo, VideoCandidate


CLICKBAIT_RE = re.compile(r"\b(shocking|must watch|you won't believe|destroyed|exposed|insane|secret they don't want)\b", re.I)
MAX_VIDEO_FEEDBACK_BOOST = 18.0
MAX_CHANNEL_FEEDBACK_BOOST = 10.0


def rank_candidates(
    candidates: list[VideoCandidate],
    *,
    topic: str,
    feedback_profile: FeedbackProfile | None = None,
    now: datetime | None = None,
) -> list[RankedVideo]:
    topic_terms = [term.lower() for term in re.findall(r"[A-Za-z0-9]+", topic) if len(term) > 2]
    topic_phrase = " ".join(topic_terms)
    feedback_profile = feedback_profile or FeedbackProfile()
    now = now or datetime.now(UTC)
    ranked: list[RankedVideo] = []
    for candidate in candidates:
        haystack = f"{candidate.title} {candidate.channel} {candidate.metadata_text}".lower()
        score = 50.0
        reasons: list[str] = []
        matches = sum(1 for term in topic_terms if term in haystack)
        if matches:
            score += min(25.0, matches * 8.0)
            reasons.append("topic match")
        if topic_phrase and topic_phrase in haystack:
            score += 6.0
            reasons.append("exact phrase")
        if CLICKBAIT_RE.search(candidate.title):
            score -= 20.0
            reasons.append("clickbait risk")
        freshness_score = _freshness_boost(candidate.published_at, now=now)
        if freshness_score:
            score += freshness_score
            reasons.append("fresh")
        elif candidate.published_at:
            reasons.append("dated")
        video_feedback = feedback_profile.video_scores.get(candidate.video_id, 0.0)
        if video_feedback:
            score += max(-MAX_VIDEO_FEEDBACK_BOOST, min(MAX_VIDEO_FEEDBACK_BOOST, video_feedback * 6.0))
            reasons.append("feedback")
        channel_key = candidate.channel or "__unknown__"
        channel_feedback = feedback_profile.channel_scores.get(channel_key, 0.0)
        if channel_feedback:
            score += max(-MAX_CHANNEL_FEEDBACK_BOOST, min(MAX_CHANNEL_FEEDBACK_BOOST, channel_feedback * 3.0))
            reasons.append("channel trend")
        if len(candidate.title) > 12:
            score += 5.0
            reasons.append("specific title")
        if not reasons:
            reasons.append("visible search candidate")
        ranked.append(RankedVideo(candidate=candidate, score=score, reasons=tuple(reasons)))
    return sorted(ranked, key=lambda item: (-item.score, item.candidate.title.lower()))


def feedback_weight_for_signal(signal: str) -> float:
    normalized = signal.strip().lower().replace("-", "_")
    weights = {
        "more_like_this": 1.0,
        "save": 1.5,
        "less_like_this": -1.0,
        "too_clickbait": -1.5,
    }
    if normalized not in weights:
        raise ValueError(f"Unsupported feedback signal: {signal}")
    return weights[normalized]


def _freshness_boost(value: str, *, now: datetime) -> float:
    published = _parse_published_at(value)
    if published is None:
        return 0.0
    age_hours = max(0.0, (now - published).total_seconds() / 3600.0)
    if age_hours <= 24:
        return 10.0
    if age_hours <= 72:
        return 6.0
    if age_hours <= 24 * 7:
        return 3.0
    if age_hours <= 24 * 30:
        return 1.0
    return -2.0


def _parse_published_at(value: str) -> datetime | None:
    cleaned = value.strip()
    if not cleaned:
        return None
    if len(cleaned) == 10:
        try:
            return datetime.fromisoformat(cleaned).replace(tzinfo=UTC)
        except ValueError:
            return None
    try:
        parsed = datetime.fromisoformat(cleaned)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)
