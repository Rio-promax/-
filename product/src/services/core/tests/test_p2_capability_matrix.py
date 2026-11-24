"""P2 平台能力矩阵契约测试：单一真相源 + 未实现能力不得报告为可用。"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.api.main import create_app
from app.platforms.connections import PLATFORM_DEFINITIONS


PLAN_PLATFORM_KEYS = {definition.key for definition in PLATFORM_DEFINITIONS}
CAPABILITY_FIELDS = (
    "platform",
    "display_name",
    "login_url",
    "auth_type",
    "checker_available",
    "browser_session_available",
    "supported_source_types",
    "public_import_available",
    "account_probe_available",
    "text_available",
    "image_ocr_available",
    "video_available",
    "collection_sync_available",
    "note",
)


def _capabilities() -> dict:
    client = TestClient(create_app("sqlite:///:memory:"))
    response = client.get("/api/v1/source-capabilities")
    assert response.status_code == 200
    return {item["platform"]: item for item in response.json()["capabilities"]}


def test_every_plan_platform_returns_complete_fields() -> None:
    capabilities = _capabilities()
    for key in PLAN_PLATFORM_KEYS:
        assert key in capabilities, key
        for field in CAPABILITY_FIELDS:
            assert field in capabilities[key], (key, field)


def test_fields_derive_from_platform_definitions() -> None:
    capabilities = _capabilities()
    for definition in PLATFORM_DEFINITIONS:
        entry = capabilities[definition.key]
        assert entry["display_name"] == definition.display_name
        assert entry["login_url"] == definition.login_url
        assert entry["auth_type"] == definition.auth_type
        assert entry["checker_available"] is definition.checker_available
        assert entry["browser_session_available"] is definition.browser_session_available
        assert entry["supported_source_types"] == list(definition.supported_source_types)
        assert entry["public_import_available"] is definition.public_import_available
        assert entry["account_probe_available"] is definition.account_probe_available
        assert entry["text_available"] is definition.text_available
        assert entry["video_available"] is definition.video_available
        assert entry["collection_sync_available"] is definition.collection_sync_available
        assert entry["note"] == definition.capability_note


def test_ocr_capability_reported_false_before_p5() -> None:
    # 方案 §6 P2 硬约束：P5 通过验收前 image_ocr_available 恒为 false。
    capabilities = _capabilities()
    assert capabilities
    for entry in capabilities.values():
        assert entry["image_ocr_available"] is False


def test_unverified_capabilities_not_reported_available() -> None:
    capabilities = _capabilities()
    for key in ("xiaohongshu", "zhihu", "douyin", "wechat"):
        entry = capabilities[key]
        assert entry["browser_session_available"] is (key in {"xiaohongshu", "zhihu"})
        assert entry["public_import_available"] is False
        assert entry["video_available"] is False
        assert entry["account_probe_available"] is False
        assert entry["collection_sync_available"] is False
        assert entry["text_available"] is False
    bilibili = capabilities["bilibili"]
    assert bilibili["public_import_available"] is True
    assert bilibili["video_available"] is True
    assert bilibili["account_probe_available"] is True
    assert bilibili["collection_sync_available"] is True


def test_non_connection_platforms_kept_as_documented_legacy_entries() -> None:
    # youtube / 普通网页无连接语义，不入 PlatformDefinition；作为方案范围外
    # 的静态事实保留完整字段，防止静默漂移。
    capabilities = _capabilities()
    for key in ("youtube", "web"):
        entry = capabilities[key]
        assert entry["auth_type"] == "public"
        assert entry["checker_available"] is False
        assert entry["public_import_available"] is True
        assert entry["image_ocr_available"] is False
        assert entry["note"]
