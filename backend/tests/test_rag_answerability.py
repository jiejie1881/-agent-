from dataclasses import replace

import pytest

from app.rag.answerability import Basis, EvidenceSpan, ServerAssessment, Status, assess


def supported():
    text = 'COMPLETED需求不应当作新的待计划需求。'
    span = EvidenceSpan('synthetic-v1', 'synthetic-chunk', text, 0, len(text), frozenset({'completed_reassignment'}))
    return ServerAssessment(authorization='ALLOW', candidates=1, versions_valid=True, conditions_match=True,
        subject_matches=True, time_matches=True, required_claims=frozenset({'completed_reassignment'}),
        spans=(span,), support_basis=Basis.STRUCTURED_RULE_VALIDATOR)


@pytest.mark.parametrize(('changes','status'), [
    ({}, Status.SUPPORTED),
    ({'candidates':0,'spans':()}, Status.NOT_FOUND_IN_SEARCH),
    ({'spans':()}, Status.INSUFFICIENT_EVIDENCE),
    ({'conditions_match':False}, Status.CONDITION_MISMATCH),
    ({'conditions_match':None}, Status.INSUFFICIENT_EVIDENCE),
    ({'subject_matches':False}, Status.CONDITION_MISMATCH),
    ({'subject_matches':None}, Status.INSUFFICIENT_EVIDENCE),
    ({'time_matches':False}, Status.CONDITION_MISMATCH),
    ({'time_matches':None}, Status.INSUFFICIENT_EVIDENCE),
    ({'intent':'LIVE','required_business_capability':'receipt_time','approved_business_capabilities':frozenset({'receipt_time'}),'business_authorized':True}, Status.ROUTE_BUSINESS),
    ({'intent':'LIVE','required_business_capability':'receipt_time'}, Status.CAPABILITY_UNAVAILABLE),
    ({'intent':'LIVE','required_business_capability':'receipt_time','approved_business_capabilities':frozenset({'receipt_time'})}, Status.PERMISSION_DENIED),
    ({'authorization':'DENY'}, Status.PERMISSION_DENIED),
    ({'authorization':'STALE'}, Status.RECHECK_AUTHORIZATION),
    ({'authorization':'UNKNOWN'}, Status.RECHECK_AUTHORIZATION),
    ({'conflict':True}, Status.CONFLICT),
    ({'intent':'MIXED'}, Status.SPLIT_REQUIRED),
    ({'candidates':0,'spans':(),'absence_basis':Basis.AUTHORIZED_HUMAN_REVIEW,'authorized_corpus_snapshot':'synthetic-snapshot'}, Status.NO_KB_ANSWER_VERIFIED),
    ({'candidates':0,'spans':(),'absence_basis':Basis.AUTHORIZED_HUMAN_REVIEW}, Status.NOT_FOUND_IN_SEARCH),
    ({'support_basis':Basis.UNKNOWN}, Status.INSUFFICIENT_EVIDENCE),
    ({'versions_valid':False}, Status.INSUFFICIENT_EVIDENCE),
], ids=['supported','empty','missing-span','mismatch','unknown-condition','subject-mismatch','subject-unknown','time-mismatch','time-unknown','business','no-capability','business-denied',
        'denied','stale','unknown-auth','conflict','mixed','verified-absence','no-snapshot','unverified-support','old-version'])
def test_trusted_contract_transitions(changes, status):
    result = assess(replace(supported(), **changes))
    assert result.status == status
    assert result.may_answer is (status is Status.SUPPORTED)
    assert bool(result.references) is result.may_answer


@pytest.mark.parametrize('claim', ['completed_reassignment', 'morning_trip_load', 'temperature_guarantee'])
def test_similar_rule_is_not_support_for_different_claim(claim):
    base = supported()
    actual = assess(replace(base, required_claims=frozenset({claim})))
    assert actual.may_answer is (claim == 'completed_reassignment')


def test_required_evidence_must_cover_all_claims():
    value = replace(supported(), required_claims=frozenset({'completed_reassignment','trip_duplicate'}))
    assert assess(value).status is Status.INSUFFICIENT_EVIDENCE
    text = '同一需求不得重复出现在多趟中。'
    other = EvidenceSpan('synthetic-v1','trip-chunk',text,0,len(text),frozenset({'trip_duplicate'}))
    assert assess(replace(value,candidates=2,spans=(*value.spans,other))).may_answer


def test_unknown_conditions_cannot_be_replaced_by_high_candidate_count():
    assert not assess(replace(supported(), candidates=100, conditions_match=None)).may_answer


def test_negative_rule_can_support_a_negative_answer():
    text = '当前系统不支持自动温控匹配。'
    span = EvidenceSpan('v1','temperature',text,0,len(text),frozenset({'automatic_temperature_supported'}))
    value = replace(supported(), required_claims=span.supports, spans=(span,))
    assert assess(value).status is Status.SUPPORTED
    assert assess(replace(value,required_claims=frozenset({'specific_frozen_cargo_guaranteed'}))).status is Status.INSUFFICIENT_EVIDENCE


def test_rule_intent_does_not_become_live_from_time_words():
    # A trusted intent assessment is required; the contract has no keyword router.
    assert assess(supported()).status is Status.SUPPORTED
    assert assess(replace(supported(),intent='LIVE')).status is Status.CAPABILITY_UNAVAILABLE


def test_public_denial_does_not_disclose_document_existence_or_body():
    results = [assess(replace(supported(), authorization='DENY')),
               assess(replace(supported(),candidates=0,spans=())),
               assess(replace(supported(),authorization='STALE'))]
    assert len({r.public_message for r in results}) == 1
    assert all(not r.references and not r.may_answer for r in results)


@pytest.mark.parametrize('value', [{'authorization':'ALLOW','supported':True}, 'SUPPORTED', True, None])
def test_user_model_claims_are_not_server_assessments(value):
    with pytest.raises(TypeError):
        assess(value)


@pytest.mark.parametrize(('start','end'), [(-1,2),(0,100),(2,1),(True,2)])
def test_invalid_reference_ranges_rejected(start,end):
    with pytest.raises(ValueError):
        EvidenceSpan('v1','x','rule',start,end,frozenset({'claim'}))


def test_untrusted_provenance_and_conditions_rejected():
    with pytest.raises(TypeError):
        replace(supported(),support_basis='STRUCTURED_RULE_VALIDATOR')
    with pytest.raises(TypeError):
        replace(supported(),conditions_match='true')
    with pytest.raises(TypeError):
        replace(supported(),required_claims={'mutable-claim'})
