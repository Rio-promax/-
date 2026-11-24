"""11-21 小红书收藏导入链路的源码接线契约。

真实 WebView 登录页与逐条导入仍需人工验收；这里防止候选链接、正文校验、
失败分层与重试状态在后续改动中退回旧行为。
"""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SHELL = (ROOT.parent / "desktop-shell" / "Program.cs").read_text(encoding="utf-8")
JS = (ROOT / "app" / "ui" / "app.js").read_text(encoding="utf-8")


def _section(source: str, start: str, end: str) -> str:
    return source.split(start, 1)[1].split(end, 1)[0]


def test_favorite_page_keeps_original_token_source_and_dom_url_wins():
    """响应不得伪造 pc_collect；同 ID 的 DOM href 覆盖响应候选。"""
    assert "xsec_source=pc_collect" not in SHELL
    parser = _section(
        SHELL,
        "private static FavoriteEvidence ParseFavoritePage(",
        "private static FavoriteEvidence ParseBoardFavoritePage(",
    )
    assert 'FirstString(note, "xsec_source", "xsecSource")' in parser
    assert "FirstString(source, \"xsec_source\", \"xsecSource\")" in parser
    assert "MergeFavoriteCandidatesLocked(evidence.Candidates);" in SHELL
    merge = _section(
        SHELL,
        "private void MergeFavoriteCandidatesLocked(",
        "private async Task<string> ProbeFavoritePageAsync(",
    )
    assert "candidate.HasOriginalDomUrl" in merge
    assert "_favoriteScanCandidates[existingIndex] = candidate;" in merge
    assert "HasOriginalDomUrl = hasOriginalDomUrl" in SHELL


def test_note_read_waits_for_nonempty_body_matching_requested_id():
    """壳只在正文非空且笔记 ID 与所请求链接一致时返回成功。"""
    parser = _section(
        SHELL,
        "private async Task<(XhsNoteDetail Note, string Observation)> ReadNoteFromPageAsync(",
        "private const string FavoriteNoteDomScript =",
    )
    assert 'if (!bodyPresent) return (null, "detail_visible");' in parser
    assert "string.Equals(id, noteId, StringComparison.Ordinal)" in parser
    assert "if (string.IsNullOrWhiteSpace(id)) id = noteId;" not in parser
    script = _section(
        SHELL,
        "private const string NoteDetailScript =",
        "public async Task<XhsSessionResult> ReadNoteAsync(",
    )
    assert "targetId" in script and "entryId" in script
    assert "entryId !== targetId" in script
    assert "matchedId || targetId" not in script
    read = _section(
        SHELL,
        "public async Task<XhsSessionResult> ReadNoteAsync(",
        "private async Task<(XhsNoteDetail Note, string Observation)> ReadNoteFromPageAsync(",
    )
    assert "attempt < 10" in read
    assert "ReadNoteFromPageAsync(noteId, trace)" in read or "ReadNoteFromPageAsync(noteId)" in read


def test_note_read_uses_the_scanned_favorite_scope_and_native_card():
    submit = _section(JS, "async function submitAccountImport()", "/* ------------------------- 图二：任务")
    assert 'scope: state.activeAlbumId ? "album" : "notes"' in submit
    assert "albumId: state.activeAlbumId || null" in submit

    assert (
        "ReadNoteAsync(requestId, noteUrl, noteScope, noteAlbumId)" in SHELL
        or "ReadNoteAsync(xhsOperationId, noteUrl, noteScope, noteAlbumId)" in SHELL
    )
    read = _section(
        SHELL,
        "public async Task<XhsSessionResult> ReadNoteAsync(",
        "private async Task<(XhsNoteDetail Note, string Observation)> ReadNoteFromPageAsync(",
    )
    assert "_favoriteScanScope" in read
    assert "_favoriteScanAlbumId" in read
    assert "_favoriteScanIds.Contains(noteId)" in read
    assert "OpenFavoriteNoteAsync(noteId" in read
    assert "RestoreFavoriteListAsync(" in read
    assert "NavigateAndWaitAsync(url)" not in read


def test_note_read_restores_the_favorite_list_after_opening_detail():
    assert "CaptureFavoriteListStateScript" in SHELL
    assert "RestoreFavoriteListStateScript" in SHELL
    assert "private async Task<bool> RestoreFavoriteListAsync(" in SHELL
    assert "_favoriteScanCollectionUrl" in SHELL
    assert "CoreWebView2.GoBack" in SHELL or "_core.GoBack()" in SHELL


def test_native_card_read_restores_the_pre_search_list_position_if_card_is_missing():
    read = _section(
        SHELL,
        "public async Task<XhsSessionResult> ReadNoteAsync(",
        "private async Task<bool> EnsureFavoriteCollectionAsync(",
    )
    assert "string originalListState = await CaptureFavoriteListStateAsync();" in read
    assert read.index("originalListState = await CaptureFavoriteListStateAsync()") < read.index("OpenFavoriteNoteAsync(noteId")
    assert "if (string.IsNullOrWhiteSpace(listState))" in read
    assert "RestoreFavoriteListAsync(scope, collectionUrl, originalListState)" in read
    assert "_favoriteReadCandidateIndex = -1;" in read
    restore_at = read.index("bool restored = await RestoreFavoriteListAsync(scope, collectionUrl, listState);")
    note_at = read.index("if (note == null)", restore_at)
    restore_result = read[restore_at:note_at]
    assert "Trace.LogAlways(trace + \" event=restore ok=\" + restored);" in restore_result
    assert "_favoriteReadCandidateIndex = -1;" in restore_result
    assert 'return new XhsSessionResult("REAUTH_REQUIRED", "笔记读取后未能恢复原收藏列表")' not in restore_result


def test_note_body_is_read_only_from_a_visible_detail_card():
    parser = _section(
        SHELL,
        "private async Task<(XhsNoteDetail Note, string Observation)> ReadNoteFromPageAsync(",
        "private const string FavoriteNoteDomScript =",
    )
    assert "ExecuteScriptAsync(FavoriteNoteDetailVisibleScript)" in parser
    assert "if (!detailVisible)" in parser
    assert 'return (null, "detail_not_observed");' in parser
    assert parser.index("FavoriteNoteDetailVisibleScript") < parser.index("ExecuteScriptAsync(script)")


def test_album_collection_can_be_reopened_without_a_scan_request():
    helper = _section(
        SHELL,
        "private async Task<bool> ClickFavoriteAlbumLinkAsync(",
        "private static bool TryResolveFavoriteAlbum(",
    )
    assert helper.count("requestId == null || !FavoriteScanCancelled(requestId)") == 2


def test_detail_close_sends_only_one_bubbling_escape_event():
    close = _section(
        SHELL,
        "private const string CloseFavoriteNoteDetailScript =",
        "public async Task<XhsSessionResult> ReadNoteAsync(",
    )
    assert "document.dispatchEvent(new KeyboardEvent('keydown'" in close
    assert "window.dispatchEvent" not in close


def test_note_read_diagnostics_report_route_identity_and_body_status_only():
    probe = _section(
        SHELL,
        "private const string FavoriteNoteDetailVisibleScript =",
        "private const string CloseFavoriteNoteDetailScript =",
    )
    assert "routeType" in probe
    assert "titleVisible" in probe and "bodyVisible" in probe
    assert "location.href" not in probe

    parser = _section(
        SHELL,
        "private async Task<(XhsNoteDetail Note, string Observation)> ReadNoteFromPageAsync(",
        "private const string FavoriteNoteDomScript =",
    )
    assert "route=" in parser and "id_match=" in parser and "body_present=" in parser
    assert "Trace.XhsId(id)" not in parser
    read = _section(
        SHELL,
        "public async Task<XhsSessionResult> ReadNoteAsync(",
        "private async Task<bool> EnsureFavoriteCollectionAsync(",
    )
    assert "event=restore" in read
    assert "Trace.XhsId(noteId)" not in read and "Trace.XhsId(albumId)" not in read


def test_xhs_import_errors_are_separate_and_failed_items_remain_retryable():
    """壳读取与后端建单错误分别标记；失败项保留勾选，成功项可退出。"""
    renderer = _section(JS, "function renderAccountImport()", "function closeAccountImport()")
    assert "item.importError" in renderer
    assert "item.importError.stage" in renderer
    submit = _section(JS, "async function submitAccountImport()", "/* ------------------------- 图二：任务")
    assert "壳读取失败" in submit
    assert "后端导入失败" in submit
    assert "state.selected.delete(" in submit
    assert "if (shellFailed + importFailed)" in submit
    assert submit.index("if (shellFailed + importFailed)") < submit.index("closeAccountImport();")
    assert "await post(\"/imports/bilibili/scans/confirm\"" in submit


def test_empty_favorite_page_does_not_close_the_scan_before_real_pages():
    """收藏页会先回预取空页：空页只作一轮宽限，后到的 has_more=true 必须推翻末页判定。"""
    scan = _section(
        SHELL,
        "public async Task<XhsSessionResult> ScanFavoritesAsync(",
        "private XhsSessionResult FinishFavoriteScan(",
    )
    assert "firstPage.IsEmptyPage && !firstPage.HasMore" in scan
    assert "emptyPageGrace" in scan
    assert "_favoriteLastPage != null && !_favoriteLastPage.IsEmptyPage" in scan
    assert 'state=" + scrollState' in scan

    response = _section(
        SHELL,
        "private async void OnResponseReceived(",
        "private bool IsCurrentFavoritePage(",
    )
    assert "if (evidence.IsAuthenticatedBusinessResponse && evidence.HasMore)" in response
    assert "_favoriteLastPage = null;" in response

    parser = _section(
        SHELL,
        "private static FavoriteEvidence ParseFavoritePage(",
        "private static FavoriteEvidence ParseBoardFavoritePage(",
    )
    assert "IsEmptyPage = status == 200 && hasNotes && notes.GetArrayLength() == 0," in parser


def test_favorite_scan_renders_candidates_while_still_reading():
    """读取中就把已拿到的候选画出来，并且只追加新条目，避免整体重绘清掉滚动位置。"""
    renderer = _section(JS, "function renderAccountImport()", "function closeAccountImport()")
    assert 'state.step === "candidates" || (state.step === "scanning" && allCandidates.length)' in renderer
    assert 'body.querySelector(".account-import__list")' in renderer
    assert 'insertAdjacentHTML("beforeend"' in renderer
    assert 'data-candidate-id="${esc(id)}"' in renderer
    assert "读取中…" in renderer
