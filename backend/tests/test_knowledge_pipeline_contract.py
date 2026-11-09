"""Actual isolated API persistence and failure-path integration; no real model."""
import json
from pathlib import Path
from types import SimpleNamespace

from app.services.knowledge_retrieval_service import KnowledgeRetrievalService
from tests.test_knowledge_api import knowledge_api, api_build, private_governance


def test_smoke_api_persists_pipeline_without_faking_generation(knowledge_api):
    client, manager, base, _ = knowledge_api
    index = api_build(knowledge_api, "pipeline-api-smoke")
    response = client.post(f"/api/v1/knowledge/indexes/{index}/validate", json={"dataset": "document_smoke"})
    assert response.status_code == 200, response.text
    row = response.json(); pipeline = row["metrics"]["pipeline"]
    assert row["status"] == "PASS" and pipeline["status"] == "PARTIAL"
    assert pipeline["retrieval"]["recall_at_k"] == row["metrics"]["recall_at_k"]
    assert pipeline["answer_quality"]["status"] == "NOT RUN"
    assert pipeline["usage"]["cost"]["value"] is None
    persisted = client.get(f"/api/v1/knowledge/bases/{base.id}/evaluations").json()
    assert persisted[0]["metrics"]["pipeline"] == pipeline
    assert base.active_index_id is None  # evaluation does not publish


def test_fixed_error_keeps_all_cases_in_pipeline_and_original_error(knowledge_api, monkeypatch):
    client, manager, base, actors = knowledge_api
    index = api_build(knowledge_api, "pipeline-api-failure")
    value = manager.index(actors["admin"], index)
    path = Path(__file__).parent / "fixtures/stage3_rag_holdout.json"
    labels = json.loads(path.read_text(encoding="utf8"))
    chunks = [SimpleNamespace(source=src, section=section, chunk_id=f"synthetic-{n}-{i}")
              for n, row in enumerate(labels) for i, (src, section) in enumerate(row["expected"])]
    def fail(*args, **kwargs):
        raise TimeoutError("Synthetic injected retrieval failure")
    service = KnowledgeRetrievalService(manager.session, manager.root, offline=True)
    monkeypatch.setattr(service, "prepare", lambda *a, **kw: (SimpleNamespace(search=fail), value, chunks))
    result = service.evaluate(actors["admin"], index, "fixed", "bm25")
    assert result.status == "ERROR"
    pipeline = result.metrics["pipeline"]
    assert pipeline["reliability"]["queries"] == len(labels)
    assert pipeline["reliability"]["error"] == 1
    assert pipeline["reliability"]["missing"] == len(labels) - 1
    assert result.cases[0]["error_type"] == "TimeoutError"
    assert pipeline["refusal"]["correct_refusals"] == 0
    assert pipeline["performance"]["latency_ms"]["measured"] == 0
    assert pipeline["performance"]["latency_source"] == "evaluation.cases[].latency_ms"
    assert result.cases[0]["latency_ms"] >= 0  # real timing is retained outside stable metrics
