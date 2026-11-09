"""Fail-closed execution gate for synthetic SQLite or explicitly attested MySQL.

Attestation is installed by the isolated test harness, never by request input.
This does not authorize real models or production database execution.
"""
from dataclasses import dataclass
import re

from app.domain.exceptions import BusinessError


@dataclass(frozen=True)
class IsolatedKnowledgeMysql:
    database: str
    server_uuid: str


def require_synthetic_execution(session, offline):
    bind = session.get_bind()
    if offline and bind.dialect.name == 'sqlite':
        return
    proof = session.info.get('knowledge_isolated_mysql')
    if (offline and bind.dialect.name == 'mysql' and type(proof) is IsolatedKnowledgeMysql
            and re.fullmatch(r'rag_task2_[0-9a-f]{12}', proof.database)
            and re.fullmatch(r'[0-9a-f-]{36}', proof.server_uuid)
            and bind.url.database == proof.database and bind.url.host == '127.0.0.1'
            and bind.url.username == 'rag_task2'):
        actual = session.connection().exec_driver_sql('SELECT DATABASE(), @@server_uuid').one()
        if tuple(actual) == (proof.database, proof.server_uuid):
            return
    raise BusinessError('仅允许合成SQLite或已明确核验身份的专用MySQL；真实模型未授权',
                        503, 'REAL_MODEL_NOT_AUTHORIZED')


def require_knowledge_execution(session, offline):
    """Keep the historical synthetic gate; production needs explicit DB identity.

    This permits authorized application operations, not unbudgeted model calls.
    Model transports retain their independent fail-closed billing gate.
    """
    if offline:
        return require_synthetic_execution(session, True)
    from app.core.config import get_settings
    from sqlalchemy.engine import make_url
    config = get_settings()
    bind = session.get_bind()
    expected = getattr(config, 'rag_governance_mysql_uuid', None)
    if (config.app_environment != 'production' or not config.rag_governance_enabled
            or config.rag_governance_offline_enabled or bind.dialect.name != 'mysql'
            or not expected or bind.url.database != make_url(config.database_url).database):
        raise BusinessError('知识治理正式执行环境未授权或未核验', 503, 'KNOWLEDGE_RUNTIME_NOT_ATTESTED')
    actual = session.connection().exec_driver_sql('SELECT DATABASE(), @@server_uuid').one()
    if tuple(actual) != (bind.url.database, expected):
        raise BusinessError('知识治理数据库身份不匹配', 503, 'KNOWLEDGE_RUNTIME_NOT_ATTESTED')
