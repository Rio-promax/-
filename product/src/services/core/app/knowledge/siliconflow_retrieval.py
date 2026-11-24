"""SiliconFlow embedding and reranking for archived Q&A evidence."""

from __future__ import annotations

import json
import math
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

API_KEY_ENV = "SILICONFLOW_API_KEY"
EMBEDDING_MODEL = "Qwen/Qwen3-Embedding-8B"
RERANK_MODEL = "Qwen/Qwen3-Reranker-8B"
DIMENSION = 1024
EMBED_BATCH_SIZE = 32
API_ROOT = "https://api.siliconflow.cn/v1"


class AskEmbeddingUnavailableError(RuntimeError):
    """The configured cloud retrieval service cannot be used."""


class SiliconFlowRetrieval:
    dimension = DIMENSION
    config = {
        "engine": "sqlite-vec",
        "embedding_runtime": "siliconflow-api",
        "model_id": EMBEDDING_MODEL,
        "dimension": DIMENSION,
        "batch_size": EMBED_BATCH_SIZE,
        "source_map": "archive-transcript-v1",
        "span_rule": "model-advised-ordered-chunks-v1",
        "schema": "ask-index-vector-v3",
    }

    def __init__(self, api_key: str) -> None:
        if not api_key.strip():
            raise AskEmbeddingUnavailableError("未配置硅基流动 API Key")
        self._api_key = api_key.strip()

    @classmethod
    def from_environment(cls) -> SiliconFlowRetrieval | None:
        key = os.environ.get(API_KEY_ENV, "").strip()
        return cls(key) if key else None

    def embed_documents(self, texts: list[str], *, timeout: float = 60) -> list[list[float]]:
        if not texts:
            return []
        response = self._post(
            "embeddings",
            {"model": EMBEDDING_MODEL, "input": texts, "dimensions": DIMENSION},
            timeout=timeout,
        )
        data = response.get("data")
        if not isinstance(data, list) or len(data) != len(texts):
            raise AskEmbeddingUnavailableError("硅基流动返回的向量数量不匹配")
        vectors: list[list[float] | None] = [None] * len(texts)
        for item in data:
            if not isinstance(item, dict) or not isinstance(item.get("index"), int):
                raise AskEmbeddingUnavailableError("硅基流动返回的向量格式无效")
            index = item["index"]
            vector = item.get("embedding")
            if not 0 <= index < len(texts) or not isinstance(vector, list):
                raise AskEmbeddingUnavailableError("硅基流动返回的向量格式无效")
            if len(vector) != DIMENSION or not all(
                isinstance(value, (int, float)) and math.isfinite(value) for value in vector
            ):
                raise AskEmbeddingUnavailableError("硅基流动返回的向量维度或数值无效")
            norm = math.sqrt(sum(float(value) ** 2 for value in vector))
            if norm == 0:
                raise AskEmbeddingUnavailableError("硅基流动返回了零向量")
            vectors[index] = [float(value) / norm for value in vector]
        if any(vector is None for vector in vectors):
            raise AskEmbeddingUnavailableError("硅基流动返回的向量序号不完整")
        return [vector for vector in vectors if vector is not None]

    def embed_query(self, query: str, *, timeout: float = 60) -> list[float]:
        return self.embed_documents([query], timeout=timeout)[0]

    def rerank(self, query: str, documents: list[str], *, timeout: float = 60) -> list[tuple[int, float]]:
        if not documents:
            return []
        response = self._post(
            "rerank",
            {
                "model": RERANK_MODEL,
                "query": query,
                "documents": documents,
                "top_n": len(documents),
                "return_documents": False,
            },
            timeout=timeout,
        )
        results = response.get("results")
        if not isinstance(results, list) or len(results) != len(documents):
            raise AskEmbeddingUnavailableError("硅基流动返回的重排结果数量不匹配")
        ranked: list[tuple[int, float]] = []
        seen: set[int] = set()
        for item in results:
            if not isinstance(item, dict):
                raise AskEmbeddingUnavailableError("硅基流动返回的重排结果格式无效")
            index, score = item.get("index"), item.get("relevance_score")
            if (
                not isinstance(index, int)
                or not 0 <= index < len(documents)
                or index in seen
                or not isinstance(score, (int, float))
                or not math.isfinite(score)
            ):
                raise AskEmbeddingUnavailableError("硅基流动返回的重排结果格式无效")
            seen.add(index)
            ranked.append((index, float(score)))
        return ranked

    def _post(self, endpoint: str, payload: dict[str, object], *, timeout: float = 60) -> dict[str, object]:
        request = Request(
            f"{API_ROOT}/{endpoint}",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=max(1, int(timeout))) as response:
                result = json.load(response)
        except HTTPError as error:
            raise AskEmbeddingUnavailableError(
                f"硅基流动请求失败（HTTP {error.code}）"
            ) from error
        except (URLError, TimeoutError, OSError, ValueError) as error:
            raise AskEmbeddingUnavailableError("无法连接硅基流动检索接口") from error
        if not isinstance(result, dict):
            raise AskEmbeddingUnavailableError("硅基流动返回格式无效")
        return result
