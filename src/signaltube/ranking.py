from __future__ import annotations

import re

from .models import RankedVideo, VideoCandidate


CLICKBAIT_RE = re.compile(r"\b(shocking|must watch|you won't believe|destroyed|exposed|insane|secret they don't want)\b", re.I)


def rank_candidates(candidates: list[VideoCandidate], *, topic: str) -> list[RankedVideo]:
    topic_terms = [term.lower() for term in re.findall(r"[A-Za-z0-9]+", topic) if len(term) > 2]
    ranked: list[RankedVideo] = []
    for candidate in candidates:
        haystack = f"{candidate.title} {candidate.channel} {candidate.metadata_text}".lower()
        score = 50.0
        reasons: list[str] = []
        matches = sum(1 for term in topic_terms if term in haystack)
        if matches:
            score += min(25.0, matches * 8.0)
            reasons.append("topic match")
        if CLICKBAIT_RE.search(candidate.title):
            score -= 20.0
            reasons.append("clickbait risk")
        if len(candidate.title) > 12:
            score += 5.0
            reasons.append("specific title")
        if not reasons:
            reasons.append("visible search candidate")
        ranked.append(RankedVideo(candidate=candidate, score=score, reasons=tuple(reasons)))
    return sorted(ranked, key=lambda item: (-item.score, item.candidate.title.lower()))
