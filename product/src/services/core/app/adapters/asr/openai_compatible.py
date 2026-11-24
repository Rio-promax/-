"""OpenAI-compatible audio transcription (Groq Whisper, OpenAI whisper-1, ...).

Public transcription services exposing POST {base}/audio/transcriptions with
multipart form data and verbose_json output are supported; the default endpoint
is Groq's free public Whisper API.
"""

from __future__ import annotations

import json
import mimetypes
import uuid
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen

from app.domain.models import Transcript, TranscriptSegment

DEFAULT_API_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
DEFAULT_MODEL = "whisper-large-v3"
DEFAULT_TIMEOUT_SECONDS = 120


_ASR_MODEL_MARKERS = (
    "whisper",
    "speech-to-text",
    "speech_to_text",
    "speech-recognition",
    "speech_recognition",
    "audio-to-text",
    "audio_to_text",
    "voice-to-text",
    "voice_to_text",
    "speech2text",
    "stt",
    "transcription",
    "transcribe",
    "automatic-speech-recognition",
    "automatic_speech_recognition",
    "asr",
    "sensevoice",
    "paraformer",
    "wav2vec",
    "conformer",
    "distil-whisper",
    "moonshine",
)
_NON_ASR_MODEL_MARKERS = (
    "embedding",
    "embed-",
    "rerank",
    "re-rank",
    "reranker",
    "moderation",
    "classification",
    "image-generation",
    "image_generation",
    "text-to-image",
    "text_to_image",
    "text2image",
    "imagegen",
    "dall-e",
    "gpt-image",
    "qwen-image",
    "stable-diffusion",
    "stable_diffusion",
    "text-to-speech",
    "text_to_speech",
    "tts-",
    "-tts",
    "chat-completion",
    "chat_completion",
)


class AsrProviderError(RuntimeError):
    """Raised when an ASR service cannot return a valid result."""


class AsrModelsUnavailable(AsrProviderError):
    """Raised when an ASR service does not expose a usable model catalogue."""


class TranscriptionError(AsrProviderError):
    """Raised when the ASR service rejects or cannot be reached."""


@dataclass(frozen=True, slots=True)
class TranscriptionSettings:
    api_url: str = DEFAULT_API_URL
    api_key: str = ""
    model: str = DEFAULT_MODEL
    provider: str | None = None
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS


class OpenAICompatibleTranscriber:
    """Transcribe one audio file through an OpenAI-compatible endpoint."""

    def __init__(self, settings: TranscriptionSettings) -> None:
        self.settings = settings

    def transcribe(
        self,
        audio_path: Path,
        *,
        language: str | None = None,
    ) -> Transcript:
        if not self.settings.api_key.strip():
            raise TranscriptionError("未配置 ASR 服务密钥，请在设置页配置公开 ASR 服务后重试")
        if not audio_path.is_file():
            raise TranscriptionError("缺少可转写的音频文件")

        fields: dict[str, str] = {
            "model": self.settings.model,
            "response_format": "verbose_json",
        }
        if language:
            fields["language"] = language
        body, boundary = _multipart_body(
            fields,
            file_field="file",
            file_name=audio_path.name,
            file_bytes=audio_path.read_bytes(),
            content_type=mimetypes.guess_type(audio_path.name)[0] or "application/octet-stream",
        )
        try:
            transcription_url = asr_transcription_endpoint(self.settings.api_url)
            request = Request(
                transcription_url,
                data=body,
                headers={
                    "Authorization": f"Bearer {self.settings.api_key.strip()}",
                    "Content-Type": f"multipart/form-data; boundary={boundary}",
                },
                method="POST",
            )
        except AsrProviderError as error:
            raise TranscriptionError(str(error)) from error
        try:
            with urlopen(request, timeout=self.settings.timeout_seconds) as response:
                payload = response.read()
        except HTTPError as error:
            snippet = ""
            try:
                snippet = error.read().decode("utf-8", errors="replace")[:300]
            except OSError:
                pass
            safe_snippet = snippet.replace(self.settings.api_key.strip(), "[已隐藏]")
            raise TranscriptionError(
                f"ASR 服务返回错误（HTTP {error.code}）：{safe_snippet or '无响应内容'}"
            ) from error
        except URLError as error:
            raise TranscriptionError(
                "无法连接 ASR 服务，请检查网络或配置的 API 地址"
            ) from error
        return _parse_transcription(payload)

    def list_models(self) -> tuple[str, ...]:
        """Return only models that advertise speech transcription capability."""

        api_key = self.settings.api_key.strip()
        if not api_key:
            raise AsrProviderError("未配置 ASR 服务密钥，请先填写 API 密钥")
        try:
            request = Request(
                asr_models_endpoint(self.settings.api_url),
                headers={"Authorization": f"Bearer {api_key}"},
                method="GET",
            )
        except ValueError as error:
            raise AsrProviderError("ASR 接口地址格式不正确") from error
        try:
            with urlopen(request, timeout=self.settings.timeout_seconds) as response:
                raw = response.read()
        except HTTPError as error:
            snippet = ""
            try:
                snippet = error.read().decode("utf-8", errors="replace")[:300]
            except OSError:
                pass
            if error.code in {404, 405}:
                raise AsrModelsUnavailable(
                    "当前 ASR 服务不支持模型列表查询，请手动填写 ASR 模型 ID"
                ) from error
            if error.code in {401, 403}:
                raise AsrProviderError("ASR API 密钥无效或没有模型列表权限") from error
            safe_snippet = snippet.replace(api_key, "[已隐藏]")
            raise AsrProviderError(
                f"ASR 接口返回错误（HTTP {error.code}）：{safe_snippet or '无响应内容'}"
            ) from error
        except (TimeoutError, URLError, OSError) as error:
            raise AsrProviderError("无法连接 ASR 接口，请检查接口地址和网络") from error
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise AsrProviderError("ASR 接口返回了无法解析的 JSON") from error
        if isinstance(data, list):
            entries = data
        elif isinstance(data, dict):
            if data.get("error"):
                raise AsrProviderError(f"ASR 接口返回错误：{_error_message(data['error'])}")
            entries = data.get("data") or data.get("models")
        else:
            entries = None
        if not isinstance(entries, list):
            raise AsrModelsUnavailable(
                "接口鉴权成功，但服务商没有返回 ASR 模型列表，请手动填写 ASR 模型 ID"
            )
        models = filter_asr_models(entries)
        if not models:
            raise AsrModelsUnavailable(
                "接口鉴权成功，但没有可用的语音转写模型，请手动填写 ASR 模型 ID"
            )
        return models

    def test_connection(self) -> None:
        """Validate this ASR target without calling the summary model."""

        if not self.settings.api_key.strip():
            raise AsrProviderError("未配置 ASR 服务密钥，请先填写 API 密钥")
        if not self.settings.model.strip():
            raise AsrProviderError("未配置 ASR 模型 ID，请先填写模型 ID")
        models = self.list_models()
        if self.settings.model.strip() not in models:
            raise AsrProviderError("当前 ASR 模型不在服务商返回的模型列表中")


def _multipart_body(
    fields: dict[str, str],
    *,
    file_field: str,
    file_name: str,
    file_bytes: bytes,
    content_type: str,
) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    parts: list[bytes] = []
    for name, value in fields.items():
        parts.append(
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n".encode(
                "utf-8"
            )
        )
    parts.append(
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"{file_field}\"; filename=\"{file_name}\"\r\nContent-Type: {content_type}\r\n\r\n".encode(
            "utf-8"
        )
    )
    parts.append(file_bytes)
    parts.append(f"\r\n--{boundary}--\r\n".encode("utf-8"))
    return b"".join(parts), boundary


def _validated_url(value: str) -> tuple[str, str, str, str, str]:
    parsed = urlsplit(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise AsrProviderError("ASR 接口地址必须是完整的 http 或 https 地址")
    return parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), parsed.query, ""


def _strip_endpoint_suffix(path: str) -> str:
    lower_path = path.lower()
    for suffix in (
        "/audio/transcriptions",
        "/audio/transcription",
        "/audio/transcribe",
        "/audio-to-text",
        "/audio_to_text",
        "/transcriptions",
        "/transcription",
        "/transcribe",
        "/speech-to-text",
        "/speech_to_text",
        "/speech-recognition",
        "/speech_recognition",
        "/stt",
        "/asr",
        "/chat/completions",
        "/responses",
        "/completions",
        "/models",
    ):
        if lower_path.endswith(suffix):
            return path[: -len(suffix)]
    return path


def asr_transcription_endpoint(api_url: str) -> str:
    """Normalize an ASR base URL to /audio/transcriptions.

    Recognized full ASR endpoints are kept intact; this supports providers that
    use /transcriptions, /transcribe, or /speech-to-text instead of the OpenAI
    /audio/transcriptions suffix.  A copied summary /chat/completions or
    /responses URL is treated as a base and receives the ASR suffix.
    """

    scheme, netloc, path, query, fragment = _validated_url(api_url)
    lower_path = path.lower()
    if any(
        lower_path.endswith(suffix)
        for suffix in (
            "/audio/transcriptions",
            "/audio/transcription",
            "/audio/transcribe",
            "/audio-to-text",
            "/audio_to_text",
            "/transcriptions",
            "/transcription",
            "/transcribe",
            "/speech-to-text",
            "/speech_to_text",
            "/speech-recognition",
            "/speech_recognition",
            "/stt",
            "/asr",
        )
    ):
        return urlunsplit((scheme, netloc, path, query, fragment))
    path = _strip_endpoint_suffix(path)
    path = f"{path}/audio/transcriptions" if path else "/audio/transcriptions"
    return urlunsplit((scheme, netloc, path, query, fragment))


def asr_models_endpoint(api_url: str) -> str:
    """Normalize an ASR base URL or endpoint to its sibling /models path."""

    scheme, netloc, path, _query, _fragment = _validated_url(api_url)
    path = _strip_endpoint_suffix(path)
    path = f"{path}/models" if path else "/models"
    return urlunsplit((scheme, netloc, path, "", ""))


def _contains_marker(value: object, markers: tuple[str, ...]) -> bool:
    normalized = str(value or "").lower().replace("_", "-")
    return any(marker.replace("_", "-") in normalized for marker in markers)


def _metadata_contains_marker(value: object, markers: tuple[str, ...]) -> bool:
    """Look through provider capability metadata without treating ``false`` as enabled."""

    if isinstance(value, dict):
        return any(
            (not isinstance(enabled, bool) or enabled)
            and (
                _contains_marker(name, markers)
                or _metadata_contains_marker(enabled, markers)
            )
            for name, enabled in value.items()
        )
    if isinstance(value, (list, tuple, set)):
        return any(_metadata_contains_marker(part, markers) for part in value)
    return _contains_marker(value, markers)


def _is_asr_model(model: str, item: dict[str, object] | None) -> bool:
    if _contains_marker(model, _NON_ASR_MODEL_MARKERS):
        return False
    metadata_keys = (
        "type",
        "task",
        "tasks",
        "modality",
        "modalities",
        "capability",
        "capabilities",
        "metadata",
        "meta",
        "description",
        "info",
        "input_modalities",
        "output_modalities",
        "supported_tasks",
    )
    if item and any(
        _metadata_contains_marker(item.get(key), _NON_ASR_MODEL_MARKERS)
        for key in metadata_keys
    ):
        return False
    if _contains_marker(model, _ASR_MODEL_MARKERS):
        return True
    if not item:
        return False
    for key in metadata_keys:
        if _metadata_contains_marker(item.get(key), _ASR_MODEL_MARKERS):
            return True
    return False


def filter_asr_models(entries: list[object]) -> tuple[str, ...]:
    """Keep and de-duplicate only speech-to-text/ASR model IDs."""

    models: list[str] = []
    seen: set[str] = set()
    for item in entries:
        metadata = item if isinstance(item, dict) else None
        candidate = item
        if metadata is not None:
            candidate = metadata.get("id") or metadata.get("model") or metadata.get("name")
        model = str(candidate or "").strip()
        if not model or model in seen or not _is_asr_model(model, metadata):
            continue
        seen.add(model)
        models.append(model)
    return tuple(models)


def _error_message(value: object) -> str:
    if isinstance(value, dict):
        return str(value.get("message") or value.get("type") or "未知错误")[:300]
    return str(value)[:300]


def _parse_transcription(payload: bytes) -> Transcript:
    try:
        data = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise TranscriptionError("ASR 服务返回了无法解析的响应") from error

    segments = data.get("segments") if isinstance(data, dict) else None
    if isinstance(segments, list) and segments:
        cues: list[TranscriptSegment] = []
        for item in segments:
            if not isinstance(item, dict):
                continue
            try:
                start = float(item.get("start"))
                end = float(item.get("end"))
                text = str(item.get("text") or "").strip()
            except (TypeError, ValueError):
                continue
            if text and end >= start:
                cues.append(TranscriptSegment(start, end, text))
        if cues:
            return Transcript(None, "asr", "openai-compatible", tuple(cues))

    text = str((data.get("text") or "") if isinstance(data, dict) else "").strip()
    if not text:
        raise TranscriptionError("ASR 服务没有返回转写文本")
    return Transcript(
        None,
        "asr",
        "openai-compatible",
        (TranscriptSegment(0.0, 1.0, text),),
        position_kind="detail_only",
    )
