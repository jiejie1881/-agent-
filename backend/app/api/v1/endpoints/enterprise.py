from datetime import date
from fastapi import APIRouter
from app.api.dependencies import DbSession
from app.api.auth_dependencies import CurrentUser
from app.services.enterprise_service import EnterpriseService

router = APIRouter(prefix='/enterprise', tags=['enterprise'])

@router.get('/overview')
def overview(day: date, actor: CurrentUser, db: DbSession):
    return EnterpriseService(db).overview(day, actor)
