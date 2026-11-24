"""11-13 B 站多 P／多批父集与历史重复折叠的防回归契约。

唯一权威验收是运行页实际交互；本文件只锁住本轮口径与前后端接线。
"""
from pathlib import Path
from types import SimpleNamespace

from app.api.main import _job_collection_fields, _job_collection_id
from app.db.store import SQLiteStore, _history_identity_key
from app.domain.models import AnalysisSettings, ContentKind, SourcePlatform

UI = Path(__file__).resolve().parents[1] / "app" / "ui"
JS = (UI / "app.js").read_text(encoding="utf-8")
STORE_PY = (UI.parent / "db" / "store.py").read_text(encoding="utf-8")

BVID = "BV1PXxd6vEaM"
P1 = f"https://www.bilibili.com/video/{BVID}/?p=1"
P2 = f"https://www.bilibili.com/video/{BVID}/?p=2"
P1_VARIANT = f"https://www.bilibili.com/video/{BVID}?p=1"


def _job(url: str, **metadata: object) -> SimpleNamespace:
    return SimpleNamespace(metadata={"source_url": url, **metadata})


# ---- R2：BVID 父集合集字段 ----

def test_season_takes_priority_over_bvid_parts():
    job = _job(P1, season_id=321, collection_title="真实合集", collection_total=20)
    assert _job_collection_id(job) == "season:321"
    assert _job_collection_fields(job) == ("season:321", "真实合集", 20)


def test_same_bvid_parts_share_one_collection():
    assert _job_collection_id(_job(P1)) == f"parts:{BVID}"
    assert _job_collection_id(_job(P2)) == f"parts:{BVID}"
    assert _job_collection_id(_job(P1_VARIANT)) == f"parts:{BVID}"


def test_parts_collection_title_uses_archive_batch_without_batch_total():
    job = _job(
        P2,
        archive_batch_name="batch_e913908b-一节课拿捏 LangChain",
        archive_total=70,
    )
    collection_id, title, total = _job_collection_fields(job)
    assert collection_id == f"parts:{BVID}"
    assert title == "batch_e913908b-一节课拿捏 LangChain"
    assert total is None, "整批总数混入其他视频，不能当父集分母"


def test_non_bilibili_or_missing_url_has_no_collection():
    assert _job_collection_id(_job("https://www.zhihu.com/question/123")) is None
    assert _job_collection_id(SimpleNamespace(metadata={})) is None
    assert _job_collection_id(SimpleNamespace(metadata={"import_batch_id": "batch-1"})) is None


# ---- R3：任务页分桶与父集显示 ----

def test_job_bucketing_uses_content_identity_and_single_item_is_not_a_parent():
    assert "function jobIdentity(job)" in JS
    assert "const key = job.collection_id || jobIdentity(job);" in JS
    assert "const identity = jobIdentity(job);" in JS
    assert "const isCollection = Boolean(bucket.collectionId) && jobs.length > 1;" in JS


# ---- R4：历史重复折叠（只在读取层，不动数据） ----

def test_history_dedup_uses_bvid_and_p_identity():
    assert "def _history_identity_key(entry: HistoryEntry) -> str:" in STORE_PY
    assert "key = _history_identity_key(entry)" in STORE_PY
    assert "unique[key] = entry" in STORE_PY


def test_list_history_folds_repeated_bvid_p_imports_without_deleting_rows():
    store = SQLiteStore("sqlite:///:memory:")
    created_ids = []
    for index, url in enumerate([P1, P1_VARIANT, P2]):
        content = store.create_content(
            kind=ContentKind.VIDEO,
            title=f"视频 P{index}",
            platform=SourcePlatform.BILIBILI,
            canonical_url=url,
            content_hash=f"hash-{index}",
        )
        created_ids.append(content.id)
        store.create_analysis_run(content.id, AnalysisSettings(model="test"))

    entries = store.list_history()
    assert len(entries) == 2, "同一 BVID+P 的重复导入折叠成一行，不同 P 各自保留"
    assert len({_history_identity_key(entry) for entry in entries}) == 2
    for content_id in created_ids:
        assert store.get_content(content_id) is not None, "折叠只发生在读取层，数据不删不合并"
