"""Split a transcript into small, traceable pieces for summarization."""

from __future__ import annotations

import hashlib
import re

from app.domain.models import Chunk, Transcript, TranscriptSegment


def chunk_transcript(transcript: Transcript, *, max_tokens: int) -> tuple[Chunk, ...]:
    if max_tokens < 1:
        raise ValueError("max_tokens 必须大于 0")

    chunks: list[Chunk] = []
    pending: list[TranscriptSegment] = []
    pending_tokens = 0

    def flush() -> None:
        nonlocal pending, pending_tokens
        if not pending:
            return
        text = "\n".join(segment.text for segment in pending)
        chunks.append(_make_chunk(len(chunks) + 1, pending[0].start_seconds, pending[-1].end_seconds, text))
        pending = []
        pending_tokens = 0

    for segment in transcript.segments:
        segment_tokens = estimate_tokens(segment.text)
        if segment_tokens > max_tokens:
            flush()
            chunks.extend(_split_long_segment(segment, max_tokens, len(chunks) + 1))
            continue
        if pending and pending_tokens + segment_tokens > max_tokens:
            flush()
        pending.append(segment)
        pending_tokens += segment_tokens

    flush()
    return tuple(chunks)


def estimate_tokens(text: str) -> int:
    """A lightweight estimate that works reasonably for Chinese and English text."""

    return max(1, len(re.findall(r"[\u4e00-\u9fff]|[A-Za-z0-9_]+|[^\s]", text)))


def _split_long_segment(segment: TranscriptSegment, max_tokens: int, first_ordinal: int) -> list[Chunk]:
    sentences = [part.strip() for part in re.split(r"(?<=[。！？.!?])\s*", segment.text) if part.strip()]
    pieces: list[str] = []
    current = ""
    for sentence in sentences or [segment.text]:
        candidate = f"{current} {sentence}".strip()
        if current and estimate_tokens(candidate) > max_tokens:
            pieces.append(current)
            current = ""
        if estimate_tokens(sentence) > max_tokens:
            pieces.extend(_split_to_budget(sentence, max_tokens))
        elif current:
            current = f"{current} {sentence}".strip()
        else:
            current = sentence
    if current:
        pieces.append(current)

    result: list[Chunk] = []
    for index, piece in enumerate(pieces):
        start = segment.start_seconds + (segment.end_seconds - segment.start_seconds) * index / len(pieces)
        end = segment.start_seconds + (segment.end_seconds - segment.start_seconds) * (index + 1) / len(pieces)
        result.append(_make_chunk(first_ordinal + index, start, end, piece))
    return result


def _split_to_budget(text: str, max_tokens: int) -> list[str]:
    pieces: list[str] = []
    current = ""
    for character in text:
        candidate = current + character
        if current and estimate_tokens(candidate) > max_tokens:
            pieces.append(current)
            current = character
        else:
            current = candidate
    if current:
        pieces.append(current)
    return pieces


def _make_chunk(ordinal: int, start_seconds: float, end_seconds: float, text: str) -> Chunk:
    normalized = text.strip()
    return Chunk(
        ordinal=ordinal,
        start_seconds=start_seconds,
        end_seconds=end_seconds,
        text=normalized,
        text_hash=hashlib.sha256(normalized.encode("utf-8")).hexdigest(),
        token_count=estimate_tokens(normalized),
    )
