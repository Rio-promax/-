"""Contracts for Xiaohongshu note detail observation and list recovery."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SHELL = (ROOT.parent / "desktop-shell" / "Program.cs").read_text(encoding="utf-8")
JS = (ROOT / "app" / "ui" / "app.js").read_text(encoding="utf-8")


def _section(source: str, start: str, end: str) -> str:
    return source.split(start, 1)[1].split(end, 1)[0]


def test_phone_qr_prompt_is_distinguished_from_an_unobserved_detail():
    probe = _section(
        SHELL,
        "private const string FavoriteNoteDetailVisibleScript =",
        "private const string CloseFavoriteNoteDetailScript =",
    )
    read = _section(
        SHELL,
        "public async Task<XhsSessionResult> ReadNoteAsync(",
        "private async Task<bool> EnsureFavoriteCollectionAsync(",
    )

    assert "phoneQrPrompt" in probe
    assert r"\u8bf7\u6253\u5f00\u5c0f\u7ea2\u4e66App\u626b\u7801\u67e5\u770b" in probe
    assert "event=detail_observation result=phone_qr_prompt" in SHELL
    assert "event=detail_observation result=not_observed" in SHELL
    assert "\u8bf7\u6253\u5f00\u5c0f\u7ea2\u4e66App\u626b\u7801\u67e5\u770b" in read
    assert "\u8bf7\u6253\u5f00\u5c0f\u7ea2\u4e66App\u626b\u7801\u67e5\u770b" in read


def test_verified_note_result_survives_collection_restore_failure():
    read = _section(
        SHELL,
        "public async Task<XhsSessionResult> ReadNoteAsync(",
        "private async Task<bool> EnsureFavoriteCollectionAsync(",
    )
    result = _section(SHELL, "internal sealed class XhsSessionResult", "internal sealed class XhsFavoriteAlbum")

    assert "\u8bf7\u6253\u5f00\u5c0f\u7ea2\u4e66App\u626b\u7801\u67e5\u770b" in read
    assert "\u8bf7\u6253\u5f00\u5c0f\u7ea2\u4e66App\u626b\u7801\u67e5\u770b" in read
    assert "\u8bf7\u6253\u5f00\u5c0f\u7ea2\u4e66App\u626b\u7801\u67e5\u770b" in read
    assert "\u8bf7\u6253\u5f00\u5c0f\u7ea2\u4e66App\u626b\u7801\u67e5\u770b" in read
    assert "public bool? CollectionRestored { get; }" in result
    assert "CollectionRestored = collectionRestored;" in result


def test_import_trace_records_restore_outcome_under_the_operation_id():
    submit = _section(JS, "async function submitAccountImport()", "/* ------------------------- 图二：任务")
    trace_handler = _section(SHELL, "private static void TraceXhsFrontend(", "private bool IsProductOrigin(")

    assert 'typeof read.collectionRestored === "boolean"' in submit
    assert 'read.collectionRestored ? "restore_complete" : "restore_failed"' in submit
    assert "traceXhsFavorites(operationId" in submit
    assert 'case "restore_complete": case "restore_failed":' in trace_handler
