"""Optional offline cross-encoder adapter, isolated behind a hard process timeout."""

from __future__ import annotations

import json
import math
import os
import subprocess
import sys
from collections.abc import Sequence
from numbers import Real
from pathlib import Path
from typing import Protocol


class Reranker(Protocol):
    def score(self, query: str, documents: list[str]) -> list[float]: ...


class APIReranker:
    """Explicit opt-in rerank API, same credentials/endpoint and budget as embeddings."""
    def __init__(self, settings, operation_id, *, transport=None):
        self.settings, self.operation_id, self.transport = settings, operation_id, transport

    def score(self, query, documents):
        import httpx
        from app.rag.embedding_client import OpenAICompatibleEmbeddingClient
        from app.core.model_budget import BudgetedSyncTransport, budget_for
        if not documents:
            return []
        if not isinstance(query, str) or not query.strip() or any(not isinstance(d,str) or not d.strip() for d in documents):
            raise ValueError('Invalid reranker input')
        _, key, base = OpenAICompatibleEmbeddingClient(self.settings)._validated_configuration()
        endpoint = base.rstrip('/')+'/rerank'
        with httpx.Client(timeout=self.settings.rag_reranker_timeout,
                transport=BudgetedSyncTransport(budget_for(self.settings), endpoint, 'rerank', self.transport, self.operation_id)) as client:
            response=client.post(endpoint,headers={'Authorization':'Bearer '+key},json={
                'model':self.settings.rag_reranker_model,'query':query,'documents':documents,
                'top_n':len(documents),'return_documents':False})
            if not 200 <= response.status_code < 300:
                raise RuntimeError('Reranker provider request failed')
            rows=response.json().get('results')
        if not isinstance(rows,list) or len(rows)!=len(documents):
            raise ValueError('Incomplete reranker results')
        scores=[None]*len(documents)
        for row in rows:
            if not isinstance(row,dict) or type(row.get('index')) is not int or not 0<=row['index']<len(documents) or scores[row['index']] is not None:
                raise ValueError('Ambiguous reranker result index')
            value=row.get('relevance_score')
            if isinstance(value,bool) or not isinstance(value,Real) or not math.isfinite(float(value)):
                raise ValueError('Invalid reranker score')
            scores[row['index']]=float(value)
        return scores


def build_reranker(settings, *, operation_id=None):
    if not settings.rag_reranker_enabled:
        return None
    if settings.rag_reranker_provider == 'api':
        return APIReranker(settings, operation_id)
    return LocalCrossEncoderReranker(settings.rag_reranker_model_path, timeout=settings.rag_reranker_timeout)


class LocalCrossEncoderReranker:
    def __init__(self, model_path: str, *, timeout: float = 10):
        self.model_path = Path(model_path).resolve()
        self.timeout = timeout

    def score(self, query, documents):
        if not self.model_path.is_dir():
            raise RuntimeError("Local reranker weights unavailable")
        env = os.environ.copy()
        for key in (
            "AGENT_API_KEY",
            "RAG_EMBEDDING_API_KEY",
            "OPENAI_API_KEY",
            "HF_TOKEN",
            "HUGGING_FACE_HUB_TOKEN",
        ):
            env.pop(key, None)
        env.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", OMP_NUM_THREADS="1")
        worker = Path(__file__).with_name("reranker_worker.py")
        result = subprocess.run(
            [sys.executable, str(worker)],
            input=json.dumps(
                {
                    "model_path": str(self.model_path),
                    "query": query,
                    "documents": documents,
                }
            ),
            encoding="utf-8",
            capture_output=True,
            env=env,
            timeout=self.timeout,
            check=False,
        )
        if result.returncode:
            raise RuntimeError("Local reranker failed")
        return json.loads(result.stdout)


def rerank_candidates(query, candidates, reranker):
    if not candidates:
        return []
    identifiers = [item.chunk_id for item in candidates]
    if not all(identifiers) or len(set(identifiers)) != len(identifiers):
        raise ValueError("Ambiguous reranker candidate IDs")
    values = reranker.score(query, [item.content for item in candidates])
    if (
        not isinstance(values, Sequence)
        or isinstance(values, (str, bytes, bytearray))
        or len(values) != len(candidates)
        or any(isinstance(value, bool) or not isinstance(value, Real) for value in values)
    ):
        raise ValueError("Invalid reranker score shape")
    scores = [float(value) for value in values]
    if not all(math.isfinite(value) for value in scores):
        raise ValueError("Invalid reranker score values")
    ranked = sorted(
        zip(candidates, scores), key=lambda pair: (-pair[1], pair[0].chunk_id)
    )
    return [
        item.model_copy(update={"reranker_score": score, "reranker_rank": rank})
        for rank, (item, score) in enumerate(ranked, 1)
    ]
