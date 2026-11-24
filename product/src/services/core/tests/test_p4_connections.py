"""P4 平台连接适配契约测试：非 B站 不写库、无专属端点、凭证不外泄。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api.main import create_app
from app.platforms.connections import get_platform_definition, probe_platform

NON_BILIBILI_PLATFORMS = ("xiaohongshu", "zhihu", "douyin", "wechat")
READ_ONLY_PLATFORMS = ("douyin", "wechat")


def _client() -> TestClient:
    return TestClient(create_app("sqlite:///:memory:"))


def test_probe_platform_uses_capability_note_copy() -> None:
    for platform in NON_BILIBILI_PLATFORMS:
        status, account, message = probe_platform(platform, None)
        definition = get_platform_definition(platform)
        assert status == "UNSUPPORTED"
        assert account is None
        assert message == definition.capability_note
        # 复审 R-B2：不再出现"已提供登录入口"类话术。
        assert "已提供登录入口" not in message
        assert "导入" in message or "读取" in message


@pytest.mark.parametrize("platform", READ_ONLY_PLATFORMS)
def test_check_returns_unsupported_without_persisting(platform: str) -> None:
    client = _client()

    response = client.post(f"/api/v1/platform-connections/{platform}/check")

    assert response.status_code == 200
    assert response.json()["status"] == "UNSUPPORTED"
    assert response.json()["message"] == get_platform_definition(platform).capability_note
    assert client.app.state.store.get_platform_connection(platform) is None


@pytest.mark.parametrize("platform", READ_ONLY_PLATFORMS)
def test_connect_returns_unsupported_without_persisting(platform: str) -> None:
    client = _client()

    response = client.post(
        f"/api/v1/platform-connections/{platform}/connect",
        json={"browser": "chrome"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "UNSUPPORTED"
    assert client.app.state.store.get_platform_connection(platform) is None


def test_xiaohongshu_connect_creates_not_connected_record() -> None:
    client = _client()

    response = client.post(
        "/api/v1/platform-connections/xiaohongshu/connect",
        json={"browser_profile": "C:/Users/test/AppData/Local/wb-shell-login-userdata"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "NOT_CONNECTED"
    assert response.json()["supported"] is True
    record = client.app.state.store.get_platform_connection("xiaohongshu")
    assert record is not None
    assert record.status == "NOT_CONNECTED"
    assert record.browser_profile.endswith("wb-shell-login-userdata")


def test_xiaohongshu_check_without_shell_does_not_claim_connected() -> None:
    client = _client()

    response = client.post("/api/v1/platform-connections/xiaohongshu/check")

    assert response.status_code == 200
    assert response.json()["status"] == "NOT_CONNECTED"
    assert "桌面壳" in response.json()["message"]
    assert client.app.state.store.get_platform_connection("xiaohongshu") is None


def test_zhihu_connect_creates_not_connected_record() -> None:
    client = _client()

    response = client.post("/api/v1/platform-connections/zhihu/connect", json={})

    assert response.status_code == 200
    assert response.json()["status"] == "NOT_CONNECTED"
    assert response.json()["supported"] is True
    assert "知乎" in response.json()["message"]
    assert client.app.state.store.get_platform_connection("zhihu").status == "NOT_CONNECTED"


def test_zhihu_browser_login_persists_business_response_status_without_credentials() -> None:
    client = _client()

    response = client.post(
        "/api/v1/platform-connections/zhihu/browser-login",
        json={"status": "CONNECTED", "message": "知乎账号业务响应已确认登录"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "CONNECTED"
    assert "cookie" not in response.text.lower()
    assert client.app.state.store.get_platform_connection("zhihu").status == "CONNECTED"


@pytest.mark.parametrize(
    "status",
    ("NOT_CONNECTED", "CONNECTED", "EXPIRED", "REAUTH_REQUIRED", "RISK_CONTROLLED"),
)
def test_browser_login_route_persists_only_allowed_status_and_safe_fields(status: str) -> None:
    client = _client()
    response = client.post(
        "/api/v1/platform-connections/xiaohongshu/browser-login",
        json={
            "status": status,
            "message": "小红书登录已确认",
            "browser_profile": "C:/Users/test/AppData/Local/wb-shell-login-userdata",
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == status
    assert "cookie" not in response.text.lower()
    record = client.app.state.store.get_platform_connection("xiaohongshu")
    assert record is not None
    assert record.status == status
    assert record.account_label is None
    assert record.browser_profile.endswith("wb-shell-login-userdata")


def test_browser_login_route_rejects_unsupported_status() -> None:
    client = _client()
    response = client.post(
        "/api/v1/platform-connections/xiaohongshu/browser-login",
        json={"status": "UNSUPPORTED", "message": "不应写入"},
    )

    assert response.status_code == 422
    assert client.app.state.store.get_platform_connection("xiaohongshu") is None


def test_browser_login_route_rejects_read_only_platforms() -> None:
    client = _client()
    response = client.post(
        "/api/v1/platform-connections/douyin/browser-login",
        json={"status": "CONNECTED", "message": "should not write"},
    )

    assert response.status_code == 404
    assert client.app.state.store.get_platform_connection("douyin") is None


def test_no_platform_specific_endpoints_for_non_bilibili() -> None:
    client = _client()
    paths = {getattr(route, "path", "") for route in client.app.routes}
    for platform in NON_BILIBILI_PLATFORMS:
        offending = [p for p in paths if platform in p]
        assert offending == [], (platform, offending)
    # B站 专属二维码端点维持现状
    assert any("bilibili/qrcode" in p for p in paths)
    # 通用三接口存在
    assert any(p.endswith("/{platform}/connect") for p in paths)
    assert any(p.endswith("/{platform}/check") for p in paths)
    assert any(p.endswith("/{platform}/browser-login") for p in paths)


@pytest.mark.parametrize("platform", NON_BILIBILI_PLATFORMS)
def test_connection_responses_do_not_leak_credentials(platform: str) -> None:
    client = _client()

    check_response = client.post(f"/api/v1/platform-connections/{platform}/check")
    connect_response = client.post(
        f"/api/v1/platform-connections/{platform}/connect", json={"browser": "chrome"}
    )
    list_response = client.get("/api/v1/platform-connections")

    for response in (check_response, connect_response, list_response):
        assert response.status_code == 200
        lowered = response.text.lower()
        assert "cookie" not in lowered
        assert "session=" not in lowered
        assert "credential" not in lowered


def test_bilibili_delete_still_cleans_session_state() -> None:
    client = _client()
    store = client.app.state.store
    store.save_platform_connection(
        platform="bilibili",
        status="CONNECTED",
        auth_type="qrcode_session",
        login_url="https://passport.bilibili.com/login",
        message="已连接",
    )

    response = client.delete("/api/v1/platform-connections/bilibili")

    assert response.status_code == 204
    assert store.get_platform_connection("bilibili") is None
