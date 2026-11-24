"""Framework-free adapter contracts.

Adapters return normalized data and never call one another's private APIs. The
workflow owns orchestration, cancellation and persistence.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from app.domain.models import Chunk, ContentItem, Transcript


@dataclass(frozen=True, slots=True)
class ImportRequest:
    value: str
    kind: str = "auto"
    hint_platform: str | None = None
    idempotency_key: str | None = None


@dataclass(frozen=True, slots=True)
class AuthContext:
    """Short-lived authorization reference; never serialize its secrets."""

    provider: str
    session_ref: str | None = None
    user_authorized: bool = False


@dataclass(frozen=True, slots=True)
class SourceMetadata:
    title: str
    canonical_url: str | None
    platform: str
    author: str | None = None
    published_at: str | None = None
    duration_seconds: float | None = None
    available_subtitles: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AcquiredSource:
    metadata: SourceMetadata
    content: ContentItem
    subtitle_path: Path | None = None
    media_path: Path | None = None
    text_path: Path | None = None
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ProgressEvent:
    stage: str
    progress: int
    message: str


class ProgressSink(Protocol):
    async def emit(self, event: ProgressEvent) -> None: ...


class AssetSink(Protocol):
    async def allocate(self, *, suffix: str) -> Path: ...


class SourceAdapter(Protocol):
    """Handle one source item; platform details stop at this boundary."""

    def can_handle(self, request: ImportRequest) -> bool: ...

    async def probe(self, request: ImportRequest, auth: AuthContext) -> SourceMetadata: ...

    async def acquire(
        self,
        request: ImportRequest,
        auth: AuthContext,
        assets: AssetSink,
        progress: ProgressSink,
    ) -> AcquiredSource: ...


class SourceEnumerator(Protocol):
    """Expand a collection/channel/favorites source into child requests only."""

    def can_handle(self, request: ImportRequest) -> bool: ...

    async def enumerate(
        self,
        request: ImportRequest,
        auth: AuthContext,
        progress: ProgressSink,
    ) -> AsyncIterator[ImportRequest]: ...


class TranscriptionProvider(Protocol):
    name: str

    async def transcribe(
        self,
        media_path: Path,
        *,
        language: str | None,
        progress: ProgressSink,
    ) -> Transcript: ...


class AIProvider(Protocol):
    name: str

    async def summarize_chunks(
        self,
        chunks: tuple[Chunk, ...],
        *,
        instructions: str,
        settings: dict[str, Any],
        progress: ProgressSink,
    ) -> dict[str, Any]: ...


class Exporter(Protocol):
    name: str
    output_type: str

    async def export(self, artifact_path: Path, output_dir: Path) -> Path: ...


class SearchProvider(Protocol):
    name: str

    def index(self, *, content_id: str, title: str, body: str, tags: tuple[str, ...]) -> None: ...

    def search(self, query: str, *, limit: int = 20) -> list[dict[str, Any]]: ...
