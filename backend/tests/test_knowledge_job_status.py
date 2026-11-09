from datetime import datetime, timedelta
from types import SimpleNamespace

from app.services.knowledge_job_status import describe_job


def job(**values):
    return SimpleNamespace(**({'status': 'SUCCEEDED', 'stage': 'READY', 'attempts': 2, 'error_type': None} | values))


def event(number, action, attempt=None, **extra):
    changes = dict(extra)
    if attempt is not None:
        changes['attempt'] = attempt
    return SimpleNamespace(id=number, action=action, changes=changes,
                           created_at=datetime(2030, 1, 1) + timedelta(seconds=number))


def test_latest_attempt_has_own_timestamps_without_earlier_failure():
    events = [event(1, 'RAG_JOB_STARTED', 1), event(2, 'RAG_JOB_FAILED', 1),
              event(3, 'RAG_JOB_STARTED', 2), event(4, 'RAG_JOB_STAGE', 2, stage='PARSING'),
              event(5, 'RAG_JOB_COMPLETED', 2)]
    value = describe_job(job(), events)
    assert value['started_at'] == events[2].created_at
    assert value['finished_at'] == events[-1].created_at
    assert len(value['timeline']) == 3 and value['progress']['completed_steps'] == 5


def test_queued_retry_does_not_reuse_terminal_time_or_progress():
    value = describe_job(job(status='QUEUED', stage='INDEXING'),
                         [event(1, 'RAG_JOB_STARTED', 2), event(2, 'RAG_JOB_FAILED', 2)])
    assert value['started_at'] is value['finished_at'] is None
    assert value['timeline'] == [] and value['progress']['completed_steps'] == 0


def test_old_audits_and_missing_audits_do_not_invent_times():
    start = event(2, 'RAG_JOB_STAGE', stage='PARSING')
    end = event(3, 'RAG_JOB_COMPLETED')
    assert describe_job(job(), [start, end])['started_at'] == start.created_at
    assert describe_job(job(), [])['finished_at'] is None


def test_safe_failure_message_and_timeline_never_echo_exception_or_tokens():
    value = describe_job(job(status='FAILED', stage='EMBEDDING', error_type='SYNTHETIC_SECRET'),
                         [event(1, 'RAG_JOB_STARTED', 2, secret='SYNTHETIC_SECRET'),
                          event(2, 'RAG_JOB_FAILED', 2, content='SYNTHETIC_SECRET', lease_token='SYNTHETIC_SECRET')])
    assert 'SYNTHETIC_SECRET' not in str(value)
    assert value['progress']['unit'] == 'stages' and value['progress']['completed_steps'] == 2
