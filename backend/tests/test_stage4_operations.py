import json

import pytest
from pydantic import ValidationError
from sqlalchemy import text

from app.core.config import Settings
from app.domain.enums import UserRole
from app.services.auth_service import AuthService


def test_production_shadow_rejects_missing_budget_and_accepts_blank_optional_env():
    values = {'_env_file':None,'database_url':'sqlite://','jwt_secret_key':'x'*40,
              'app_environment':'production','api_docs_enabled':False,'run_migrations':False}
    with pytest.raises(ValidationError, match='monetary budget'):
        Settings(**values,agent_dispatch_shadow_enabled=True)
    assert Settings(**values,agent_dispatch_shadow_max_cost='').agent_dispatch_shadow_max_cost is None
    assert Settings(**values,agent_dispatch_shadow_enabled=True,agent_dispatch_shadow_max_cost='1',
                    agent_dispatch_shadow_input_price_per_million='1',agent_dispatch_shadow_output_price_per_million='2',
                    agent_dispatch_shadow_cost_currency='CNY')


def test_production_readiness_rejects_stale_schema_then_recovers(client,session,monkeypatch):
    from app import main
    monkeypatch.setattr(main.settings,'app_environment','production')
    session.execute(text('CREATE TABLE alembic_version(version_num VARCHAR(32) PRIMARY KEY)'))
    session.execute(text("INSERT INTO alembic_version VALUES ('20261014_26')"));session.commit()
    response=client.get('/health/ready')
    assert response.status_code==503 and response.json()['schema']=='mismatch'
    from pathlib import Path

    from alembic.script import ScriptDirectory
    head=ScriptDirectory(str(Path(__file__).resolve().parents[1]/'alembic')).get_current_head()
    session.execute(text('UPDATE alembic_version SET version_num=:head'),{'head':head});session.commit()
    assert client.get('/health/ready').status_code==200


def test_metrics_requires_admin_and_logs_do_not_contain_query_or_credentials(client,session,monkeypatch):
    import app.core.observability as obs
    records=[]
    monkeypatch.setattr(obs.logger,'info',records.append)
    marker='SECRET_STAGE4_MUST_NOT_LOG'
    response=client.get('/health?token='+marker,headers={'Authorization':'Bearer '+marker})
    assert response.status_code==200 and len(response.headers['X-Request-ID'])==32
    assert marker not in json.dumps(records)
    assert json.loads(records[-1])['route']=='/health'
    assert client.get('/api/v1/system/metrics').status_code==200
    user=AuthService(session).create_user('s4-viewer','Stage4Viewer!123',UserRole.VIEWER)
    token=AuthService(session).login(user.username,'Stage4Viewer!123').access_token
    assert client.get('/api/v1/system/metrics',headers={'Authorization':'Bearer '+token}).status_code==403


def test_unknown_methods_have_bounded_metric_cardinality():
    from app.core.observability import HttpTelemetry
    metrics=HttpTelemetry()
    for i in range(100):metrics.record('UNKNOWN'+str(i),'UNMATCHED',404,.1)
    assert len(metrics.snapshot()['requests'])==1
