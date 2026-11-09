from types import SimpleNamespace
from sqlalchemy.engine import make_url
import pytest

from app.domain.exceptions import BusinessError
from app.services.knowledge_execution import IsolatedKnowledgeMysql, require_synthetic_execution


def session(dialect='mysql', proof=None, actual=None, url=None):
    identity = proof or IsolatedKnowledgeMysql('rag_task2_123456abcdef', '12345678-1234-1234-1234-123456789abc')
    queries = []
    def query(sql):
        queries.append(sql)
        return SimpleNamespace(one=lambda: actual or (identity.database, identity.server_uuid))
    bind = SimpleNamespace(dialect=SimpleNamespace(name=dialect), url=make_url(url or
        'mysql+pymysql://rag_task2:synthetic@127.0.0.1/rag_task2_123456abcdef'))
    return SimpleNamespace(info={'knowledge_isolated_mysql': proof},get_bind=lambda:bind,
                           connection=lambda:SimpleNamespace(exec_driver_sql=query)),queries


def test_sqlite_remains_explicit_and_does_not_query_identity():
    value, queries=session('sqlite')
    require_synthetic_execution(value,True)
    assert queries==[]
    with pytest.raises(BusinessError):require_synthetic_execution(value,False)


@pytest.mark.parametrize('proof',[None,{}, {'database':'rag_task2_123456abcdef'}, 'approved'])
def test_arbitrary_mysql_is_denied_before_connect(proof):
    value,queries=session(proof=proof)
    with pytest.raises(BusinessError):require_synthetic_execution(value,True)
    assert queries==[]


@pytest.mark.parametrize('url',[
    'mysql+pymysql://rag_task2:p@localhost/rag_task2_123456abcdef',
    'mysql+pymysql://root:p@127.0.0.1/rag_task2_123456abcdef',
    'mysql+pymysql://rag_task2:p@127.0.0.1/logistics',
])
def test_proof_cannot_authorize_different_target(url):
    proof=IsolatedKnowledgeMysql('rag_task2_123456abcdef','12345678-1234-1234-1234-123456789abc')
    value,queries=session(proof=proof,url=url)
    with pytest.raises(BusinessError):require_synthetic_execution(value,True)
    assert queries==[]


def test_runtime_uuid_and_database_are_both_checked():
    proof=IsolatedKnowledgeMysql('rag_task2_123456abcdef','12345678-1234-1234-1234-123456789abc')
    value,queries=session(proof=proof,actual=(proof.database,'different-server'))
    with pytest.raises(BusinessError):require_synthetic_execution(value,True)
    assert len(queries)==1
    value,_=session(proof=proof)
    require_synthetic_execution(value,True)
