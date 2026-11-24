"""11-17 无人声视频（纯音乐／纯画面）不再被 ASR 判为失败的契约。

真实验收是跑一条无语音视频；本文件锁住四层放行点与 M0 降级路径，
并保留「真正故障仍然报错」的反向断言。
"""
from __future__ import annotations

from pathlib import Path

from app.db.store import SQLiteStore
from app.domain.models import AnalysisSettings, ContentKind, SourcePlatform, Transcript
from app.workflows.analyze import _validate_video_transcript

APP = Path(__file__).resolve().parents[1] / "app"
LOCAL_ASR = (APP / "adapters" / "asr" / "local.py").read_text(encoding="utf-8")
ANALYZE = (APP / "workflows" / "analyze.py").read_text(encoding="utf-8").replace("\r\n", "\n")


def _store_with_job() -> tuple[SQLiteStore, str]:
    store = SQLiteStore("sqlite:///:memory:")
    content = store.create_content(
        kind=ContentKind.AUDIO,
        title="no speech",
        platform=SourcePlatform.LOCAL,
    )
    _run, job = store.create_analysis_run(content.id, AnalysisSettings(model="test"))
    return store, job.id


def test_r1_local_engines_return_empty_instead_of_raising() -> None:
    # Worker 单片 / 批量、SenseVoice 单进程、faster-whisper 四处放行
    assert 'raise RuntimeError("SenseVoiceSmall 没有返回转写文本")' not in LOCAL_ASR
    assert "片没有文本" not in LOCAL_ASR
    assert 'raise LocalAsrError("SenseVoiceSmall 没有返回转写文本")' not in LOCAL_ASR
    assert 'raise LocalAsrError("本地 ASR 没有返回转写文本")' not in LOCAL_ASR


def test_r1_real_failures_still_raise() -> None:
    # 引擎故障、无效结果、超时不得被一起放行
    assert 'raise LocalAsrError("SenseVoiceSmall 没有返回结果")' in LOCAL_ASR
    assert 'raise LocalAsrError("SenseVoiceSmall 返回了无效结果")' in LOCAL_ASR
    assert 'raise LocalAsrError("SenseVoiceSmall Worker 异常退出")' in LOCAL_ASR
    assert 'raise LocalAsrError("本地 ASR 模型尚未下载完成")' in LOCAL_ASR


def test_r2_empty_segment_text_commits_as_completed() -> None:
    store, job_id = _store_with_job()
    store.create_asr_segments(
        job_id,
        "cfg",
        [{"segment_index": 0, "start_seconds": 0.0, "end_seconds": 30.0}],
    )
    claimed = store.claim_asr_segment(
        job_id, "cfg", "worker-1", lease_seconds=60, worker_generation=1
    )
    assert claimed is not None
    committed = store.commit_asr_segment(
        claimed.id, "worker-1", worker_generation=1, text="  "
    )
    assert committed.status == "completed"
    assert committed.text == ""


def test_r3_all_empty_transcript_degrades_to_m0() -> None:
    empty = Transcript(None, "asr", "funasr:sensevoice-small", ())
    assert _validate_video_transcript(empty, 600.0) == "M0"
    assert 'raise WorkflowAsrError(JobErrorCode.TRANSCRIPT_INCOMPLETE, "SenseVoiceSmall 没有返回转写文本")' not in ANALYZE


def test_r4_no_speech_is_recorded_on_the_job() -> None:
    assert 'job.metadata["asr_no_speech"] = not segments' in ANALYZE
    assert 'job.metadata.pop("asr_no_speech", None)' in ANALYZE
    # 11-23：标记必须在 workflow 主流程统一写入，覆盖 SenseVoice 切片、
    # faster-whisper 单次、云端三条路径；只在切片路径写会漏。
    assert 'transcript.source_kind == "asr" and not transcript.segments' in ANALYZE


def test_r4_empty_summary_says_why() -> None:
    assert "未检测到可转写的语音内容。" in ANALYZE
    assert "本文无相关字幕。" in ANALYZE
    assert 'job.metadata.get("asr_no_speech")' in ANALYZE
    # 非无语音的 M0 仍用原来的通用空态
    assert "尚未取得可用正文材料。" in ANALYZE


def test_r5_m0_keeps_the_explanation_as_body() -> None:
    # 11-23：M0 不再把正文写成空串，否则界面只能显示「暂无正文」，
    # 用户看不到无语音的原因。
    assert '"" if material_level == "M0" else summary.markdown' not in ANALYZE
    assert "content.id,\n                summary.markdown," in ANALYZE
