"""Quality counterexamples; no models, real databases or policy relabelling."""
from dataclasses import replace

import pytest

from app.agent.task_plan import Intent, route_intent
from app.rag.citation_guard import validate_chunk_citations
from app.rag.answerability import EvidenceSpan, Status, assess
from tests.test_rag_answerability import supported


@pytest.mark.parametrize('query',['查看调度方案详情','查看派车方案详情'])
def test_nested_detail_is_single_dispatch_intent(query):
    route,_,tools=route_intent(query)
    assert route is Intent.DISPATCH
    assert 'get_dispatch_plan_detail' in tools


def test_real_multi_intent_is_not_collapsed_or_given_writes():
    route,_,tools=route_intent('查看调度方案详情和运输任务')
    assert route is Intent.COMPOSITE and 'list_transport_tasks' in tools
    assert 'cancel_dispatch_plan' not in tools


def test_transport_validation_remains_read_only():
    route,_,tools=route_intent('查看运输任务')
    assert route is Intent.TRANSPORT and 'validate_dispatch_plan' in tools
    assert not {'cancel_dispatch_plan','move_delivery_demand'} & tools


@pytest.mark.parametrize('token',['bogus','1234','deadbeef!', 'a'*65])
def test_malformed_explicit_citation_does_not_evade_guard(token):
    with pytest.raises(ValueError):validate_chunk_citations(f'[Chunk ID: {token}]',{'a'*64})


def test_known_citation_and_unknown_or_ambiguous_ids():
    valid='a'*64
    assert validate_chunk_citations(f'规则[{valid}]', {valid})=={valid:valid}
    with pytest.raises(ValueError):validate_chunk_citations('[deadbeef]',{valid})
    with pytest.raises(ValueError):validate_chunk_citations('[aaaaaaaa]',{valid,'a'*63+'b'})


@pytest.mark.parametrize('field',['document_version','source_text'])
def test_conflicting_chunk_identity_fails_closed(field):
    value=supported();span=value.spans[0]
    changed=replace(span,**{field: 'other-version' if field=='document_version' else span.source_text+'不同规则'})
    result=assess(replace(value,spans=(span,changed)))
    assert result.status is Status.CONFLICT and not result.may_answer


def test_distinct_source_versions_are_not_globally_forbidden():
    value=supported();span=value.spans[0]
    other=EvidenceSpan('different-document-v2','other',span.source_text,span.start,span.end,span.supports)
    assert assess(replace(value,candidates=2,spans=(span,other))).may_answer
