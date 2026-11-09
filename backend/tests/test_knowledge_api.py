"""Offline ASGI acceptance, not browser/MySQL/model acceptance."""
import pytest

from app.core.config import get_settings
from tests.test_knowledge_management import governance as _governance, upload_rule


@pytest.fixture(name="governance")
def private_governance(session, tmp_path):
    return _governance.__wrapped__(session, tmp_path)


@pytest.fixture
def knowledge_api(client, governance, monkeypatch):
    manager, base, actors = governance
    config = get_settings()
    monkeypatch.setattr(config, "app_environment", "test")
    monkeypatch.setattr(config, "rag_governance_enabled", True)
    monkeypatch.setattr(config, "rag_governance_offline_enabled", True)
    monkeypatch.setattr(config, "rag_governance_root", str(manager.root))
    monkeypatch.setattr(config, "rag_governance_default_base_id", base.id)
    return client, manager, base, actors


def token(client, name):
    response = client.post("/api/v1/auth/login", json={"username": "knowledge-" + name, "password": "SyntheticPass123!"})
    assert response.status_code == 200
    return {"Authorization": "Bearer " + response.json()["access_token"]}


def api_build(context, key="api-build-key-0001"):
    client, manager, base, actors = context
    upload_rule(manager, base, actors["admin"])
    job = client.post(f"/api/v1/knowledge/bases/{base.id}/jobs", json={"idempotency_key": key})
    assert job.status_code == 200, job.text
    result = client.post(f"/api/v1/knowledge/jobs/{job.json()['id']}/run")
    assert result.status_code == 200 and result.json()["status"] == "SUCCEEDED", result.text
    return result.json()["result_index_id"]


def api_publish(context, index_id):
    client, manager, base, _ = context
    assert client.post(f"/api/v1/knowledge/indexes/{index_id}/validate", json={"dataset": "document_smoke"}).json()["status"] == "PASS"
    manager.session.refresh(base)
    response = client.post(f"/api/v1/knowledge/indexes/{index_id}/publish", json={
        "expected_active_id": base.active_index_id, "expected_revision": base.revision, "confirmed": True})
    assert response.status_code == 200, response.text
    return response.json()


def test_offline_api_document_job_validation_publish_and_search(knowledge_api):
    client, manager, base, actors = knowledge_api
    created = client.post("/api/v1/knowledge/bases", json={"name": "独立合成库", "visibility": "ADMIN"})
    assert created.status_code == 200
    uploaded = client.post(f"/api/v1/knowledge/bases/{base.id}/documents",
        files={"file": ("规则.txt", "每次派车必须确认车辆出勤。".encode(), "text/plain")}, data={"source_label": "匿名合成"})
    assert uploaded.status_code == 200
    assert "storage_key" not in uploaded.json()
    index_id = api_build(knowledge_api)
    assert client.get(f"/api/v1/knowledge/indexes/{index_id}/diff").json()["publication_is_separate"]
    api_publish(knowledge_api, index_id)
    for mode in ["vector", "bm25", "hybrid"]:
        response = client.post("/api/v1/knowledge/retrieval/preview", json={"base_id": base.id, "query": "车辆出勤", "strategy": mode})
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["results"] and body["candidates"] and body["generation"] == "NOT RUN"
        assert body["results"][0]["document_id"].startswith(f"kb:{base.id}:doc:")
    assert client.get(f"/api/v1/knowledge/indexes/{index_id}/chunks").json()["chunks"]
    assert client.get(f"/api/v1/knowledge/bases/{base.id}/evaluations").json()
    assert client.get("/api/v1/knowledge/metrics").json()["actual_cost"] is None
    assert client.get("/api/v1/knowledge/audits").json()


@pytest.mark.parametrize("role", ["viewer", "dispatcher", "driver"])
def test_management_mutations_and_content_are_admin_only(knowledge_api, role):
    client, manager, base, actors = knowledge_api
    version = upload_rule(manager, base, actors["admin"])
    headers = token(client, role)
    response = client.post("/api/v1/knowledge/bases", json={"name": "拒绝"}, headers=headers)
    assert response.status_code == 403
    assert client.get(f"/api/v1/knowledge/documents/{version.document_id}/versions/{version.id}/content", headers=headers).status_code == 403
    assert client.get("/api/v1/knowledge/metrics", headers=headers).status_code == 403


def test_candidate_and_restricted_document_cannot_leak_to_reader(knowledge_api):
    client, manager, base, actors = knowledge_api
    index_id = api_build(knowledge_api)
    headers = token(client, "viewer")
    assert client.get(f"/api/v1/knowledge/indexes/{index_id}/chunks", headers=headers).status_code == 404
    assert client.post("/api/v1/knowledge/retrieval/preview", json={"base_id": base.id, "index_id": index_id, "query": "载重"}, headers=headers).status_code == 403
    api_publish(knowledge_api, index_id)
    doc = manager.documents(actors["admin"], base.id)[0]
    data = {"expected_revision": doc.revision, "visibility": "ADMIN", "read_roles": []}
    assert client.patch(f"/api/v1/knowledge/documents/{doc.id}/permissions", json=data).status_code == 200
    response = client.post("/api/v1/knowledge/retrieval/preview", json={"base_id": base.id, "query": "载重", "strategy": "hybrid"}, headers=headers)
    assert response.status_code == 200 and response.json()["results"] == [] and response.json()["candidates"] == []
    assert response.json()["evidence_status"] == "NO_EVIDENCE"
    assert client.get(f"/api/v1/knowledge/indexes/{index_id}/chunks", headers=headers).json()["chunks"] == []


def test_upload_limits_and_cross_document_version_access(knowledge_api):
    client, manager, base, actors = knowledge_api
    first = upload_rule(manager, base, actors["admin"])
    other = manager.upload(actors["admin"], base.id, "other.txt", b"synthetic second document")
    assert client.get(f"/api/v1/knowledge/documents/{first.document_id}/versions/{other.id}/content").status_code == 404
    assert client.post(f"/api/v1/knowledge/bases/{base.id}/documents", files={"file": ("../escape.md", b"synthetic")}).status_code == 422
    assert client.post(f"/api/v1/knowledge/bases/{base.id}/documents", files={"file": ("large.txt", b"x" * (5 * 1024 * 1024 + 1))}).status_code == 422
    assert client.post(f"/api/v1/knowledge/bases/{base.id}/documents", content=b"", headers={"Content-Length": str(6 * 1024 * 1024)}).status_code == 413


def test_fixed_evaluation_missing_labels_is_blocked_not_pass(knowledge_api):
    client, _, _, _ = knowledge_api
    index_id = api_build(knowledge_api)
    result = client.post(f"/api/v1/knowledge/indexes/{index_id}/validate", json={"dataset": "fixed", "strategy": "hybrid"})
    assert result.status_code == 200 and result.json()["status"] == "BLOCKED"
    assert result.json()["metrics"]["reason"] == "MISSING_LABEL_TARGETS"


def test_disabled_and_real_environment_gates(knowledge_api, monkeypatch):
    client, _, _, _ = knowledge_api
    monkeypatch.setattr(get_settings(), "rag_governance_enabled", False)
    assert client.get("/api/v1/knowledge/bases").status_code == 404
    monkeypatch.setattr(get_settings(), "rag_governance_enabled", True)
    monkeypatch.setattr(get_settings(), "rag_governance_offline_enabled", False)
    assert client.get("/api/v1/knowledge/bases").status_code == 503


def test_unauthenticated_knowledge_access_is_rejected(client):
    client.headers.pop("Authorization", None)
    assert client.get("/api/v1/knowledge/bases").status_code == 401


def test_fixed_evaluation_history_is_persisted_without_overwriting(knowledge_api):
    from pathlib import Path
    from app.services.knowledge_job_service import KnowledgeJobService
    client, manager, base, actors = knowledge_api
    corpus = Path(__file__).resolve().parents[1] / "knowledge_base"
    for path in sorted(corpus.glob("*.md")):
        manager.upload(actors["admin"], base.id, path.name, path.read_bytes(), source_label="project-rule-fixture")
    service = KnowledgeJobService(manager.session, manager.root, offline=True)
    job = service.create(actors["admin"], base.id, "complete-fixed-corpus")
    service.run(actors["admin"], job.id)
    assert job.status == "SUCCEEDED"
    results = []
    for mode in ("vector", "bm25", "hybrid", "bm25"):
        response = client.post(f"/api/v1/knowledge/indexes/{job.result_index_id}/validate", json={"dataset": "fixed", "strategy": mode})
        assert response.status_code == 200, response.text
        value = response.json()
        assert value["status"] in {"PASS", "FAIL"} and len(value["cases"]) == 12
        assert value["metrics"]["generation_quality"] == "NOT RUN"
        assert all("metrics" in row and "should_refuse" in row for row in value["cases"])
        results.append(value)
    assert results[1]["id"] != results[3]["id"] and results[1]["metrics"] == results[3]["metrics"]
    assert len(client.get(f"/api/v1/knowledge/bases/{base.id}/evaluations").json()) == 4
    assert base.active_index_id is None


def test_evaluation_error_preserves_failed_question_and_blocks_publication(knowledge_api, monkeypatch):
    from pathlib import Path
    from app.rag.rag_service import RagService
    client, manager, base, actors = knowledge_api
    for path in sorted((Path(__file__).resolve().parents[1] / "knowledge_base").glob("*.md")):
        manager.upload(actors["admin"], base.id, path.name, path.read_bytes())
    response = client.post(f"/api/v1/knowledge/bases/{base.id}/jobs", json={"idempotency_key": "evaluation-error-case"})
    job_id = response.json()["id"]
    index_id = client.post(f"/api/v1/knowledge/jobs/{job_id}/run").json()["result_index_id"]
    def fail(*args, **kwargs):
        raise TimeoutError("synthetic evaluation timeout")
    monkeypatch.setattr(RagService, "search", fail)
    result = client.post(f"/api/v1/knowledge/indexes/{index_id}/validate", json={"dataset": "fixed", "strategy": "bm25"})
    assert result.status_code == 200 and result.json()["status"] == "ERROR"
    assert result.json()["cases"][0]["error_type"] == "TimeoutError"
    assert len(client.get(f"/api/v1/knowledge/bases/{base.id}/evaluations").json()) == 1
    denied = client.post(f"/api/v1/knowledge/indexes/{index_id}/publish", json={
        "expected_active_id": None, "expected_revision": 0, "confirmed": True})
    assert denied.status_code == 409 and base.active_index_id is None


@pytest.mark.parametrize("with_evidence", [True, False])
def test_actual_agent_api_uses_governed_tool_with_mock_model(knowledge_api, monkeypatch, with_evidence):
    import json
    from app.agent.model_types import AgentModelResponse, AgentToolCall
    import app.api.agent_dependencies as dependencies
    client, manager, base, actors = knowledge_api
    index_id = api_build(knowledge_api)
    api_publish(knowledge_api, index_id)
    monkeypatch.setattr(get_settings(), "rag_retrieval_mode", "bm25")
    if not with_evidence:
        doc = manager.documents(actors["admin"], base.id)[0]
        client.patch(f"/api/v1/knowledge/documents/{doc.id}/permissions", json={"expected_revision": doc.revision, "visibility": "ADMIN"})
    headers = token(client, "viewer")
    expected = client.post("/api/v1/knowledge/retrieval/preview", headers=headers,
        json={"base_id": base.id, "query": "车辆出勤", "strategy": "bm25"}).json()

    class MockModel:
        def __init__(self):
            self.calls = 0

        async def chat(self, messages, tools):
            self.calls += 1
            if self.calls == 1:
                return AgentModelResponse(tool_calls=(AgentToolCall(id="governed-rag", name="search_knowledge_base",
                    arguments={"query": "车辆出勤", "knowledge_base_id": base.id}),))
            tool = next(m for m in messages if m.role.value == "tool")
            data = json.loads(tool.content)["data"]
            assert data["results"] == expected["results"]
            if not data["results"]:
                assert data["evidence_status"] == "NO_EVIDENCE"
                return AgentModelResponse(content="没有授权证据，无法确认。")
            return AgentModelResponse(content="合成规则要求确认出勤。来源：物流规则.md / 出勤。")

    monkeypatch.setattr(dependencies, "LangChainModelClient", MockModel)
    conversation = client.post("/api/v1/agent/conversations", headers=headers, json={})
    assert conversation.status_code in {200, 201}, conversation.text
    response = client.post(f"/api/v1/agent/conversations/{conversation.json()['id']}/messages", headers=headers,
        json={"message": "车辆出勤规则是什么？"})
    assert response.status_code == 200, response.text
    assert response.json()["used_tools"] == ["search_knowledge_base"]
    assert ("无法确认" in response.json()["message"]["content"]) is (not with_evidence)


def test_api_does_not_accept_paid_provider_or_arbitrary_dataset(knowledge_api):
    client, _, base, _ = knowledge_api
    assert client.post("/api/v1/knowledge/retrieval/preview", json={"base_id": base.id, "query": "x", "allow_paid_embedding": True}).status_code == 422
    index_id = api_build(knowledge_api)
    assert client.post(f"/api/v1/knowledge/indexes/{index_id}/validate", json={"dataset": "../../arbitrary.json"}).status_code == 422


def test_job_runtime_metadata_and_authorized_chunk_statistics(knowledge_api):
    client, manager, base, actors = knowledge_api
    upload_rule(manager, base, actors['admin'], text='# 合成规则\n签收后保留回单。🚚')
    queued = client.post(f'/api/v1/knowledge/bases/{base.id}/jobs', json={'idempotency_key': 'runtime-detail-contract'}).json()
    assert queued['started_at'] is queued['finished_at'] is None and queued['progress']['completed_steps'] == 0
    done = client.post(f"/api/v1/knowledge/jobs/{queued['id']}/run").json()
    assert done['status'] == 'SUCCEEDED' and done['started_at'] and done['finished_at']
    assert done['progress'] == {'unit': 'stages', 'current_step': 5, 'completed_steps': 5, 'total_steps': 5}
    assert done['timeline'][0]['action'] == 'RAG_JOB_STARTED' and done['timeline'][-1]['action'] == 'RAG_JOB_COMPLETED'
    assert client.get(f"/api/v1/knowledge/jobs/{done['id']}").json()['started_at'] == done['started_at']
    assert client.get(f'/api/v1/knowledge/bases/{base.id}/jobs').json()[0]['finished_at'] == done['finished_at']
    response = client.get(f"/api/v1/knowledge/indexes/{done['result_index_id']}/chunks").json()
    assert response['total_chunks'] == len(response['chunks']) and response['offset'] == 0
    assert response['page_characters'] == sum(len(c['content']) for c in response['chunks'])
    assert all(c['char_count'] == len(c['content']) for c in response['chunks'])
    assert client.get(f"/api/v1/knowledge/jobs/{done['id']}", headers=token(client, 'viewer')).status_code == 403
