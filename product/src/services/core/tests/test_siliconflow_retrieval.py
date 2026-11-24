import io
import json

import pytest

from app.knowledge import siliconflow_retrieval as cloud


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


def test_cloud_embedding_and_rerank_contract(monkeypatch):
    requests = []

    def fake_urlopen(request, timeout):
        assert timeout == 60
        requests.append((request.full_url, json.loads(request.data), request.get_header("Authorization")))
        if request.full_url.endswith("/embeddings"):
            payload = {
                "data": [
                    {"index": 1, "embedding": [0.0, 2.0] + [0.0] * (cloud.DIMENSION - 2)},
                    {"index": 0, "embedding": [2.0, 0.0] + [0.0] * (cloud.DIMENSION - 2)},
                ]
            }
        else:
            payload = {"results": [
                {"index": 1, "relevance_score": 0.9},
                {"index": 0, "relevance_score": 0.3},
            ]}
        return _Response(json.dumps(payload).encode())

    monkeypatch.setattr(cloud, "urlopen", fake_urlopen)
    backend = cloud.SiliconFlowRetrieval("test-key")
    vectors = backend.embed_documents(["第一段", "第二段"])
    assert vectors[0][:2] == [1.0, 0.0]
    assert vectors[1][:2] == [0.0, 1.0]
    assert backend.rerank("提问", ["第一段", "第二段"]) == [(1, 0.9), (0, 0.3)]
    assert requests[0][1] == {
        "model": cloud.EMBEDDING_MODEL,
        "input": ["第一段", "第二段"],
        "dimensions": cloud.DIMENSION,
    }
    assert requests[1][1]["model"] == cloud.RERANK_MODEL
    assert all(auth == "Bearer test-key" for _, _, auth in requests)


def test_cloud_failure_does_not_expose_key(monkeypatch):
    def fail(_request, timeout):
        raise cloud.HTTPError("https://api.siliconflow.cn", 401, "unauthorized", {}, None)

    monkeypatch.setattr(cloud, "urlopen", fail)
    with pytest.raises(cloud.AskEmbeddingUnavailableError) as error:
        cloud.SiliconFlowRetrieval("sensitive-test-key").embed_query("问题")
    assert "401" in str(error.value)
    assert "sensitive-test-key" not in str(error.value)


def test_cloud_key_is_saved_without_echo_and_selects_new_profile(tmp_path):
    from fastapi.testclient import TestClient

    from app.api.main import create_app

    app = create_app("sqlite:///:memory:", tmp_path / "archives")
    with TestClient(app) as client:
        response = client.put(
            "/api/v1/settings",
            json={"ai_ask_siliconflow_api_key": "synthetic-test-key"},
        )
        assert response.status_code == 200
        assert response.json()["ai_ask_cloud_configured"] is True
        assert "synthetic-test-key" not in response.text
        assert app.state.ask_index.vector_profile_id is not None
        assert app.state.ask_index._embedding_backend.config["model_id"] == cloud.EMBEDDING_MODEL
