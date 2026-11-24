"""Map archived transcript segments to only the positions their source proves."""

from __future__ import annotations

import math
from dataclasses import dataclass

from app.knowledge.transcript import transcript_position_kind


@dataclass(frozen=True, slots=True)
class TranscriptSourceSpan:
    ordinal: int
    source_kind: str
    location_kind: str
    source_ref: str
    start_seconds: float | None
    end_seconds: float | None
    text: str


def map_transcript_segments(payload: object) -> tuple[TranscriptSourceSpan, ...]:
    """Use source timestamps only when the archive identifies a timed source."""

    if not isinstance(payload, dict):
        return ()
    raw_segments = payload.get("segments")
    if not isinstance(raw_segments, list):
        return ()
    source_kind = str(payload.get("source_kind") or "unknown")
    position_kind = transcript_position_kind(
        source_kind,
        payload.get("engine"),
        raw_segments,
        explicit=payload.get("position_kind"),
    )
    spans: list[TranscriptSourceSpan] = []
    for ordinal, item in enumerate(raw_segments, start=1):
        if not isinstance(item, dict):
            continue
        source_text = str(item.get("text") or "").strip()
        if not source_text:
            continue
        start = _finite_seconds(item.get("start_seconds"))
        end = _finite_seconds(item.get("end_seconds"))
        if (
            position_kind != "timestamp"
            or start is None
            or end is None
            or start < 0
            or end < start
        ):
            location_kind = "detail_only"
            start = end = None
        else:
            location_kind = "timestamp"
        spans.append(
            TranscriptSourceSpan(
                ordinal=ordinal,
                source_kind=source_kind,
                location_kind=location_kind,
                source_ref=f"transcript:segment:{ordinal}",
                start_seconds=start,
                end_seconds=end,
                text=source_text,
            )
        )
    return tuple(spans)


def _finite_seconds(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return None
    return seconds if math.isfinite(seconds) else None
