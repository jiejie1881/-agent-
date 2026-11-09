"""LS9 explicit, default-off test path; LS8 extractive contract is unchanged."""
import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.rag.answer_contract import (IsolatedAnswerContract, BusinessRequest, snapshot, canonical)
from app.rag.semantic_judge import SemanticJudgePipeline, EvidenceState
from app.agent.model_types import AgentModelMessage, AgentMessageRole, AgentModelResponse


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class Citation(StrictModel):
    chunk_id: str
    document_id: str
    document_version: str
    quote: str = Field(min_length=1, max_length=16000)


class Claim(StrictModel):
    text: str = Field(min_length=1, max_length=16000)
    citation_index: int = Field(ge=0, strict=True)


class EvidenceRef(StrictModel):
    chunk_id: str
    document_id: str
    document_version: str
    body_sha256: str = Field(pattern='^[a-f0-9]{64}$')


class AnswerEnvelope(StrictModel):
    response_version: Literal['ls9-answer-v1']
    status: Literal['ANSWER', 'REFUSED', 'NEEDS_REVIEW']
    answer: str = Field(max_length=64000)
    claims: list[Claim] = Field(max_length=16)
    citations: list[Citation] = Field(max_length=16)
    refusal_reason: str | None = Field(max_length=200)
    evidence_refs: list[EvidenceRef] = Field(max_length=16)


class OutputContractError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('Duplicate JSON key')
        value[key] = item
    return value


def validate_answer(content, context, proof):
    try:
        raw = json.loads(content, object_pairs_hook=unique_object)
        envelope = AnswerEnvelope.model_validate(raw)
    except (ValueError, TypeError, ValidationError):
        raise OutputContractError('SCHEMA_INVALID') from None
    if envelope.status != 'ANSWER':
        raise OutputContractError('MODEL_REFUSAL_WITH_SUPPORT')
    if envelope.refusal_reason is not None:
        raise OutputContractError('SCHEMA_INVALID')
    if not envelope.claims or not envelope.citations:
        raise OutputContractError('CITATION_MISSING')
    if (len(envelope.claims) != len(envelope.citations) or
            {c.citation_index for c in envelope.claims} != set(range(len(envelope.citations)))):
        raise OutputContractError('CLAIM_SUPPORT_INVALID')
    if envelope.answer != '\n'.join(claim.text for claim in envelope.claims):
        raise OutputContractError('UNSUPPORTED_ANSWER_TEXT')
    chunks = {c.chunk_id: c for c in context.chunks}
    expected_refs = []
    for claim in envelope.claims:
        citation = envelope.citations[claim.citation_index]
        if claim.text != citation.quote:
            raise OutputContractError('CLAIM_SUPPORT_INVALID')
        chunk = chunks.get(citation.chunk_id)
        if chunk is None or (chunk.document_id, chunk.version) != (citation.document_id, citation.document_version):
            raise OutputContractError('CITATION_BINDING_INVALID')
        expected_refs.append(EvidenceRef(chunk_id=chunk.chunk_id, document_id=chunk.document_id,
            document_version=chunk.version, body_sha256=hashlib.sha256(chunk.text.encode()).hexdigest()))
    if (len({r.chunk_id for r in envelope.evidence_refs}) != len(envelope.evidence_refs) or
            {r.model_dump_json() for r in envelope.evidence_refs} != {r.model_dump_json() for r in expected_refs}):
        raise OutputContractError('EVIDENCE_REFS_INVALID')
    try:
        text = IsolatedAnswerContract.render(canonical(dict(citations=[dict(chunk_id=c.chunk_id, quote=c.quote)
            for c in envelope.citations])), proof.assessment.spans, proof.assessment.required_claims)
    except (TypeError, ValueError):
        raise OutputContractError('CLAIM_SUPPORT_INVALID') from None
    return text, envelope


def response_example(context, proof):
    """Server-approved extractive schema example, not a generated free answer."""
    citations, refs = [], []
    by_id = {c.chunk_id: c for c in context.chunks}
    for span in proof.assessment.spans:
        chunk = by_id[span.chunk_id]
        citations.append(dict(chunk_id=chunk.chunk_id, document_id=chunk.document_id,
            document_version=chunk.version, quote=span.source_text[span.start:span.end]))
        refs.append(dict(chunk_id=chunk.chunk_id, document_id=chunk.document_id, document_version=chunk.version,
                         body_sha256=hashlib.sha256(chunk.text.encode()).hexdigest()))
    refs = list({r['chunk_id']:r for r in refs}.values())
    return dict(response_version='ls9-answer-v1', status='ANSWER',
        answer='\n'.join(c['quote'] for c in citations),
        claims=[dict(text=c['quote'], citation_index=i) for i,c in enumerate(citations)],
        citations=citations, refusal_reason=None, evidence_refs=refs)


class IsolatedSemanticContract(IsolatedAnswerContract):
    POLICY = 'ls9-semantic-v1'

    def __init__(self, pipeline, *, business_resolver=None, repair_attempts=1):
        if type(pipeline) is not SemanticJudgePipeline:
            raise TypeError('Explicit server judge pipeline required')
        if type(repair_attempts) is not int or repair_attempts not in (0, 1):
            raise ValueError('At most one fixed-context repair')
        super().__init__(business_resolver or (lambda _: None))
        self.pipeline, self.repair_attempts = pipeline, repair_attempts

    def validate_installation(self, checkpoint_path):
        from app.core.config import get_settings
        super().validate_installation(checkpoint_path)
        if get_settings().rag_semantic_gate_mode != 'isolated':
            raise ValueError('LS9 default off; isolated test flag required')

    def output(self, workflow, state, status, context, *, text=None, result=None, attempts=(), envelope=None):
        if status in {'JUDGE_ERROR', 'BINDING_ERROR', 'MODEL_ERROR', 'OUTPUT_ERROR', 'POLICY_DISABLED'}:
            text = '回答校验暂未完成，请重试或交由人工核查；本次不是知识库无答案结论。'
        update = workflow.contract_result(state, status, context.sha256, text)
        update['answerability']['policy'] = self.POLICY
        update['semantic_decision'] = dict(policy=self.POLICY, context_sha256=context.sha256,
            **(result.audit() if result else dict(outcome=status, evidence_state='UNKNOWN', traces=[])),
            output_status=status, attempts=list(attempts))
        # Clear prior accepted payload on replay/error; never leave a stale
        # ANSWER envelope beside a new failure/refusal decision.
        update['answer_response'] = envelope.model_dump() if envelope is not None else {}
        return update

    async def answer(self, workflow, state):
        from app.core.config import get_settings
        context = snapshot(state)
        if get_settings().rag_semantic_gate_mode != 'isolated':
            return self.output(workflow, state, 'POLICY_DISABLED', context)
        # Resolve LIVE facts only through the existing closed read-tool route.
        try:
            request = self.resolve(context)
        except Exception:
            return self.output(workflow, state, 'JUDGE_ERROR', context)
        if request is not None:
            if type(request) is not BusinessRequest or request.context_sha256 != context.sha256:
                return self.output(workflow, state, 'BINDING_ERROR', context)
            update = await workflow.contracted_answer(state, IsolatedAnswerContract(lambda _: request))
            update['answerability']['policy'] = self.POLICY
            update['answer_response'] = {}
            update['semantic_decision'] = dict(policy=self.POLICY, context_sha256=context.sha256,
                outcome='AUTHORIZED_BUSINESS_ROUTE', evidence_state='UNKNOWN', traces=[],
                output_status=update['answerability']['status'])
            return update
        if not state.get('read_results'):
            return None  # tool selection still allowed; direct answer is not
        result = await self.pipeline.evaluate(context)
        # Judge await is another authorization/version boundary.
        workflow.recheck_knowledge_context(state)
        if snapshot(state).sha256 != context.sha256:
            return self.output(workflow, state, 'BINDING_ERROR', context, result=result)
        if result.outcome != 'DECIDED':
            return self.output(workflow, state, result.outcome, context, result=result)
        if result.state is not EvidenceState.SUPPORTED:
            return self.output(workflow, state, result.state.value, context, result=result)
        proof = result.proof
        example = response_example(context, proof)
        messages = [AgentModelMessage.model_validate(m) for m in state['messages']]
        messages.append(AgentModelMessage(role=AgentMessageRole.SYSTEM, content=
            '仅使用已核验完整证据片段返回以下结构，不增删限定条件。示例：' + canonical(example)))
        attempts = []
        for attempt in range(self.repair_attempts + 1):
            if get_settings().rag_semantic_gate_mode != 'isolated':
                return self.output(workflow, state, 'POLICY_DISABLED', context, result=result, attempts=attempts)
            try:
                response = await workflow.service.model_client.chat(messages, [])
            except Exception as error:
                attempts.append(dict(attempt=attempt, outcome='MODEL_ERROR', error_type=type(error).__name__))
                return self.output(workflow, state, 'MODEL_ERROR', context, result=result, attempts=attempts)
            workflow.recheck_knowledge_context(state)
            if get_settings().rag_semantic_gate_mode != 'isolated':
                return self.output(workflow, state, 'POLICY_DISABLED', context, result=result, attempts=attempts)
            if snapshot(state).sha256 != context.sha256:
                return self.output(workflow, state, 'BINDING_ERROR', context, result=result, attempts=attempts)
            if type(response) is not AgentModelResponse:
                attempts.append(dict(attempt=attempt, outcome='MODEL_ERROR', error_type='InvalidResponseType'))
                return self.output(workflow, state, 'MODEL_ERROR', context, result=result, attempts=attempts)
            try:
                if response.has_tool_calls:
                    raise OutputContractError('UNEXPECTED_TOOL_CALL')
                text, envelope = validate_answer(response.content, context, proof)
                attempts.append(dict(attempt=attempt, outcome='VALID'))
                return self.output(workflow, state, 'ANSWERABLE', context, text=text, result=result,
                                   attempts=attempts, envelope=envelope)
            except OutputContractError as error:
                attempts.append(dict(attempt=attempt, outcome=error.code))
                # No query rewrite, candidate expansion, new proof or tool call.
                messages.append(AgentModelMessage(role=AgentMessageRole.SYSTEM, content=
                    '上次输出未通过服务端校验：' + error.code + '。仅修复输出结构和引用；证据范围不变。'))
        return self.output(workflow, state, 'OUTPUT_ERROR', context, result=result, attempts=attempts)
