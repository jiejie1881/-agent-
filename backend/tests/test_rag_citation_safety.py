"""Explicit provenance checks; no claim of answer correctness or NLP support."""
import asyncio

import pytest

from app.agent.exceptions import AgentModelResponseError
from app.agent.model_types import AgentMessageRole, AgentModelMessage, AgentModelResponse
from app.rag.citation_guard import validate_chunk_citations
from tests.test_agent_knowledge_cache_authorization import graph_context, private_governance  # noqa: F401


def test_valid_full_and_unique_abbreviated_citations_resolve_without_rewriting():
    chunk = 'a'*64
    text = f'规则 [{chunk}]；见 [aaaaaaaa...] 和 Chunk ID: {chunk}'
    assert validate_chunk_citations(text,[chunk]) == {chunk:chunk,'aaaaaaaa':chunk}


@pytest.mark.parametrize('text,ids', [
    ('依据 ['+'b'*64+']',['a'*64]),
    ('依据 [aaaaaaaa...]',['a'*64,'a'*8+'b'*56]),
    ('Chunk ID: '+'b'*64,['a'*64]),
    ('['+'a'*64+']',[]),
    ('['+'a'*65+']',['a'*64]),
])
def test_unknown_or_ambiguous_citations_fail_closed(text, ids):
    with pytest.raises(ValueError):
        validate_chunk_citations(text,ids)


def test_plain_business_ids_are_not_interpreted_as_chunk_citations():
    assert validate_chunk_citations('订单摘要 '+ 'b'*64,[]) == {}


@pytest.mark.parametrize('valid', [True,False])
def test_actual_langgraph_model_node_validates_citations_after_authorized_tool_result(graph_context,valid):
    g = graph_context
    state = g.execute(g.state)
    actual = next(iter(state['read_results'].values()))['data']['results'][0]['chunk_id']
    response_id = actual if valid else ('0'*64 if actual != '0'*64 else '1'*64)
    class Model:
        async def chat(self,*args):
            return AgentModelResponse(content=f'引用 [{response_id}]')
    g.service.model_client = Model()
    state['messages'].insert(0,AgentModelMessage(role=AgentMessageRole.SYSTEM,content='synthetic').model_dump(mode='json'))
    if valid:
        assert response_id in asyncio.run(g.workflow.model(state))['content']
    else:
        with pytest.raises(AgentModelResponseError,match='引用'):
            asyncio.run(g.workflow.model(state))
