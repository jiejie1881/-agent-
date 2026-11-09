import pytest

from app.rag.answerability import acceptance_gates


def test_bm25_ranking_pass_cannot_hide_abstention_and_real_quality_gaps():
    gates=acceptance_gates({'recall_at_k':1,'ndcg':.6684184895489564},negative_questions=3,false_positive_questions=2)
    assert gates['retrieval']=='PASS' and gates['retrieval_abstention']=='FAIL'
    assert gates['semantic_answerability']==gates['final_generation']==gates['real_reranker']=='BLOCKED'
    assert gates['overall']=='PARTIAL'


@pytest.mark.parametrize('kind',['CONTRACT','MOCK','FROZEN_REPLAY','NOT_RUN'])
def test_non_real_evidence_never_opens_real_quality_gates(kind):
    gates=acceptance_gates({'recall_at_k':1,'ndcg':1},negative_questions=3,false_positive_questions=0,
        semantic_kind=kind,semantic_passed=True,generation_kind=kind,generation_passed=True,reranker_kind=kind,reranker_passed=True)
    assert gates['retrieval_abstention']=='PASS'
    assert gates['overall']=='PARTIAL' and gates['real_reranker']=='BLOCKED'


@pytest.mark.parametrize(('recall','ndcg','expected'),[(.95,.65,'PASS'),(.944444,.639328,'FAIL'),(None,.7,'BLOCKED'),(1,float('nan'),'BLOCKED'),(2,1,'BLOCKED')])
def test_original_thresholds_are_preserved(recall,ndcg,expected):
    assert acceptance_gates({'recall_at_k':recall,'ndcg':ndcg})['retrieval']==expected


@pytest.mark.parametrize(('negative','false'),[(0,0),(None,None),(3,4),(3,-1),(True,0)])
def test_unknown_or_invalid_denominators_cannot_pass(negative,false):
    assert acceptance_gates({},negative_questions=negative,false_positive_questions=false)['retrieval_abstention']=='BLOCKED'
