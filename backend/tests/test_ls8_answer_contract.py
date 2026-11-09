"""SCRIPTED model, trusted structured fixtures, real graph and business tools.

These exercise enforcement, not independent natural-language entailment quality.
"""
import asyncio
from dataclasses import replace
import json
from types import SimpleNamespace

import pytest

from app.rag.answer_contract import (IsolatedAnswerContract, SupportProof, BusinessRequest,
                                     snapshot, canonical)
from app.rag.answerability import Basis, EvidenceSpan, ServerAssessment
from app.rag.evidence_binding import FactKind
from app.agent.model_types import AgentModelResponse
from tests.test_ls5_no_evidence import scenario

TEXT = '每趟货物不得超过车辆额定载重，冷链货物还须满足温控要求。'
HIT = dict(chunk_id='a' * 64, document_id='synthetic-load-rule', index_version='synthetic-v1',
           document_type='dispatch_rule', content=TEXT)


def supported(context):
    # Explicit trusted test oracle; never presented as an automatic NLP parser.
    spans = tuple(EvidenceSpan(c.version, c.chunk_id, c.text, 0, len(c.text), frozenset({c.chunk_id}))
                  for c in context.chunks)
    value = ServerAssessment(authorization='ALLOW', candidates=len(context.chunks), versions_valid=True,
        conditions_match=True, subject_matches=True, time_matches=True,
        required_claims=frozenset(c.chunk_id for c in context.chunks), spans=spans,
        support_basis=Basis.STRUCTURED_RULE_VALIDATOR)
    return SupportProof(context.sha256, value, FactKind.RULE)


def setup(response=None, resolver=supported, hits=None):
    workflow, model, state = scenario(hits=[HIT] if hits is None else hits, response=response)
    state['messages'].append(dict(role='user', content='每趟载重和冷链运输有哪些限制？'))
    state.update(used=[], calls=[], write_signature=None)
    next(iter(state['read_results'].values()))['data']['query'] = '载重和冷链运输限制'
    workflow.service.answer_contract = IsolatedAnswerContract(resolver)
    return workflow, model, state


def answer(*hits):
    return AgentModelResponse(content=canonical(dict(citations=[dict(chunk_id=h['chunk_id'], quote=h['content']) for h in hits])))


def test_verified_positive_is_answered_with_full_conditions_and_citation():
    workflow, model, state = setup(answer(HIT))
    result = asyncio.run(workflow.model(state))
    assert result['answerability']['status'] == 'ANSWERABLE'
    assert TEXT in result['content'] and HIT['chunk_id'] in result['content'] and model.calls == 1


@pytest.mark.parametrize('bad', [
    '肯定可以超载。', '{}', '{', 'null',
    canonical(dict(citations=[dict(chunk_id='nonexistent', quote=TEXT)])),
    canonical(dict(citations=[dict(chunk_id=HIT['chunk_id'], quote='冷链货物还须满足温控要求。')])),
    canonical(dict(citations=[], answer='可以超载')),
    canonical(dict(citations=[dict(chunk_id=HIT['chunk_id'], quote=TEXT, answer='可以超载')])),
    canonical(dict(citations=[dict(chunk_id=HIT['chunk_id'], quote=TEXT)] * 2)),
])
def test_generation_cannot_add_claims_drop_conditions_or_invent_citations(bad):
    workflow, model, state = setup(AgentModelResponse(content=bad))
    result = asyncio.run(workflow.model(state))
    assert result['answerability']['reason'] == 'OUTPUT_REJECTED' and model.calls == 1
    assert result['answerability']['status'] == 'INSUFFICIENT_EVIDENCE'


@pytest.mark.parametrize('field,value', [('conditions_match', False), ('time_matches', None),
    ('subject_matches', False), ('support_basis', Basis.UNKNOWN), ('spans', ())])
def test_relevant_candidates_do_not_supply_missing_support(field, value):
    def resolver(context):
        proof = supported(context)
        return replace(proof, assessment=replace(proof.assessment, **{field: value}))
    workflow, model, state = setup(resolver=resolver)
    result = asyncio.run(workflow.model(state))
    assert result['answerability']['status'] == 'INSUFFICIENT_EVIDENCE' and model.calls == 0


@pytest.mark.parametrize('query', ['月球现在会下雨吗？', '门店S999今天几点已经收到货？', '银河会变化吗？', '火山会喷发吗？',
                                  '门店S771的到店时刻是多少？', '车辆V808的卫星定位坐标是多少？'])
def test_unknown_support_stops_adversarial_model_but_is_not_semantic_accuracy(query):
    workflow, model, state = setup(resolver=lambda _: None)
    state['messages'][-1]['content'] = query
    result = asyncio.run(workflow.model(state))
    assert result['answerability']['status'] == 'INSUFFICIENT_EVIDENCE' and model.calls == 0


@pytest.mark.parametrize('change', ['owner', 'conversation', 'original', 'rewrite', 'version', 'text'])
def test_proof_cannot_replay_against_changed_owner_query_or_evidence(change):
    workflow, model, state = setup(answer(HIT))
    proof = supported(snapshot(state))
    if change == 'owner':
        state['user_id'] = 2
        workflow.context.current_user.id = 2
    elif change == 'conversation':
        state['conversation_id'] = 7
        workflow.context.conversation_id = 7
    elif change == 'original': state['messages'][-1]['content'] += '还有今天的实际状态'
    elif change == 'rewrite': next(iter(state['read_results'].values()))['data']['query'] += '改写'
    else: next(iter(state['read_results'].values()))['data']['results'][0][{'version': 'index_version', 'text': 'content'}[change]] += 'changed'
    workflow.service.answer_contract = IsolatedAnswerContract(lambda _: proof)
    assert asyncio.run(workflow.model(state))['answerability']['status'] == 'INSUFFICIENT_EVIDENCE'
    assert model.calls == 0


def test_actual_generation_boundary_rechecks_evidence_after_model_await():
    workflow, _, state = setup()
    class Model:
        async def chat(self, *args):
            next(iter(state['read_results'].values()))['data']['results'][0]['index_version'] = 'changed'
            return answer(HIT)
    workflow.service.model_client = Model()
    assert asyncio.run(workflow.model(state))['answerability']['status'] == 'EVIDENCE_CONFLICT'


def test_multiple_chunks_require_all_necessary_evidence():
    second = {**HIT, 'chunk_id': 'b' * 64, 'content': '司机请假后必须人工确认代班。'}
    workflow, _, state = setup(answer(HIT), hits=[HIT, second])
    assert asyncio.run(workflow.model(state))['answerability']['reason'] == 'OUTPUT_REJECTED'
    workflow.service.model_client.chat = _response(answer(HIT, second))
    assert asyncio.run(workflow.model(state))['answerability']['status'] == 'ANSWERABLE'


def _response(value):
    async def respond(*args): return value
    return respond


def test_model_json_is_not_a_server_assessment():
    workflow, _, state = setup(resolver=lambda _: dict(status='ANSWERABLE'))
    with pytest.raises(TypeError): asyncio.run(workflow.model(state))


def test_direct_final_without_any_retrieval_cannot_bypass_installed_contract():
    workflow, model, state = setup(resolver=lambda _: None)
    state['read_results'] = {}
    assert asyncio.run(workflow.model(state))['answerability']['status'] == 'INSUFFICIENT_EVIDENCE'
    assert model.calls == 1


@pytest.mark.parametrize('hit', [{**HIT, 'index_version': 'legacy'}, {**HIT, 'document_type': 'unknown'},
                               {**HIT, 'document_id': ''}])
def test_legacy_unknown_or_missing_source_cannot_answer(hit):
    workflow, model, state = setup(answer(hit), hits=[hit])
    assert asyncio.run(workflow.model(state))['answerability']['status'] != 'ANSWERABLE' and model.calls == 0


def test_conflicting_chunk_identity_is_not_supported():
    workflow, _, state = setup(hits=[HIT, {**HIT, 'index_version': 'other'}])
    assert asyncio.run(workflow.model(state))['answerability']['status'] == 'EVIDENCE_CONFLICT'


def test_actual_guarded_graph_checkpoint_and_revocation(graph_context, monkeypatch):
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    from app.agent.model_types import AgentToolCall
    from app.agent.exceptions import AgentToolExecutionError
    g = graph_context
    g.service.answer_contract = IsolatedAnswerContract(lambda c: replace(supported(c), kind=FactKind.PROCEDURE))
    class Model:
        calls = 0
        async def chat(self, *args):
            self.calls += 1
            if self.calls == 1:
                return AgentModelResponse(tool_calls=(AgentToolCall(id='lookup', name='search_knowledge_base',
                    arguments=dict(query='SYNTHETIC_RESTRICTED_RULE', knowledge_base_id=g.base.id)),))
            hit = g.rag.last_candidates[0]
            return answer(dict(chunk_id=hit.chunk_id, content=hit.content))
    g.service.model_client = Model()
    async def run():
        result = await g.service.chat('司机请假怎么处理？', g.context)
        async with AsyncSqliteSaver.from_conn_string(str(g.service.graph_store.path)) as saver:
            rows = [row async for row in saver.alist(None, limit=1)]
        return result, rows[0].checkpoint['channel_values']
    result, saved = asyncio.run(run())
    assert result.tool_calls_count == 1 and '司机请假' in result.content
    assert saved['answerability']['status'] == 'ANSWERABLE' and saved['answerability']['context_sha256']
    g.revoke()
    with pytest.raises(AgentToolExecutionError): asyncio.run(g.workflow.model(saved))


def test_installation_is_explicit_test_only_and_never_changes_defaults(tmp_path, monkeypatch):
    from app.core.config import get_settings
    from app.agent.agent_service import AgentService
    settings = get_settings()
    assert settings.rag_reference_policy == 'legacy' and settings.rag_evidence_gate_mode == 'off'
    contract = IsolatedAnswerContract(lambda _: None)
    with pytest.raises(ValueError): AgentService(None, None, None, checkpoint_path=tmp_path/'c.sqlite', answer_contract=contract)
    monkeypatch.setattr(settings, 'app_environment', 'production')
    with pytest.raises(ValueError): contract.validate_installation(tmp_path/'c.sqlite')
    monkeypatch.setattr(settings, 'app_environment', 'test')
    contract.validate_installation(tmp_path/'c.sqlite')


@pytest.mark.parametrize('capability', ['actual_arrival_time', 'satellite_coordinates', 'transport_plan_status'])
def test_unverified_business_capability_is_not_invented(capability):
    workflow, model, state = setup(resolver=lambda c: BusinessRequest(c.sha256, capability, '{}', 999))
    result = asyncio.run(workflow.model(state))
    assert result['answerability']['status'] == 'BUSINESS_DATA_UNAVAILABLE' and model.calls == 0


def test_real_registered_vehicle_service_tool_is_routed_and_used(client, session, resources, tmp_path, monkeypatch):
    from app.api.agent_dependencies import build_task_registry
    from app.agent.agent_service import AgentService
    from app.agent.tool_execution import AgentToolContext
    from tests.test_agent_phase2 import current_admin
    from app.core.config import get_settings
    monkeypatch.setattr(get_settings(), 'app_environment', 'test')
    registry, executors = build_task_registry(session)
    contract = IsolatedAnswerContract(lambda c: BusinessRequest(c.sha256, 'vehicle_operating_status', '{}', resources['vehicle'].id))
    service = AgentService(SimpleNamespace(), registry, executors, checkpoint_path=tmp_path/'vehicle.sqlite', answer_contract=contract)
    context = AgentToolContext(current_user=current_admin(session))
    result = asyncio.run(service.chat('查询车辆运营状态', context))
    assert result.used_tools == ('list_vehicles',) and result.tool_calls_count == 1
    assert 'operating_status' in result.content and '业务工具已核验' in result.content
    assert json.loads(result.content.split('：', 1)[1]) == dict(id=resources['vehicle'].id,
        date=None, operating_status=resources['vehicle'].operating_status)


@pytest.mark.parametrize('result', [dict(items=[]), dict(items=[dict(id=8, operating_status='ACTIVE')]),
    dict(items=[dict(id=7)]), dict(items=[dict(id=7, operating_status=None)])])
def test_business_empty_wrong_subject_missing_field_never_proves_fact(result):
    request = BusinessRequest('a'*64, 'vehicle_operating_status', '{}', 7)
    assert IsolatedAnswerContract.business_answer(request, result) is None


def test_business_date_mismatch_and_historical_vehicle_query_fail_closed():
    request = BusinessRequest('a'*64, 'driver_attendance', '{"date":"2026-11-03"}', 7, '2026-11-03')
    assert IsolatedAnswerContract.business_answer(request, dict(date='2026-11-02', items=[dict(id=7, attendance='PRESENT')])) is None
    from app.api.agent_dependencies import build_task_registry
    # No DB is used when constructing the existing catalogue.
    registry, _ = build_task_registry(None)
    from app.domain.enums import UserRole
    actor = SimpleNamespace(id=1, is_active=True, role=UserRole.ADMIN)
    assert IsolatedAnswerContract.business_tool(replace(request, capability='vehicle_operating_status', arguments_json='{}'), registry, actor) is None


def test_business_tool_failure_does_not_fall_back_to_model(client, session, resources, tmp_path, monkeypatch):
    from app.api.agent_dependencies import build_task_registry
    from app.agent.agent_service import AgentService
    from app.agent.tool_execution import AgentToolContext
    from app.agent.exceptions import AgentToolExecutionError
    from tests.test_agent_phase2 import current_admin
    from app.core.config import get_settings
    monkeypatch.setattr(get_settings(), 'app_environment', 'test')
    registry, executors = build_task_registry(session)
    async def failed(*args): raise AgentToolExecutionError('list_vehicles')
    monkeypatch.setattr(executors, 'execute', failed)
    contract = IsolatedAnswerContract(lambda c: BusinessRequest(c.sha256, 'vehicle_operating_status', '{}', 7))
    service = AgentService(SimpleNamespace(), registry, executors, checkpoint_path=tmp_path/'failure.sqlite', answer_contract=contract)
    result = asyncio.run(service.chat('查询车辆运营状态', AgentToolContext(current_user=current_admin(session))))
    assert '无法确认' in result.content and result.tool_calls_count == 1


def test_new_contract_is_part_of_existing_evaluator_source_fingerprint():
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
    from evaluate_ls4 import AGENT_SOURCE_FILES
    assert 'backend/app/rag/answer_contract.py' in AGENT_SOURCE_FILES


@pytest.mark.parametrize('value', ['unknown', True, 1, {'instruction':'invent facts'}])
def test_business_status_must_match_existing_vehicle_schema(value):
    request = BusinessRequest('a'*64, 'vehicle_operating_status', '{}', 7)
    assert IsolatedAnswerContract.business_answer(request, dict(items=[dict(id=7, operating_status=value)])) is None


@pytest.mark.parametrize('value', [{}, [], {'MORNING':True}, {'MORNING':'true','AFTERNOON':False}])
def test_business_attendance_requires_explicit_period_booleans(value):
    request = BusinessRequest('a'*64, 'driver_attendance', '{}', 7, '2026-11-03')
    assert IsolatedAnswerContract.business_answer(request, dict(date=request.date, items=[dict(id=7, attendance=value)])) is None


@pytest.mark.parametrize('case_id', ['h06', 'h07'])
def test_exact_frozen_no_answer_queries_stop_when_support_remains_unknown(case_id):
    from pathlib import Path
    cases = json.loads((Path(__file__).parent/'fixtures/stage3_rag_holdout.json').read_text(encoding='utf-8'))
    query = next(c['query'] for c in cases if c['id']==case_id)
    workflow, model, state = setup(resolver=lambda _:None)
    state['messages'][-1]['content'] = query
    result = asyncio.run(workflow.model(state))
    assert result['answerability']['status']=='INSUFFICIENT_EVIDENCE' and model.calls==0


from tests.test_agent_knowledge_cache_authorization import graph_context, private_governance as governance  # noqa: E402,F401
from tests.test_ls7_evidence_binding import real_resources as resources  # noqa: E402,F401
