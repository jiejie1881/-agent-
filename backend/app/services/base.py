import re
from collections.abc import Callable
from typing import TypeVar

from sqlalchemy.exc import IntegrityError
from sqlalchemy import select, or_
from sqlalchemy.orm import Session

from app.domain.exceptions import ConflictError

T = TypeVar("T")


class BaseService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.audit_context = None

    def with_audit(self, actor, action, object_type, object_id=None, changes=None):
        self.audit_context = (actor, action, object_type, object_id, changes)
        return self

    def search_page(self, model, offset, limit, keyword=None, is_active=None, filters=None):
        query=select(model).order_by(model.id)
        if keyword:
            fields=[getattr(model,field) for field in ('code','name','address','plate_number','organization','delivery_region') if hasattr(model,field)]
            prefix={'stores':'门店','routes':'线路','vehicles':'车辆','users':'司机'}.get(model.__tablename__)
            match=re.fullmatch(rf"{prefix}-([0-9]+)",keyword.strip()) if prefix else None
            query=query.where(model.id==int(match.group(1))) if match else query.where(or_(*(field.contains(keyword.strip(),autoescape=True) for field in fields)))
        if is_active is not None:
            query=query.where(model.is_active==is_active)
        for key,value in (filters or {}).items():
            if value is not None:query=query.where(getattr(model,key)==value)
        return list(self.session.scalars(query.offset(offset).limit(limit)))

    def _commit(self, action: Callable[[], T], conflict_message: str, *, commit: bool = True) -> T:
        try:
            result = action()
            if self.audit_context:
                from app.services.audit_log_service import AuditLogService
                actor, audit_action, object_type, object_id, changes = self.audit_context
                self.session.flush()
                AuditLogService(self.session).add(actor, audit_action, object_type,
                    object_id if object_id is not None else getattr(result, 'id', None), changes)
            self.session.commit() if commit else self.session.flush()
            return result
        except IntegrityError as exc:
            self.session.rollback()
            raise ConflictError(conflict_message) from exc
        except Exception:
            self.session.rollback()
            raise

