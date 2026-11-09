from __future__ import annotations

import math
from abc import ABC, abstractmethod
from collections.abc import Sequence
from urllib.parse import urlparse

import httpx

from app.core.config import Settings, get_settings
from app.core.model_budget import BudgetDenied, BudgetedSyncTransport, budget_for
from app.rag.exceptions import (
    KnowledgeBaseConfigurationError,
    KnowledgeBaseEmbeddingError,
)


class EmbeddingClient(ABC):
    @abstractmethod
    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        raise NotImplementedError

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]


class OpenAICompatibleEmbeddingClient(EmbeddingClient):
    SUPPORTED_PROVIDERS = frozenset({"openai", "openai-compatible", "openai_compatible"})

    def __init__(
        self,
        settings: Settings | None = None,
        transport: httpx.BaseTransport | None = None,
        *, operation_id: str | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._transport = transport
        self.operation_id = operation_id

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        values = [text.strip() for text in texts]
        if not values or any(not text for text in values):
            raise KnowledgeBaseEmbeddingError("Embedding 输入不能为空")
        model, api_key, base_url = self._validated_configuration()
        try:
            with httpx.Client(
                timeout=self._settings.rag_embedding_timeout,
                transport=BudgetedSyncTransport(budget_for(self._settings),
                    f"{base_url.rstrip('/')}/embeddings", "embedding", self._transport,
                    self.operation_id),
            ) as client:
                response = client.post(
                    f"{base_url.rstrip('/')}/embeddings",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json={"model": model, "input": values},
                )
                response.raise_for_status()
        except BudgetDenied:
            raise KnowledgeBaseConfigurationError("模型预算保护未通过，本次不允许调用Embedding") from None
        except httpx.TimeoutException:
            raise KnowledgeBaseEmbeddingError("Embedding 服务请求超时") from None
        except httpx.RequestError:
            raise KnowledgeBaseEmbeddingError("无法连接 Embedding 服务") from None
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in {401, 403}:
                message = "Embedding 服务认证失败"
            elif exc.response.status_code == 429:
                message = "Embedding 服务请求过于频繁"
            else:
                message = "Embedding 服务返回错误状态"
            raise KnowledgeBaseEmbeddingError(message) from None
        try:
            payload = response.json()
            data = payload["data"]
            if not isinstance(data, list) or len(data) != len(values) or any(
                not isinstance(item, dict) or type(item.get('index')) is not int for item in data
            ) or sorted(item['index'] for item in data) != list(range(len(values))):
                raise ValueError
            ordered = sorted(data, key=lambda item: item["index"])
            embeddings = [item["embedding"] for item in ordered]
            if len(embeddings) != len(values) or any(
                not isinstance(vector, list) or not vector for vector in embeddings
            ):
                raise ValueError
            converted = [[float(value) for value in vector] for vector in embeddings]
            if len({len(vector) for vector in converted}) != 1 or any(
                not math.isfinite(value) for vector in converted for value in vector
            ):
                raise ValueError
            return converted
        except (KeyError, TypeError, ValueError, OverflowError):
            raise KnowledgeBaseEmbeddingError("Embedding 服务返回格式异常") from None

    def _validated_configuration(self) -> tuple[str, str, str]:
        provider = (self._settings.rag_embedding_provider or "").strip().lower()
        model = (self._settings.rag_embedding_model or "").strip()
        base_url = (self._settings.rag_embedding_base_url or "").strip()
        api_key = (
            self._settings.rag_embedding_api_key.get_secret_value()
            if self._settings.rag_embedding_api_key is not None
            else ""
        )
        if provider not in self.SUPPORTED_PROVIDERS:
            raise KnowledgeBaseConfigurationError("未配置可用的 RAG Embedding Provider")
        if not model:
            raise KnowledgeBaseConfigurationError("RAG_EMBEDDING_MODEL 未配置")
        if not api_key:
            raise KnowledgeBaseConfigurationError("RAG_EMBEDDING_API_KEY 未配置")
        parsed = urlparse(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise KnowledgeBaseConfigurationError("RAG_EMBEDDING_BASE_URL 不是有效 HTTP 地址")
        return model, api_key, base_url
