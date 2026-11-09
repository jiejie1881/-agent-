from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from app.agent.dispatch_workflow import ShadowDispatchWorkflow
from app.agent.langchain_client import LangChainModelClient
from app.api.dependencies import DbSession
from app.core.config import get_settings
from app.services.dispatch_context_service import DispatchContextService


def get_shadow_dispatch(db: DbSession):
    bind = db.get_bind()

    def load(day):
        # Materialize then close: final reload must use a new read transaction.
        with Session(bind=bind, autoflush=False) as session:
            return DispatchContextService(session).load(day)

    settings = get_settings()
    return ShadowDispatchWorkflow(LangChainModelClient(settings=settings,
        max_output_tokens=settings.agent_dispatch_shadow_output_tokens), load, settings)


ShadowDispatchDependency = Annotated[ShadowDispatchWorkflow, Depends(get_shadow_dispatch)]
