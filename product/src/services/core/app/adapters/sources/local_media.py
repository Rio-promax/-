"""Inspect a local media file and use an adjacent subtitle when available."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
import wave
from dataclasses import replace
from pathlib import Path

from app.adapters.sources.local_text import LocalTextError, import_text_file
from app.adapters.sources.prepared import PreparedSource
from app.domain.models import ContentKind

MEDIA_SUFFIXES = frozenset({".mp3", ".m4a", ".wav", ".ogg", ".mp4", ".mkv", ".mov", ".webm"})
AUDIO_SUFFIXES = frozenset({".mp3", ".m4a", ".wav", ".ogg"})


class LocalMediaError(ValueError):
    pass


def import_media_file(path: Path, *, title: str | None, language: str | None) -> PreparedSource:
    if not path.is_file():
        raise LocalMediaError("找不到本地媒体文件")
    if path.suffix.lower() not in MEDIA_SUFFIXES:
        raise LocalMediaError("当前仅支持常见音频和视频文件")

    resolved_title = (title or path.stem).strip() or path.stem
    subtitle_path = _find_sidecar_subtitle(path)
    if subtitle_path is not None:
        try:
            subtitle = import_text_file(subtitle_path, title=resolved_title, language=language)
        except LocalTextError as error:
            raise LocalMediaError(str(error)) from error
        return replace(
            subtitle,
            kind=ContentKind.VIDEO,
            title=resolved_title,
            content_hash=_file_hash(path),
            source_path=str(path.resolve()),
            source_url=path.resolve().as_uri(),
            acquisition_method="local_media_with_sidecar_subtitle",
            # 转写时长不能证明媒体总时长；探测不到总时长时由工作流拒绝生成总结。
            duration_seconds=_probe_duration(path),
        )

    # 无字幕：交给 ASR（音频文件直接用；视频先提取音轨）。
    audio_path = _audio_for_asr(path)
    return PreparedSource(
        kind=ContentKind.VIDEO,
        title=resolved_title,
        transcript=None,
        content_hash=_file_hash(path),
        source_path=str(path.resolve()),
        source_url=path.resolve().as_uri(),
        acquisition_method=(
            "local_audio_for_asr" if path.suffix.lower() in AUDIO_SUFFIXES else "local_media_extracted_audio"
        ),
        duration_seconds=_probe_duration(path),
        audio_path=str(audio_path),
        audio_is_temp=audio_path != path,
    )


def _audio_for_asr(path: Path) -> Path:
    if path.suffix.lower() in AUDIO_SUFFIXES:
        if path.stat().st_size == 0:
            raise LocalMediaError("无法识别音频内容：音频文件为空，请更换来源")
        return path
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise LocalMediaError(
            "无法识别视频内容：没有找到同名字幕，且缺少 ffmpeg 无法提取音轨。"
            "请提供字幕文件或安装 ffmpeg 后重试。"
        )
    temp_dir = Path(tempfile.mkdtemp(prefix="knowledge-asr-"))
    wav_path = temp_dir / f"{path.stem}.wav"
    process = subprocess.run(
        [
            ffmpeg,
            "-y",
            "-i",
            str(path),
            "-vn",
            "-acodec",
            "pcm_s16le",
            "-ar",
            "16000",
            "-ac",
            "1",
            str(wav_path),
        ],
        capture_output=True,
        check=False,
        encoding="utf-8",
        errors="replace",
    )
    if process.returncode != 0 or not wav_path.is_file():
        raise LocalMediaError("无法识别视频内容：音频提取失败（ffmpeg 返回错误），请提供字幕文件后重试")
    if wav_path.stat().st_size == 0:
        raise LocalMediaError("无法识别视频内容：提取的音频文件为空，请更换来源")
    return wav_path


def _find_sidecar_subtitle(path: Path) -> Path | None:
    for suffix in (".srt", ".vtt", ".txt", ".md"):
        candidate = path.with_suffix(suffix)
        if candidate.is_file():
            return candidate
    return None


def _probe_duration(path: Path) -> float | None:
    ffprobe = shutil.which("ffprobe")
    if ffprobe is None:
        if path.suffix.lower() == ".wav":
            try:
                with wave.open(str(path), "rb") as wav_file:
                    frame_rate = wav_file.getframerate()
                    if frame_rate > 0:
                        return wav_file.getnframes() / frame_rate
            except (EOFError, OSError, wave.Error):
                pass
        return None
    process = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        check=False,
        encoding="utf-8",
        errors="replace",
    )
    if process.returncode != 0:
        return None
    duration = json.loads(process.stdout).get("format", {}).get("duration")
    return float(duration) if duration is not None else None


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
