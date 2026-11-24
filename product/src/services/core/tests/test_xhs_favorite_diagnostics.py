from pathlib import Path

from fastapi.testclient import TestClient

from app.api.main import create_app

CORE = Path(__file__).resolve().parents[1]


def test_xhs_operation_id_crosses_the_shell_and_api_boundaries():
    ui = (CORE / "app/ui/app.js").read_text(encoding="utf-8")
    shell = (CORE.parent / "desktop-shell/Program.cs").read_text(encoding="utf-8")
    api = (CORE / "app/api/main.py").read_text(encoding="utf-8")
    assert 'action: "trace_favorites"' in ui
    assert 'X-Xhs-Operation-Id' in ui and 'X-Xhs-Operation-Id' in api
    assert 'xhs-import op=%s' in api
    assert 'xhs-scan op=' in shell and 'xhs-note op=' in shell


def test_backend_logs_rejected_note_without_content_or_query(tmp_path, caplog):
    client = TestClient(create_app("sqlite:///:memory:", tmp_path / "archives"))
    operation_id = "0123456789abcdef0123456789abcdef"
    response = client.post(
        "/api/v1/imports/local",
        headers={"X-Xhs-Operation-Id": operation_id},
        json={
            "text": "incompatible_local_source",
            "xiaohongshu_source": {
                "url": "https://www.xiaohongshu.com/explore/example123?xsec_token=private_token",
                "text": "private_body",
            },
            "duplicate_action": "reuse",
        },
    )
    assert response.status_code == 422
    assert f"xhs-import op={operation_id} note=example123 result=http_422 job=-" in caplog.text
    assert "private_token" not in caplog.text
    assert "private_body" not in caplog.text
