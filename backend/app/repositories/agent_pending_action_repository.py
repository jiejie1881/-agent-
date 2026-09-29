from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.agent_pending_action import AgentPendingAction
from app.repositories.base import BaseRepository


class AgentPendingActionRepository(BaseRepository[AgentPendingAction]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, AgentPendingAction)

    def list_by_conversation_and_user(
        self, conversation_id: int, user_id: int
    ) -> list[AgentPendingAction]:
        statement = (
            select(AgentPendingAction)
            .where(
                AgentPendingAction.conversation_id == conversation_id,
                AgentPendingAction.user_id == user_id,
            )
            .order_by(AgentPendingAction.created_at.asc(), AgentPendingAction.id.asc())
        )
        return list(self.session.scalars(statement))

    def get_owned(
        self, action_id: int, conversation_id: int, user_id: int, *, for_update: bool = False
    ) -> AgentPendingAction | None:
        statement = select(AgentPendingAction).where(
            AgentPendingAction.id == action_id,
            AgentPendingAction.conversation_id == conversation_id,
            AgentPendingAction.user_id == user_id,
        )
        if for_update:
            statement = statement.with_for_update()
        return self.session.scalar(statement)
