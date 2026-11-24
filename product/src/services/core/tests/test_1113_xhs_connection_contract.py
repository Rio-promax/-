"""R4 / R5 防回归辅助契约（不是验收依据）。

唯一权威验收是「运行页实际交互」。本文件只锁住本轮落地的接线，
防止连接核实链路、壳窗口可见与分批候选回传被改回旧状。
"""
from pathlib import Path
import re

UI = Path(__file__).resolve().parents[1] / "app" / "ui"
SHELL = Path(__file__).resolve().parents[2] / "desktop-shell" / "Program.cs"

JS = (UI / "app.js").read_text(encoding="utf-8")
SHELL_TEXT = SHELL.read_text(encoding="utf-8")


def _scan_favorites_branch():
    match = re.search(
        r'else if \(action == "scan_favorites"\)\s*\{(.*?)\n\s*\}',
        SHELL_TEXT,
        re.S,
    )
    assert match, "R5：缺 scan_favorites 消息分支"
    return match.group(1)


# ---------------- R4：连接状态可核实 ----------------

def test_r4_connection_check_is_wired_to_shell():
    """设置面板「检查连接」→ 一键检查全部平台 → 壳 check_session → browser-login 写回 → 刷新连接状态。"""
    assert 'data-act="conn-check-all"' in JS, "R4：平台面板缺公共「检查连接」按钮"
    assert 'case "conn-check-all":' in JS, "R4：缺「检查连接」事件分支"
    assert "async function checkAllConnections()" in JS, "R4：缺一键检查实现"
    assert "await checkXhsConnection()" in JS, "R4：一键检查未包含小红书壳会话检查"
    assert '"check_session"' in JS, "R4：现行前端未恢复壳会话检查"
    assert '"open_login"' in JS, "R4：「连接」未触发壳登录窗口"
    assert "/platform-connections/xiaohongshu/browser-login" in JS, "R4：缺状态写回端点"
    assert "await saveXhsSession(result)" in JS, "R4：壳结果未写回连接记录"
    assert 'await refresh("connections")' in JS, "R4：写回后未刷新连接状态"


def test_r4_import_gate_uses_verified_status():
    """导入前以连接记录判断是否进扫描，未连接时不再停在「正在读取…」。"""
    assert 'conn.status !== "CONNECTED"' in JS, "R4：导入前缺连接态校验"
    assert '"小红书账号未连接"' in JS, "R4：缺未连接提示"


def test_r4_timeout_does_not_cancel_session_checks():
    """超时取消只对扫描生效，不能把 check_session / open_login 当作收藏扫描取消。"""
    assert 'if (action === "scan_favorites") {' in JS, "R4：超时取消未限定扫描动作"


# ---------------- R5(B)：壳窗口可见 + 分批候选回传 ----------------

def test_r5_scan_shows_shell_window():
    """扫描收藏时把壳窗口显示出来，用户能看到收藏页。"""
    branch = _scan_favorites_branch()
    if "ShowXhsWindow(login);" in branch:
        branch = SHELL_TEXT.split("private void ShowXhsWindow(", 1)[1].split("private async Task", 1)[0]
    assert "login.Show(this);" in branch, "R5：scan_favorites 分支未显示壳窗口"
    assert "login.BringToFront();" in branch, "R5：scan_favorites 分支未置前壳窗口"


def test_r5_progress_message_wiring():
    """壳分批回传 progress 消息，前端继续监听而不是提前结束。"""
    assert "public bool Progress { get; }" in SHELL_TEXT, "R5：结果对象缺 progress 标记"
    assert "progress = result.Progress," in SHELL_TEXT, "R5：消息未序列化 progress"
    assert "public event Action<string, IReadOnlyList<XhsFavoriteCandidate>> FavoriteScanProgress;" in SHELL_TEXT, \
        "R5：壳缺分批进度事件"
    assert "_xhsLoginForm.FavoriteScanProgress +=" in SHELL_TEXT, "R5：主壳未订阅分批进度"
    assert SHELL_TEXT.count("FavoriteScanProgress?.Invoke(requestId,") >= 4, "R5：目录/笔记分页未发进度"
    assert "if (result.progress) { onProgress?.(result); return; }" in JS, "R5：前端未把进度与终态分开"


def test_r5_partial_candidates_survive_timeout():
    """已收到的候选在超时/失败时仍交回选择界面，不再全部丢弃。"""
    assert "onProgress: (partial) => collectXhsProgress(state, partial)" in JS, "R5：扫描未挂进度回调"
    assert "result.candidates?.length ? result.candidates : state.candidates" in JS, \
        "R5：终态为空时未保留已收候选"
    assert "if (state.candidates.length) {" in JS, "R5：超时分支未走部分结果"
