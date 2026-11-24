"""Normalized source material accepted by the analysis workflow."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.domain.models import ContentKind, SourcePlatform, Transcript


@dataclass(frozen=True, slots=True)
class PreparedSource:
    kind: ContentKind
    title: str
    transcript: Transcript | None
    content_hash: str
    source_path: str | None
    source_url: str | None
    acquisition_method: str
    platform: SourcePlatform = SourcePlatform.LOCAL
    author: str | None = None
    published_at: datetime | None = None
    duration_seconds: float | None = None
    thumbnail_url: str | None = None
    source_note: str | None = None
    audio_path: str | None = None
    audio_is_temp: bool = False
    download_seconds: float | None = None
