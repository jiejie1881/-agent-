"""Versioned semantic-judge boundary. No automatic NLP or model client here.

Judges are trusted server adapters. A mock opinion verifies orchestration only;
it is never independent ground truth. Scores and candidate counts grant nothing.
"""
import asyncio
from dataclasses import dataclass, asdict
from enum import Enum
from time import perf_counter
from typing import Protocol

from app.rag.answer_contract import EvidenceContext, SupportProof, IsolatedAnswerContract


class EvidenceState(str, Enum):
    SUPPORTED = 'SUPPORTED'
    INSUFFICIENT = 'INSUFFICIENT'
    CONTRADICTORY = 'CONTRADICTORY'
    IRRELEVANT = 'IRRELEVANT'
    UNKNOWN = 'UNKNOWN'


@dataclass(frozen=True)
class JudgeOpinion:
    state: EvidenceState
    context_sha256: str
    judge_version: str
    reason_codes: tuple[str, ...]
    proof: SupportProof | None = None


class SemanticRelevanceJudge(Protocol):
    async def judge(self, context: EvidenceContext) -> JudgeOpinion: ...


class EvidenceSufficiencyJudge(Protocol):
    async def judge(self, context: EvidenceContext) -> JudgeOpinion: ...


class ContradictionJudge(Protocol):
    """SUPPORTED here means consistency checked, not merely 'no known conflict'."""
    async def judge(self, context: EvidenceContext) -> JudgeOpinion: ...


@dataclass(frozen=True)
class EvidenceDecisionTrace:
    stage: str
    version: str | None
    context_sha256: str
    state: str
    elapsed_ms: float
    error_type: str | None = None
    reason_codes: tuple[str, ...] = ()
    evidence_versions: tuple[tuple[str, str, str], ...] = ()


@dataclass(frozen=True)
class AnswerabilityResult:
    outcome: str  # DECIDED / JUDGE_ERROR / BINDING_ERROR
    state: EvidenceState
    proof: SupportProof | None
    trace: tuple[EvidenceDecisionTrace, ...]

    def audit(self):
        return dict(outcome=self.outcome, evidence_state=self.state.value,
                    traces=[asdict(row) for row in self.trace])


class SemanticJudgePipeline:
    def __init__(self, relevance: SemanticRelevanceJudge, sufficiency: EvidenceSufficiencyJudge,
                 contradiction: ContradictionJudge, *, timeout_seconds=2.0):
        if type(timeout_seconds) not in (int, float) or not 0 < timeout_seconds <= 30:
            raise ValueError('Bounded judge timeout required')
        self.judges = (('relevance', relevance), ('sufficiency', sufficiency), ('contradiction', contradiction))
        self.timeout_seconds = timeout_seconds

    async def evaluate(self, context):
        trace, opinions = [], []
        versions = tuple((c.document_id, c.version, c.chunk_id) for c in context.chunks)
        for stage, judge in self.judges:
            started = perf_counter()
            version = None
            try:
                opinion = await asyncio.wait_for(judge.judge(context), self.timeout_seconds)
                if (type(opinion) is not JudgeOpinion or type(opinion.state) is not EvidenceState or
                        type(opinion.judge_version) is not str or not opinion.judge_version or
                        len(opinion.judge_version) > 100 or type(opinion.reason_codes) is not tuple or
                        any(type(c) is not str or not c or len(c) > 100 for c in opinion.reason_codes)):
                    raise ValueError('Invalid server judge opinion')
                version = opinion.judge_version
                if opinion.context_sha256 != context.sha256:
                    raise ValueError('Foreign query/evidence judgment')
                if stage == 'sufficiency' and opinion.state is EvidenceState.SUPPORTED:
                    if type(opinion.proof) is not SupportProof:
                        raise ValueError('Positive judgment needs bound support proof')
                opinions.append(opinion)
                trace.append(EvidenceDecisionTrace(stage, version, context.sha256, opinion.state.value,
                    (perf_counter()-started)*1000, reason_codes=opinion.reason_codes, evidence_versions=versions))
            except Exception as error:
                # Exception text can contain document content/credentials. Type
                # only; cancellation is BaseException and is not swallowed.
                trace.append(EvidenceDecisionTrace(stage, version, context.sha256, 'JUDGE_ERROR',
                    (perf_counter()-started)*1000, type(error).__name__, evidence_versions=versions))
                return AnswerabilityResult('JUDGE_ERROR', EvidenceState.UNKNOWN, None, tuple(trace))
        states = {o.state for o in opinions}
        if EvidenceState.CONTRADICTORY in states:
            state = EvidenceState.CONTRADICTORY
        elif EvidenceState.UNKNOWN in states:
            state = EvidenceState.UNKNOWN
        elif EvidenceState.IRRELEVANT in states:
            state = EvidenceState.IRRELEVANT
        elif EvidenceState.INSUFFICIENT in states:
            state = EvidenceState.INSUFFICIENT
        else:
            state = EvidenceState.SUPPORTED
        proof = opinions[1].proof if state is EvidenceState.SUPPORTED else None
        if proof is not None:
            try:
                status, _ = IsolatedAnswerContract(lambda _: proof).decision(context, proof)
                if status.value != 'ANSWERABLE':
                    return AnswerabilityResult('BINDING_ERROR', EvidenceState.UNKNOWN, None, tuple(trace))
            except Exception:
                return AnswerabilityResult('BINDING_ERROR', EvidenceState.UNKNOWN, None, tuple(trace))
        return AnswerabilityResult('DECIDED', state, proof, tuple(trace))


class MockSemanticJudge:
    """Explicit test adapter. No query keywords, question IDs or gold lookup."""
    def __init__(self, state=EvidenceState.UNKNOWN, *, proof_factory=None):
        self.state, self.proof_factory = state, proof_factory

    async def judge(self, context):
        return JudgeOpinion(self.state, context.sha256, 'MOCK-NOT-SEMANTIC-v1', ('MOCK_ONLY',),
                            self.proof_factory(context) if self.proof_factory else None)
