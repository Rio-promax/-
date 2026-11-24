"""Convert pasted text and common subtitle files into the shared Transcript format."""

from __future__ import annotations

import re

from app.domain.models import Transcript, TranscriptSegment

_TIMED_SOURCE_KINDS = frozenset({"subtitle", "bilibili_subtitle", "asr"})


def transcript_from_text(
    text: str,
    *,
    language: str | None = None,
    source_kind: str = "text",
) -> Transcript:
    """Use paragraphs as segments when the source has no real timestamps."""

    blocks = [
        _clean_text(block)
        for block in re.split(r"\n\s*\n", text.strip())
        if _clean_text(block)
    ]
    if not blocks:
        raise ValueError("内容不能为空")

    cursor = 0.0
    segments: list[TranscriptSegment] = []
    for block in blocks:
        # This is only a readable position estimate, not a media timestamp.
        duration = max(1.0, len(block) / 14)
        segments.append(TranscriptSegment(cursor, cursor + duration, block))
        cursor += duration

    return Transcript(language, source_kind, None, tuple(segments), position_kind="detail_only",
                      source_coverage_complete=True)


def transcript_from_subtitle(
    text: str,
    *,
    language: str | None = None,
    source_kind: str = "subtitle",
) -> Transcript:
    """Read the timestamp blocks shared by SRT and WebVTT files."""

    lines = text.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    segments: list[TranscriptSegment] = []
    index = 0
    while index < len(lines):
        line = lines[index].strip()
        if "-->" not in line:
            index += 1
            continue

        start_text, end_text = (part.strip().split(" ", 1)[0] for part in line.split("-->", 1))
        try:
            start_seconds = _timestamp_seconds(start_text)
            end_seconds = _timestamp_seconds(end_text)
        except ValueError:
            index += 1
            continue

        index += 1
        content_lines: list[str] = []
        while index < len(lines) and lines[index].strip():
            content_lines.append(lines[index])
            index += 1
        content = _clean_text(" ".join(content_lines))
        if content and end_seconds >= start_seconds:
            segments.append(TranscriptSegment(start_seconds, end_seconds, content))
        index += 1

    if not segments:
        raise ValueError("字幕文件中没有可用的时间戳文本")
    return Transcript(language, source_kind, "subtitle", tuple(segments))


def transcript_to_dict(transcript: Transcript) -> dict[str, object]:
    result = {
        "version": transcript.version,
        "language": transcript.language,
        "source_kind": transcript.source_kind,
        "engine": transcript.engine,
        "position_kind": transcript.position_kind,
        "segments": [
            {
                "start_seconds": segment.start_seconds,
                "end_seconds": segment.end_seconds,
                "text": segment.text,
                "speaker": segment.speaker,
            }
            for segment in transcript.segments
        ],
    }
    if transcript.source_coverage_complete is not None:
        result["source_coverage_complete"] = transcript.source_coverage_complete
    return result


def transcript_from_dict(value: object) -> Transcript:
    if not isinstance(value, dict):
        raise ValueError("转写阶段性产物格式无效")
    raw_segments = value.get("segments")
    if not isinstance(raw_segments, list):
        raise ValueError("转写阶段性产物缺少片段")
    segments = tuple(
        TranscriptSegment(
            float(item["start_seconds"]),
            float(item["end_seconds"]),
            str(item["text"]),
            str(item["speaker"]) if item.get("speaker") else None,
        )
        for item in raw_segments
        if isinstance(item, dict)
    )
    if not segments:
        raise ValueError("转写阶段性产物没有片段")
    source_kind = str(value.get("source_kind") or "text")
    engine = value.get("engine")
    return Transcript(
        value.get("language"),
        source_kind,
        engine,
        segments,
        str(value.get("version") or "transcript-v1"),
        _position_kind(value, source_kind, engine, segments),
        value.get("source_coverage_complete") if isinstance(value.get("source_coverage_complete"), bool) else None,
    )


def _position_kind(value, source_kind, engine, segments) -> str:
    return transcript_position_kind(
        source_kind,
        engine,
        segments,
        explicit=value.get("position_kind"),
    )


def transcript_position_kind(source_kind, engine, segments, *, explicit=None) -> str:
    """Return timestamp only for known timed sources with valid provenance."""

    normalized_source = str(source_kind).casefold()
    if normalized_source in {"text", "public_page_text"} or normalized_source.endswith("_text"):
        return "detail_only"
    if normalized_source not in _TIMED_SOURCE_KINDS:
        return "detail_only"
    if explicit in {"timestamp", "detail_only"}:
        return explicit
    if (
        normalized_source == "asr"
        and engine == "openai-compatible"
        and len(segments) == 1
        and _segment_value(segments[0], "start_seconds") == 0.0
        and _segment_value(segments[0], "end_seconds") == 1.0
    ):
        # Older OpenAI-compatible plain-text responses were represented as a
        # 0–1 second segment even though the provider supplied no timestamps.
        return "detail_only"
    return "timestamp"


def _segment_value(segment, key):
    if isinstance(segment, dict):
        return segment.get(key)
    return getattr(segment, key, None)


def _clean_text(value: str) -> str:
    without_tags = re.sub(r"<[^>]+>", "", value)
    return re.sub(r"\s+", " ", without_tags).strip()


def _timestamp_seconds(value: str) -> float:
    normalized = value.replace(",", ".")
    parts = normalized.split(":")
    if len(parts) == 3:
        hours, minutes, seconds = parts
    elif len(parts) == 2:
        hours, minutes, seconds = "0", *parts
    else:
        raise ValueError("invalid subtitle timestamp")
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
