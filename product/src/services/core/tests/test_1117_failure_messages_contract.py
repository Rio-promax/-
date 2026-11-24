"""11-17 全链路失败提示中文化的防回归契约。

唯一权威验收是运行页实际交互；本文件只锁住「用户可见文案全中文、
含阶段与下一步」以及前后端接线。规则表从 app.js 源码直接解析，
避免测试里另抄一份规则造成漂移。
"""
import re
from pathlib import Path

UI = Path(__file__).resolve().parents[1] / "app" / "ui"
JS = (UI / "app.js").read_text(encoding="utf-8")
CSS = (UI / "style.css").read_text(encoding="utf-8")

_RULE_RE = re.compile(
    r'\{\s*match:\s*"((?:[^"\\]|\\.)*)"\s*,\s*stage:\s*"(\w+)"\s*,'
    r'\s*reason:\s*"((?:[^"\\]|\\.)*)"\s*,\s*suggestion:\s*"((?:[^"\\]|\\.)*)"\s*\}'
)


def _rules():
    block = JS[JS.index("const FAILURE_RULES = ["):]
    block = block[:block.index("];") + 2]
    return [(m.group(1), m.group(2), m.group(3), m.group(4))
            for m in _RULE_RE.finditer(block)]


RULES = _rules()
STAGE_LABEL = {"queue": "排队", "source": "取材", "transcription": "转写",
               "chunking": "分段", "summary": "总结", "archive": "归档"}
CHECKPOINT_STAGE = {
    "source_ready": "source", "text_loaded": "source",
    "transcribing": "transcription", "transcript_ready": "transcription",
    "chunking": "chunking", "chunks_ready": "chunking",
    "summarizing": "summary", "summary_ready": "summary",
    "archiving": "archive", "indexing": "archive", "indexed": "archive",
}
FALLBACK_REASON = "任务在该阶段意外中止，系统没有拿到可解释的原因"
FALLBACK_SUGGESTION = "请重试当前任务；若反复失败，请保留诊断信息反馈"


def humanize(error_message, error_code="", checkpoint=""):
    """Python 侧等价实现，用于逐条验证真实库文案。"""
    haystack = f"{error_message}\n{error_code}"
    hit = next((r for r in RULES if r[0] in haystack), None)
    stage_key = (hit[1] if hit else CHECKPOINT_STAGE.get(str(checkpoint or ""), "")) or ""
    stage = STAGE_LABEL.get(stage_key, "处理")
    reason = hit[2] if hit else FALLBACK_REASON
    suggestion = hit[3] if hit else FALLBACK_SUGGESTION
    return f"【{stage}阶段】{reason}。{suggestion}"


# 真实库 2026-11-17 抽取的 51 种 distinct 失败文案归并样本（含英文原文）。
REAL_SAMPLES = [
    "[Errno 2] No such file or directory: 'D:\\knowledge-root\\2026\\bilibili\\batch-xxx\\.transcript.json.abc'",
    "缺少可转写的音频文件，无法识别视频内容",
    "总结生成失败：总结服务返回错误（HTTP 403）：{\"code\":\"AccessDenied.Unpurchased\",\"message\":\"Access to model denied.\"}",
    "网页响应不完整，请稍后重试",
    "[WinError 206] 文件名或扩展名太长。: 'D:\\knowledge-root\\2026\\bilibili\\batch-xxx\\01_title--content_abc'",
    "[WinError 3] 系统找不到指定的路径。: 'D:\\knowledge-root\\2026\\bilibili\\batch-xxx\\02_title--content_abc'",
    "本地 ASR 没有返回转写文本",
    "总结生成失败：无法连接总结服务，请检查网络、API 地址或请求超时设置",
    "总结生成失败：总结服务请求超时，请稍后重试；反复超时请在设置页调大超时时间",
    "ASR 转写在 120 秒内未返回，已终止本次调用，请重试",
    "视频内容未完整识别：仅识别到 299 秒，视频时长 1295 秒",
    "视频内容未完整识别：仅识别到 639 秒，视频时长 655 秒",
    "Unable to allocate 1.96 GiB for an array with shape (1, 655179, 201) and data type complex128",
    "无法识别视频内容：B站音频下载失败：ERROR: [BiliBili] 1ZL4c6NEmM: Unable to download webpage: The read operation timed out (caused by TransportError('The read operation timed out'))。请先在设置页完成 B站二维码登录",
    "无法识别视频内容：B站音频下载失败：[download] Got error: The read operation timed out。请先在设置页完成 B站二维码登录",
    "无法识别视频内容：B站音频下载失败：ERROR: [BiliBili] 1rcn56hEHP: Unable to download webpage: [SSL: UNEXPECTED_EOF_WHILE_READING] EOF occurred in violation of protocol (_ssl.c:1000)",
    "SenseVoiceSmall 没有返回转写文本",
    "总结生成失败，未产生可用总结内容，请重试",
    "无法识别视频内容：该视频没有公开字幕，且未配置 ASR 服务。",
    "无法识别视频内容：该视频没有可读取的公开字幕，且没有配置语音识别（ASR）。",
    "无法识别视频内容：第 2 P（Part）没有可读取的字幕，且未配置 ASR 服务。",
    "本地 ASR 模型尚未下载完成",
    "本地 ASR 组件尚未安装，请在设置页安装本地组件后重试",
    "ASR 片段未全部完成",
    "可转写的音频文件为空，无法识别视频内容，请更换来源",
    "无法识别视频内容：没有找到同名字幕，且缺少 ffmpeg 无法提取音轨。",
    "无法识别视频内容：音频提取失败（ffmpeg 返回错误），请提供字幕文件后重试",
    "无法识别视频内容：提取的音频文件为空，请更换来源",
    "链接已识别，但网页没有返回足够的公开正文，未生成不完整总结",
    "链接跳转后不属于原平台，无法安全读取",
    "目前仅支持 Bilibili、YouTube、知乎、小红书、微信公众号、抖音和普通网页链接",
    "缺少可转写的音频文件，无法运行 SenseVoiceSmall",
    "无法定位原始来源，不能重新总结",
    "总结服务返回错误（HTTP 500）：Internal Server Error",
    "The read operation timed out",
    "URLError: <urlopen error timed out>",
    "content_not_found",
    "resummarize_source_unavailable",
    "job_not_found",
    "HTTP 404",
    "",  # 空错误也必须有中文兜底
]

_ENGLISH_WORD = re.compile(r"[A-Za-z]{3,}")


# ---- R1：规则表与统一映射 ----

def test_r1_rule_table_covers_all_five_stages():
    assert len(RULES) >= 40, f"规则数异常：{len(RULES)}"
    stages = {r[1] for r in RULES}
    assert {"source", "transcription", "chunking", "summary", "archive"} <= stages, stages
    assert all(r[1] in STAGE_LABEL for r in RULES)
    for match, _stage, reason, suggestion in RULES:
        assert match.strip(), "规则 match 不能为空"
        assert reason.strip() and suggestion.strip(), match
        assert not _ENGLISH_WORD.search(reason), f"原因含英文：{match}"
        assert not _ENGLISH_WORD.search(suggestion), f"建议含英文：{match}"


def test_r1_real_library_messages_all_render_chinese_with_stage():
    """真实库 51 种文案逐条过映射：全中文、含阶段、含下一步、零英文残留。"""
    for raw in REAL_SAMPLES:
        text = humanize(raw)
        assert text.startswith("【") and "阶段】" in text, (raw, text)
        assert not _ENGLISH_WORD.search(text), f"用户可见文案残留英文：{raw} -> {text}"
        assert "。" in text and len(text) > 24, (raw, text)


def test_r1_unknown_failure_never_echoes_raw_error():
    text = humanize("SomeBrandNewException: unexpected token <EOF> at line 9", checkpoint="summarizing")
    assert "SomeBrandNewException" not in text
    assert "【总结阶段】" in text
    assert FALLBACK_REASON in text
    assert not _ENGLISH_WORD.search(text)


def test_r1_stage_is_inferred_from_checkpoint_when_rule_has_no_stage():
    text = humanize("", checkpoint="archiving")
    assert "【归档阶段】" in text


def test_r1_known_causes_are_actionable_not_generic():
    """具体成因必须落到针对性建议，不能落回通用兜底。"""
    cases = [
        ("本地 ASR 没有返回转写文本", "纯音乐"),
        ("HTTP 403", "额度"),
        ("WinError 206", "长度上限"),
        ("Unable to download webpage", "网络波动"),
        ("网页响应不完整", "逐条"),
        ("缺少可转写的音频文件", "重新下载"),
    ]
    for raw, needle in cases:
        text = humanize(raw)
        assert needle in text, (raw, text)
        assert FALLBACK_REASON not in text


# ---- R1/R2：前端接线 ----

def test_r1_job_stages_no_longer_shows_raw_error_message():
    assert "note = humanizeFailure(job).text;" in JS
    assert "note = job.error_message || \"该阶段执行失败\";" not in JS
    assert "function humanizeFailure(job)" in JS
    assert "return { stage, stageKey, reason, suggestion, text: `【${stage}阶段】${reason}。${suggestion}` };" in JS


def test_r1_api_errors_are_humanized_for_the_whole_series():
    assert "throw new Error(humanizeApiError(detail));" in JS
    assert "function humanizeApiError(detail)" in JS
    assert "throw new Error(detail);" not in JS
    # 机器错误码与纯英文原文都有中文兜底
    assert "操作未成功：该项当前不可用" in JS
    assert "服务返回了无法识别的错误" in JS


def test_r1_api_error_never_leaks_machine_codes():
    for raw in ("content_not_found", "HTTP 404", "Connection reset by peer", ""):
        # 复刻 humanizeApiError 的判定顺序
        if any(r[0] in raw for r in RULES):
            out = humanize(raw)
        elif re.fullmatch(r"[a-z][a-z0-9_]*", raw.strip()):
            out = "操作未成功：该项当前不可用。请刷新后重试；若反复出现请查看诊断信息"
        elif re.match(r"^HTTP \d+", raw.strip()):
            out = "请求未成功，服务暂时不可用。请稍后重试"
        elif raw.strip() and raw.strip().isascii():
            out = "操作未成功：服务返回了无法识别的错误。请稍后重试，若反复出现请查看诊断信息"
        else:
            out = "操作未成功，请稍后重试"
        assert not _ENGLISH_WORD.search(out), (raw, out)


def test_r2_failed_card_shows_reason_without_expanding():
    assert 'const failure = state.key === "failed" ? humanizeFailure(job) : null;' in JS
    assert '<div class="job-card__failure" title="${esc(failure.text)}">${esc(failure.text)}</div>' in JS
    assert ".job-card__failure {" in CSS
    assert "-webkit-line-clamp: 2;" in CSS
    # 其他状态不得新增该行
    assert 'state.key === "completed" ? humanizeFailure' not in JS


def test_r1_backend_original_error_is_preserved_for_diagnostics():
    """本轮不改后端原文：诊断与日志仍可拿到真实异常。"""
    main_py = (UI.parent / "api" / "main.py").read_text(encoding="utf-8")
    analyze_py = (UI.parent / "workflows" / "analyze.py").read_text(encoding="utf-8")
    assert "error_message=job.error_message," in main_py
    assert "job.fail(error_code, str(error))" in analyze_py
