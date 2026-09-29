from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.agent_conversation import (
    AgentConversation,
    AgentConversationMessage,
)
from app.repositories.base import BaseRepository


class AgentConversationRepository(BaseRepository[AgentConversation]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, AgentConversation)

    def list_by_user(
        self,
        user_id: int,
        offset: int,
        limit: int,
    ) -> list[AgentConversation]:
        statement = (
            select(AgentConversation)
            .where(AgentConversation.user_id == user_id)
            .order_by(
                AgentConversation.updated_at.desc(),
                AgentConversation.id.desc(),
            )
            .offset(offset)
            .limit(limit)
        )
        return list(self.session.scalars(statement))

    def get_by_id_and_user(
        self,
        conversation_id: int,
        user_id: int,
    ) -> AgentConversation | None:
        statement = select(AgentConversation).where(
            AgentConversation.id == conversation_id,
            AgentConversation.user_id == user_id,
        )
        return self.session.scalar(statement)

    def get_for_update_by_id_and_user(
        self,
        conversation_id: int,
        user_id: int,
    ) -> AgentConversation | None:
        statement = (
            select(AgentConversation)
            .where(
                AgentConversation.id == conversation_id,
                AgentConversation.user_id == user_id,
            )
            .with_for_update()
        )
        return self.session.scalar(statement)


class AgentConversationMessageRepository(
    BaseRepository[AgentConversationMessage]
):
    def __init__(self, session: Session) -> None:
        super().__init__(session, AgentConversationMessage)

    def list_by_conversation_and_user(
        self,
        conversation_id: int,
        user_id: int,
    ) -> list[AgentConversationMessage]:
        statement = (
            select(AgentConversationMessage)
            .join(
                AgentConversation,
                AgentConversation.id
                == AgentConversationMessage.conversation_id,
            )
            .where(
                AgentConversationMessage.conversation_id == conversation_id,
                AgentConversation.user_id == user_id,
            )
            .order_by(
                AgentConversationMessage.created_at.asc(),
                AgentConversationMessage.id.asc(),
            )
        )
        return list(self.session.scalars(statement))

    def list_recent_by_conversation_and_user(
        self,
        conversation_id: int,
        user_id: int,
        limit: int,
    ) -> list[AgentConversationMessage]:
        statement = (
            select(AgentConversationMessage)
            .join(
                AgentConversation,
                AgentConversation.id
                == AgentConversationMessage.conversation_id,
            )
            .where(
                AgentConversationMessage.conversation_id == conversation_id,
                AgentConversation.user_id == user_id,
            )
            .order_by(
                AgentConversationMessage.created_at.desc(),
                AgentConversationMessage.id.desc(),
            )
            .limit(limit)
        )
        return list(reversed(list(self.session.scalars(statement))))

    def exists_for_conversation_and_user(
        self,
        conversation_id: int,
        user_id: int,
    ) -> bool:
        statement = (
            select(AgentConversationMessage.id)
            .join(
                AgentConversation,
                AgentConversation.id
                == AgentConversationMessage.conversation_id,
            )
            .where(
                AgentConversationMessage.conversation_id == conversation_id,
                AgentConversation.user_id == user_id,
            )
            .limit(1)
        )
        return self.session.scalar(statement) is not None
