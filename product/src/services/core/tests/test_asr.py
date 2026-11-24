"""Tests for the OpenAI-compatible ASR adapter."""

import json
import uuid

import pytest

from app.adapters.asr.openai_compatible import (
    OpenAICompatibleTranscriber,
    TranscriptionError,
    TranscriptionSettings,
    _multipart_body,
    _parse_transcription,
)
from app.domain.models import TranscriptSegment


class FakeResponse:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args) -> None:
        return None

    def read(self) -> bytes:
        return self._payload


def make_audio(tmp_path) -> str:
    audio = tmp_path / "audio.m4a"
    audio.write_bytes(b"fake-audio-bytes")
    return str(audio)


def test_multipart_body_contains_file_and_fields() -> None:
    body, boundary = _multipart_body(
        {"model": "whisper-large-v3", "response_format": "verbose_json"},
        file_field="file",
        file_name="a.m4a",
        file_bytes=b"abc",
        content_type="audio/mpeg",
    )
    text = body.decode("utf-8")
    assert boundary in text
    assert 'name="model"' in text
    assert 'name="file"; filename="a.m4a"' in text
    assert "abc" in text
    assert text.endswith("--" + boundary + "--\r\n")


def test_parse_transcription_uses_segments(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = json.dumps(
        {
            "text": "全文",
            "segments": [
                {"start": 0.0, "end": 3.2, "text": "第一句。"},
                {"start": 3.2, "end": 7.5, "text": "第二句。"},
            ],
        }
    ).encode("utf-8")

    transcript = _parse_transcription(payload)

    assert transcript.source_kind == "asr"
    assert transcript.engine == "openai-compatible"
    assert len(transcript.segments) == 2
    assert transcript.segments[0].start_seconds == 0.0
    assert transcript.segments[1].text == "第二句。"


def test_parse_transcription_falls_back_to_plain_text() -> None:
    payload = json.dumps({"text": "只有一段转写文本"}).encode("utf-8")

    transcript = _parse_transcription(payload)

    assert len(transcript.segments) == 1
    assert transcript.segments[0].text == "只有一段转写文本"
    assert transcript.position_kind == "detail_only"


def test_parse_transcription_reports_empty_asr_result() -> None:
    with pytest.raises(TranscriptionError, match="ASR 服务没有返回转写文本"):
        _parse_transcription(b'{"text":"", "segments":[]}')


def test_transcribe_sends_authorization_and_parses_response(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    captured = {}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["auth"] = request.get_header("Authorization")
        captured["method"] = request.get_method()
        return FakeResponse(
            json.dumps(
                {"segments": [{"start": 0.0, "end": 2.0, "text": "转写内容。"}]}
            ).encode("utf-8")
        )

    monkeypatch.setattr("app.adapters.asr.openai_compatible.urlopen", fake_urlopen)
    transcriber = OpenAICompatibleTranscriber(
        TranscriptionSettings(api_key="secret-key", model="whisper-large-v3")
    )
    audio = tmp_path / "a.m4a"
    audio.write_bytes(b"fake-audio")

    transcript = transcriber.transcribe(audio, language="zh")

    assert captured["auth"] == "Bearer secret-key"
    assert captured["url"].endswith("/audio/transcriptions")
    assert transcript.segments[0].text == "转写内容。"
    assert isinstance(transcript.segments[0], TranscriptSegment)


def test_transcribe_reports_missing_key() -> None:
    transcriber = OpenAICompatibleTranscriber(TranscriptionSettings(api_key=""))

    with pytest.raises(TranscriptionError, match="未配置 ASR 服务密钥"):
        transcriber.transcribe(__import__("pathlib").Path("a.m4a"))


def test_transcribe_reports_http_error(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    from urllib.error import HTTPError

    class FakeHTTPError(HTTPError):
        def __init__(self) -> None:
            super().__init__("https://asr.test", 401, "Unauthorized", {}, None)

        def read(self) -> bytes:
            return b'invalid api key'

    def fake_urlopen(request, timeout):
        raise FakeHTTPError()

    monkeypatch.setattr("app.adapters.asr.openai_compatible.urlopen", fake_urlopen)
    transcriber = OpenAICompatibleTranscriber(TranscriptionSettings(api_key="bad"))
    audio = tmp_path / "a.m4a"
    audio.write_bytes(b"fake-audio")

    with pytest.raises(TranscriptionError, match="HTTP 401"):
        transcriber.transcribe(audio)
