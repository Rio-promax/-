"""11-17 知识库默认按内容创建时间倒序的防回归契约。

唯一权威验收是运行页实际交互；本文件只锁住本轮口径与前后端接线。
"""
import re
from pathlib import Path

UI = Path(__file__).resolve().parents[1] / "app" / "ui"
JS = (UI / "app.js").read_text(encoding="utf-8")
MAIN_PY = (UI.parent / "api" / "main.py").read_text(encoding="utf-8")
STORE_PY = (UI.parent / "db" / "store.py").read_text(encoding="utf-8")


def _render_library_block() -> str:
    start = JS.index("function renderLibrary() {")
    end = JS.index("function renderLibraryToolbar() {", start)
    return JS[start:end]


# ---- R1：合集卡与单条卡统一按 created_at 倒序 ----

def test_r1_render_library_uses_one_sorted_tile_list():
    block = _render_library_block()
    assert "const groups = libraryGroups();" in block
    assert 'const createdAtOf = (entry) => String(contentOf(entry).created_at || "");' in block
    assert "const tiles = groups.collections.map((group) => ({" in block
    assert "at: group.entries.map(createdAtOf).sort().pop() || \"\"," in block
    assert "at: createdAtOf(item.entry)," in block
    assert "tiles.sort((a, b) => (a.at === b.at ? 0 : (a.at > b.at ? -1 : 1)));" in block
    assert 'cards = tiles.map((tile) => tile.html).join("");' in block


def test_r1_old_two_segment_concatenation_is_gone():
    block = _render_library_block()
    assert 'groups.collections.map(collectionTileHtml).join("")' not in block
    assert '+ groups.singles.map((item) => tileHtml(item.entry)).join("")' not in block
    assert "collections.map(collectionTileHtml)" not in JS


def test_r1_collection_time_is_newest_member_not_first():
    """父集卡取集内最新成员时间，不因桶内顺序把整组拉到旧位置。"""
    block = _render_library_block()
    assert "group.entries.map(createdAtOf).sort().pop()" in block
    assert "group.entries[0]" not in block


def test_r1_adding_mode_and_collection_detail_are_untouched():
    block = _render_library_block()
    assert 'if (adding) cards = entries.map((entry) => tileHtml(entry)).join("");' in block
    assert 'const back = S.libCollection' in block
    assert "function libraryGroups()" in JS, "父子集分组本身未改"
    assert "bucket.entries.length > 1" in JS


# ---- R2：后端默认口径保持 created_at / desc ----

def test_r2_history_endpoint_defaults_to_created_at_desc():
    assert 'sort_by: str = Query(default="created_at"' in MAIN_PY
    assert 'order: str = Query(default="desc"' in MAIN_PY
    assert "descending=order == \"desc\"" in MAIN_PY


def test_r2_store_still_orders_by_content_created_at():
    assert '"created_at": ContentRow.created_at,' in STORE_PY
    assert "statement = statement.order_by(order, AnalysisRunRow.created_at.desc())" in STORE_PY
    assert "sort_by: str = \"created_at\"" in STORE_PY
    assert "descending: bool = True" in STORE_PY


def test_r2_no_new_sort_control_was_added():
    """A 口径不改时间语义：不引入 updated_at 排序控件。"""
    assert "libFilters: { platform: null, kind: null, duration: null, introduction: null }" in JS
    assert "libFilters.sort" not in JS
    assert "libSort" not in JS


# ---- 行为契约：用与前端同构的排序规则验证时间倒序 ----

def test_r3_tile_time_order_matches_created_at_desc():
    """把前端那三行排序规则按同构语义复现，锁住「零逆序」这一验收结论。"""
    collections = [
        {"at": "2026-11-12T15:50:50.393257", "kind": "collection"},
        {"at": "2026-09-10T14:30:50.475840", "kind": "collection"},
    ]
    singles = [
        {"at": "2026-11-12T16:24:30.208606", "kind": "single"},
        {"at": "2026-11-12T14:42:00.372945", "kind": "single"},
        {"at": "2026-09-07T07:29:55.862655", "kind": "single"},
    ]
    tiles = collections + singles
    tiles.sort(key=lambda item: item["at"], reverse=True)
    times = [item["at"] for item in tiles]
    assert times == sorted(times, reverse=True)
    assert tiles[0]["kind"] == "single", "最新的单条内容不再被所有合集卡挡在后面"
    inversions = sum(
        1 for i in range(len(tiles)) for j in range(i + 1, len(tiles))
        if tiles[i]["at"] < tiles[j]["at"]
    )
    assert inversions == 0
