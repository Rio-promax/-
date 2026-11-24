"""Product release metadata exposed to the desktop shell."""

APP_VERSION = "0.2.0"

# Increment only when the frontend and backend request/response contract is no
# longer compatible.  This is the single source of truth used by the API,
# generated frontend script, startup script, and their tests.
API_CONTRACT_VERSION = "2026-09-15.2"

CHANGELOG = [
    {
        "version": APP_VERSION,
        "date": "2026-08-24",
        "summary": "补齐任务可靠性、本地模型生命周期、内容库、数据治理与反馈诊断。",
    }
]

KNOWN_ISSUES = [
    "浏览器级核心流程自动验证当前受本地浏览器运行环境阻塞，需人工验收。",
    "真实公开模型下载、本地模型实际加载、云端 ASR、总结模型 API 和 Bilibili 登录态仍需人工验证。",
    "长视频总结质量和页面视觉比例仍需人工验收。",
]
