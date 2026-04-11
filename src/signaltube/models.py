from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class VideoCandidate:
    video_id: str
    url: str
    title: str
    channel: str = ""
    metadata_text: str = ""
    published_at: str = ""
    duration_text: str = ""
    source_topic: str = ""
    source: str = "browser_lab"

    @property
    def thumbnail_url(self) -> str:
        return f"https://i.ytimg.com/vi/{self.video_id}/hqdefault.jpg"

    @property
    def embed_url(self) -> str:
        return f"https://www.youtube.com/embed/{self.video_id}"


@dataclass(frozen=True)
class RankedVideo:
    candidate: VideoCandidate
    score: float
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class TopicConfig:
    topic: str
    enabled: bool = True
    max_candidates: int = 40
    sort_order: int = 100
    last_collected_at: str = ""


@dataclass(frozen=True)
class FeedbackProfile:
    video_scores: dict[str, float] = field(default_factory=dict)
    channel_scores: dict[str, float] = field(default_factory=dict)
