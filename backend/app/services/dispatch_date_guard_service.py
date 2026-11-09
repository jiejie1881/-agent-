"""Serialize plan generation for one delivery date on MySQL."""

from sqlalchemy import select
from sqlalchemy.dialects.mysql import insert as mysql_insert

from app.models.agent_dispatch_acceptance import DispatchDateGuard


def lock_dispatch_date(session, delivery_date):
    """Use the same lock order in traditional and Agent plan creation."""
    if session.get_bind().dialect.name != "mysql":
        return
    statement = mysql_insert(DispatchDateGuard).values(delivery_date=delivery_date)
    session.execute(statement.on_duplicate_key_update(delivery_date=delivery_date))
    session.scalar(select(DispatchDateGuard).where(
        DispatchDateGuard.delivery_date == delivery_date).with_for_update())
