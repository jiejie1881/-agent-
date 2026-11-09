from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.agent.model_types import AgentMessageRole, AgentModelMessage
from app.domain.enums import AgentConversationMessageRole
from app.domain.exceptions import BusinessError, ConflictError, NotFoundError
from app.models.agent_conversation import (
    AgentConversation,
    AgentConversationMessage,
)
from app.repositories.agent_conversation_repository import (
    AgentConversationMessageRepository,
    AgentConversationRepository,
)
from app.services.base import BaseService


class AgentConversationService(BaseService):
    DEFAULT_TITLE = "新会话"
    TITLE_MAX_LENGTH = 50

    def __init__(self, session: Session, history_max_messages: int) -> None:
        super().__init__(session)
        self.history_max_messages = history_max_messages
        self.conversation_repository = AgentConversationRepository(session)
        self.message_repository = AgentConversationMessageRepository(session)

    def create(self, user_id: int) -> AgentConversation:
        conversation = AgentConversation(
            user_id=user_id,
            title=self.DEFAULT_TITLE,
        )
        return self._commit(
            lambda: self.conversation_repository.add(conversation),
            "创建Agent会话失败",
        )

    def list(
        self,
        user_id: int,
        offset: int,
        limit: int,
    ) -> list[AgentConversation]:
        return self.conversation_repository.list_by_user(
            user_id, offset, limit
        )

    def get_owned(
        self,
        conversation_id: int,
        user_id: int,
    ) -> AgentConversation:
        conversation = self.conversation_repository.get_by_id_and_user(
            conversation_id, user_id
        )
        if conversation is None:
            raise NotFoundError("Agent会话不存在")
        return conversation

    def get_detail(
        self,
        conversation_id: int,
        user_id: int,
    ) -> tuple[AgentConversation, list[AgentConversationMessage]]:
        conversation = self.get_owned(conversation_id, user_id)
        messages = self.message_repository.list_by_conversation_and_user(
            conversation_id, user_id
        )
        return conversation, messages

    def get_model_history(
        self,
        conversation_id: int,
        user_id: int,
    ) -> tuple[AgentModelMessage, ...]:
        self.get_owned(conversation_id, user_id)
        messages = (
            self.message_repository.list_recent_by_conversation_and_user(
                conversation_id,
                user_id,
                self.history_max_messages,
            )
        )
        return tuple(
            AgentModelMessage(
                role=(
                    AgentMessageRole.USER
                    if message.role == AgentConversationMessageRole.USER
                    else AgentMessageRole.ASSISTANT
                ),
                content=message.content,
            )
            for message in messages
        )

    def save_exchange(
        self,
        conversation_id: int,
        user_id: int,
        user_content: str,
        assistant_content: str,
    ) -> AgentConversationMessage:
        try:
            conversation = (
                self.conversation_repository.get_for_update_by_id_and_user(
                    conversation_id, user_id
                )
            )
            if conversation is None:
                raise NotFoundError("Agent会话不存在")
            is_first_exchange = not (
                self.message_repository.exists_for_conversation_and_user(
                    conversation_id, user_id
                )
            )
            self.message_repository.add(
                AgentConversationMessage(
                    conversation_id=conversation.id,
                    role=AgentConversationMessageRole.USER,
                    content=user_content,
                )
            )
            assistant_message = self.message_repository.add(
                AgentConversationMessage(
                    conversation_id=conversation.id,
                    role=AgentConversationMessageRole.ASSISTANT,
                    content=assistant_content,
                )
            )
            if is_first_exchange:
                conversation.title = self._title_from(user_content)
            conversation.updated_at = datetime.now(timezone.utc)
            self.session.add(conversation)
            self.session.commit()
            self.session.refresh(assistant_message)
            return assistant_message
        except BusinessError:
            self.session.rollback()
            raise
        except IntegrityError as exc:
            self.session.rollback()
            raise ConflictError("保存Agent会话消息失败") from exc
        except Exception:
            self.session.rollback()
            raise

    @classmethod
    def _title_from(cls, content: str) -> str:
        normalized = content.strip()
        return normalized[: cls.TITLE_MAX_LENGTH] or cls.DEFAULT_TITLE
