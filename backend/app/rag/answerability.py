"""Deterministic contract over trusted SERVER assessments, not an NLP classifier.

There is deliberately no JSON/model-output deserializer or question-ID lookup.
Server integrations must resolve authorization, conditions, versions and support
from authoritative data before constructing these objects. This module neither
infers semantic entailment nor executes a business tool or a model.
"""
from dataclasses import dataclass
from enum import Enum
import math
from typing import Mapping


class Status(str, Enum):
    SUPPORTED = 'SUPPORTED'
    INSUFFICIENT_EVIDENCE = 'INSUFFICIENT_EVIDENCE'
    CONDITION_MISMATCH = 'CONDITION_MISMATCH'
    ROUTE_BUSINESS = 'ROUTE_BUSINESS'
    CAPABILITY_UNAVAILABLE = 'CAPABILITY_UNAVAILABLE'
    NOT_FOUND_IN_SEARCH = 'NOT_FOUND_IN_SEARCH'
    NO_KB_ANSWER_VERIFIED = 'NO_KB_ANSWER_VERIFIED'
    PERMISSION_DENIED = 'PERMISSION_DENIED'
    RECHECK_AUTHORIZATION = 'RECHECK_AUTHORIZATION'
    CONFLICT = 'CONFLICT'
    SPLIT_REQUIRED = 'SPLIT_REQUIRED'


class Basis(str, Enum):
    UNKNOWN = 'UNKNOWN'
    STRUCTURED_RULE_VALIDATOR = 'STRUCTURED_RULE_VALIDATOR'
    AUTHORIZED_HUMAN_REVIEW = 'AUTHORIZED_HUMAN_REVIEW'


@dataclass(frozen=True)
class EvidenceSpan:
    document_version: str
    chunk_id: str
    source_text: str
    start: int
    end: int
    supports: frozenset[str]

    def __post_init__(self):
        if (type(self.document_version) is not str or type(self.chunk_id) is not str or type(self.source_text) is not str or
                not self.document_version or not self.chunk_id or type(self.supports) is not frozenset or not self.supports or
                any(type(c) is not str or not c for c in self.supports) or
                type(self.start) is not int or type(self.end) is not int or
                not 0 <= self.start < self.end <= len(self.source_text) or
                not self.source_text[self.start:self.end].strip()):
            raise ValueError('Invalid server evidence span')


@dataclass(frozen=True)
class ServerAssessment:
    authorization: str = 'UNKNOWN'  # ALLOW / DENY / STALE / UNKNOWN
    intent: str = 'RULE'  # RULE / LIVE / MIXED
    candidates: int = 0
    versions_valid: bool = False
    conditions_match: bool | None = None
    subject_matches: bool | None = None
    time_matches: bool | None = None
    conflict: bool = False
    required_claims: frozenset[str] = frozenset()
    spans: tuple[EvidenceSpan, ...] = ()
    support_basis: Basis = Basis.UNKNOWN
    absence_basis: Basis = Basis.UNKNOWN
    authorized_corpus_snapshot: str | None = None
    required_business_capability: str | None = None
    approved_business_capabilities: frozenset[str] = frozenset()
    business_authorized: bool = False

    def __post_init__(self):
        if self.authorization not in {'ALLOW', 'DENY', 'STALE', 'UNKNOWN'} or self.intent not in {'RULE', 'LIVE', 'MIXED'}:
            raise ValueError('Invalid server assessment state')
        if type(self.candidates) is not int or self.candidates < 0:
            raise ValueError('Invalid candidate count')
        if any(type(v) is not frozenset or any(type(k) is not str or not k for k in v)
               for v in (self.required_claims, self.approved_business_capabilities)):
            raise TypeError('Server claims/capabilities must be immutable identifiers')
        if not isinstance(self.spans, tuple) or any(type(s) is not EvidenceSpan for s in self.spans):
            raise TypeError('Only immutable server evidence spans are allowed')
        if type(self.support_basis) is not Basis or type(self.absence_basis) is not Basis:
            raise TypeError('Assessment provenance must be explicit')
        if type(self.versions_valid) is not bool or type(self.conflict) is not bool or type(self.business_authorized) is not bool:
            raise TypeError('Server checks must be booleans')
        if any(value is not None and type(value) is not bool for value in
               (self.conditions_match, self.subject_matches, self.time_matches)):
            raise TypeError('Conditions must be checked or UNKNOWN')


@dataclass(frozen=True)
class Decision:
    status: Status
    may_answer: bool = False
    references: tuple[EvidenceSpan, ...] = ()
    business_capability: str | None = None

    @property
    def public_message(self):
        # No distinction exposing whether a restricted document exists.
        if self.status in {Status.PERMISSION_DENIED, Status.RECHECK_AUTHORIZATION,
                           Status.NOT_FOUND_IN_SEARCH, Status.NO_KB_ANSWER_VERIFIED}:
            return '没有足够的授权资料可确认。'
        if self.status == Status.SUPPORTED:
            return '仅可依据已核验片段回答并引用。'
        if self.status == Status.ROUTE_BUSINESS:
            return '需查询有权限的实时业务工具。'
        return '当前证据不足或条件未确认，不能给出确定结论。'


def assess(value: ServerAssessment) -> Decision:
    if type(value) is not ServerAssessment:
        raise TypeError('User/model mappings are not trusted server assessments')
    if value.authorization != 'ALLOW':
        return Decision(Status.PERMISSION_DENIED if value.authorization == 'DENY' else Status.RECHECK_AUTHORIZATION)
    if value.intent == 'LIVE':
        if value.required_business_capability not in value.approved_business_capabilities or not value.required_business_capability:
            return Decision(Status.CAPABILITY_UNAVAILABLE)
        if not value.business_authorized:
            return Decision(Status.PERMISSION_DENIED)
        return Decision(Status.ROUTE_BUSINESS, business_capability=value.required_business_capability)
    if value.intent == 'MIXED':
        return Decision(Status.SPLIT_REQUIRED)
    if not value.versions_valid:
        return Decision(Status.INSUFFICIENT_EVIDENCE)
    if value.conflict:
        return Decision(Status.CONFLICT)
    # A stable chunk ID cannot refer to incompatible source snapshots. Trusted
    # support labels do not make contradictory identity/version metadata safe.
    identities = {}
    for span in value.spans:
        identity = (span.document_version, span.source_text)
        if span.chunk_id in identities and identities[span.chunk_id] != identity:
            return Decision(Status.CONFLICT)
        identities[span.chunk_id] = identity
    applicability = (value.conditions_match, value.subject_matches, value.time_matches)
    if any(value is False for value in applicability):
        return Decision(Status.CONDITION_MISMATCH)
    if any(value is None for value in applicability):
        return Decision(Status.INSUFFICIENT_EVIDENCE)
    if not value.candidates:
        verified = value.absence_basis is Basis.AUTHORIZED_HUMAN_REVIEW and bool(value.authorized_corpus_snapshot)
        return Decision(Status.NO_KB_ANSWER_VERIFIED if verified else Status.NOT_FOUND_IN_SEARCH)
    supported = frozenset(claim for span in value.spans for claim in span.supports)
    if (value.support_basis is not Basis.UNKNOWN and value.required_claims and value.spans and
            value.required_claims <= supported and len({s.chunk_id for s in value.spans}) <= value.candidates):
        return Decision(Status.SUPPORTED, True, value.spans)
    return Decision(Status.INSUFFICIENT_EVIDENCE)


def acceptance_gates(metrics: Mapping, *, negative_questions=None, false_positive_questions=None,
                     semantic_kind='NOT_RUN', semantic_passed=None, generation_kind='NOT_RUN',
                     generation_passed=None, reranker_kind='NOT_RUN', reranker_passed=None):
    """Separate gates, preserving historical retrieval arithmetic and thresholds.

    REAL_VERIFIED is an evidence classification supplied by a trusted evaluator,
    never a request parameter. Contract/mock observations cannot open real gates.
    """
    def measured(value):
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and 0 <= value <= 1
    recall, ndcg = metrics.get('recall_at_k'), metrics.get('ndcg')
    retrieval = 'BLOCKED' if not measured(recall) or not measured(ndcg) else ('PASS' if recall >= .95 and ndcg >= .65 else 'FAIL')
    if (type(negative_questions) is not int or type(false_positive_questions) is not int or
            negative_questions <= 0 or not 0 <= false_positive_questions <= negative_questions):
        refusal = 'BLOCKED'
    else:
        refusal = 'PASS' if false_positive_questions == 0 else 'FAIL'
    def real(kind, passed):
        return 'BLOCKED' if kind != 'REAL_VERIFIED' or type(passed) is not bool else ('PASS' if passed else 'FAIL')
    gates = dict(retrieval=retrieval, retrieval_abstention=refusal,
        semantic_answerability=real(semantic_kind, semantic_passed),
        final_generation=real(generation_kind, generation_passed),
        real_reranker=real(reranker_kind, reranker_passed))
    gates['overall'] = 'PASS' if all(v == 'PASS' for v in gates.values()) else 'PARTIAL'
    return gates
