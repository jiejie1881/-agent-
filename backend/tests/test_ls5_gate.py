from app.evaluation.closure import admission


def test_missing_real_model_cannot_pass_even_when_other_metrics_perfect():
    agent=dict(intent_accuracy=1,tool_selection_accuracy=1,task_completion_rate=1)
    answers=dict(no_answer_false_answer_rate=0,citation_accuracy=1,reviewed=10,
                 invalid_citation_count=0,unsupported_answers=0,missing_citations=0)
    result=admission(agent,answers,dict(status='PASS',run_count=4),unauthorized_calls=0)
    assert result['status']=='BLOCKED'


def test_malformed_real_model_digest_not_accepted():
    agent=dict(intent_accuracy=1,tool_selection_accuracy=1,task_completion_rate=1)
    answers=dict(no_answer_false_answer_rate=0,citation_accuracy=1,reviewed=10,
                 invalid_citation_count=0,unsupported_answers=0,missing_citations=0)
    for digest in ['X'*64,'a'*63,'g'*64]:
        result=admission(agent,answers,dict(status='PASS',run_count=4),unauthorized_calls=0,
            real_model_result=dict(scope='REAL_MODEL',usage_source='PROVIDER_RESPONSE',
                model='fixture',evidence_sha256=digest,successful_requests=1))
        assert result['status']=='BLOCKED'
    assert next(x for x in result['checks'] if x['name']=='real_model_evidence')['status']=='BLOCKED'
    result=admission(agent,answers,dict(status='PASS',run_count=4),unauthorized_calls=0,
                     real_model_result=dict(scope='OFFLINE_FIXTURE',usage_source='PROVIDER_RESPONSE',
                                            model='fixture',evidence_sha256='a'*64,successful_requests=10))
    assert result['status']=='BLOCKED'
