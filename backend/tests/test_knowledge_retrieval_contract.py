import hashlib

import pytest

from app.agent.knowledge_tools import SearchKnowledgeBaseTool
from app.agent.schemas.tool import SearchKnowledgeBaseArgs
from app.agent.tool_execution import AgentToolContext
from app.core.config import Settings, get_settings
from app.domain.exceptions import BusinessError
from app.rag.governed import GovernedRagFacade
from app.schemas.knowledge import KnowledgeQueryInput
from app.services.knowledge_job_service import KnowledgeJobService
from tests.test_knowledge_api import knowledge_api as _api
from tests.test_knowledge_management import governance as _governance


@pytest.fixture(name='governance')
def private_governance(session,tmp_path):
    return _governance.__wrapped__(session,tmp_path)


@pytest.fixture(name='knowledge_api')
def private_api(client,governance,monkeypatch):
    return _api.__wrapped__(client,governance,monkeypatch)


def typed_build(context):
    client,manager,base,actors=context
    manager.upload(actors['admin'],base.id,'dispatch_rules.md','# 线路\n仅使用线路白名单内车辆。'.encode())
    manager.upload(actors['admin'],base.id,'cold_chain_rules.md','# 温控\n系统不自动进行温控匹配。'.encode())
    manager.upload(actors['admin'],base.id,'notes.txt','# literal heading\n合成文本保留井号，不做Markdown章节解析。'.encode())
    jobs=KnowledgeJobService(manager.session,manager.root,offline=True)
    job=jobs.create(actors['admin'],base.id,'contract-new-index'); jobs.run(actors['admin'],job.id)
    assert job.status=='SUCCEEDED'
    jobs.validate(actors['admin'],job.result_index_id)
    manager.publish(actors['admin'],job.result_index_id,None,base.revision,True)
    return job.result_index_id


@pytest.mark.parametrize('explicit',[False,True])
def test_actual_nondefault_configuration_and_agent_lab_defaults(knowledge_api,monkeypatch,explicit):
    import asyncio
    from app.api.v1.endpoints.knowledge import retrieval
    client,manager,base,actors=knowledge_api
    index_id=typed_build(knowledge_api)
    config=get_settings()
    for key,value in dict(rag_default_top_k=2,rag_vector_candidates=5,rag_bm25_candidates=7,rag_rrf_k=13,rag_retrieval_mode='bm25').items():
        monkeypatch.setattr(config,key,value)
    service=GovernedRagFacade(manager.session,config)
    rag,value,_=service.prepare(actors['admin'],base.id,'bm25')
    assert (rag.default_top_k,rag.vector_candidates,rag.bm25_candidates,rag.rrf_k)==(2,5,7,13)
    from app.services.knowledge_retrieval_service import KnowledgeRetrievalService
    direct=KnowledgeRetrievalService(manager.session,manager.root,offline=True)
    direct_rag,_,_=direct.prepare(actors['admin'],base.id,direct.default_strategy)
    assert (direct_rag.default_top_k,direct_rag.vector_candidates,direct_rag.bm25_candidates,direct_rag.rrf_k)==(2,5,7,13)
    before=hashlib.sha256(manager.path(value.manifest_key).read_bytes()).hexdigest()
    query={'base_id':base.id,'query':'线路白名单'}
    arguments=dict(query='线路白名单',knowledge_base_id=base.id)
    if explicit:
        query.update(strategy='bm25',top_k=1);arguments['top_k']=1
    data=client.post('/api/v1/knowledge/retrieval/preview',json=query)
    assert data.status_code==200,data.text
    tool=SearchKnowledgeBaseTool(service)
    expected=asyncio.run(tool.execute(SearchKnowledgeBaseArgs(**arguments),AgentToolContext(current_user=actors['admin'])))
    assert data.json()['results']==expected.data['results']
    assert data.json()['stats']['returned']<= (1 if explicit else 2)
    assert retrieval(manager.session).default_strategy=='bm25'
    assert hashlib.sha256(manager.path(value.manifest_key).read_bytes()).hexdigest()==before
    assert index_id==base.active_index_id


def test_types_match_metadata_filters_and_txt_parser(knowledge_api):
    client,manager,base,actors=knowledge_api
    index_id=typed_build(knowledge_api)
    jobs=KnowledgeJobService(manager.session,manager.root,offline=True)
    _,chunks,_=jobs.checked_index(manager.index(actors['admin'],index_id))
    assert {c.document_type for c in chunks}=={'dispatch_rule','cold_chain','system_manual'}
    assert next(c for c in chunks if c.source=='notes.txt').section=='正文'
    for kind in ['dispatch_rule','cold_chain','system_manual']:
        value=client.post('/api/v1/knowledge/retrieval/preview',json={'base_id':base.id,'query':'线路温控合成文本','strategy':'vector','document_type':kind})
        assert value.status_code==200,value.text
        assert value.json()['results'] and all(c['document_type']==kind for c in value.json()['results'])


def test_unconfigured_reranking_is_explicitly_rejected_without_loading_model(knowledge_api,monkeypatch):
    client,_,base,_=knowledge_api
    typed_build(knowledge_api)
    monkeypatch.setattr(get_settings(),'rag_reranker_enabled',True)
    monkeypatch.setattr(get_settings(),'rag_reranker_model_path','synthetic-unavailable-not-loaded')
    result=client.post('/api/v1/knowledge/retrieval/preview',json={'base_id':base.id,'query':'线路'})
    assert result.status_code==503,result.text


def test_omitted_fields_and_invalid_settings_are_explicit():
    data=KnowledgeQueryInput(base_id=1,query='synthetic')
    assert data.strategy is None and data.top_k is None and data.document_type is None
    for key,value in [('rag_rrf_k',0),('rag_vector_candidates',0),('rag_default_top_k',11)]:
        with pytest.raises(ValueError): Settings(_env_file=None,**{key:value})


def test_missing_or_nonoffline_storage_remains_fail_closed(governance):
    manager,base,actors=governance
    config=Settings(_env_file=None,app_environment='test',rag_governance_enabled=True,rag_governance_offline_enabled=False)
    with pytest.raises(BusinessError):
        GovernedRagFacade(manager.session,config).search_for_actor(actors['viewer'],'线路',base_id=base.id)


def test_actual_fixed_api_keeps_ranking_and_refusal_gates_separate(knowledge_api):
    from pathlib import Path
    client,manager,base,actors=knowledge_api
    for path in sorted((Path(__file__).resolve().parents[1]/'knowledge_base').glob('*.md')):
        manager.upload(actors['admin'],base.id,path.name,path.read_bytes())
    jobs=KnowledgeJobService(manager.session,manager.root,offline=True)
    job=jobs.create(actors['admin'],base.id,'separate-fixed-gates');jobs.run(actors['admin'],job.id)
    result=client.post(f'/api/v1/knowledge/indexes/{job.result_index_id}/validate',json={'dataset':'fixed','strategy':'bm25'})
    assert result.status_code==200,result.text
    value=result.json()
    assert value['status']=='PASS'  # Historical ranking status is preserved.
    gates=value['metrics']['acceptance_gates']
    assert gates['retrieval']=='PASS' and gates['retrieval_abstention']=='FAIL'
    assert gates['semantic_answerability']==gates['final_generation']==gates['real_reranker']=='BLOCKED'
    assert gates['overall']=='PARTIAL' and base.active_index_id is None
