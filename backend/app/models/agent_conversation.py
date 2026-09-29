from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain.enums import AgentConversationMessageRole
from app.infrastructure.database.base import Base
from app.models.mixins import TimestampMixin


class AgentConversation(TimestampMixin, Base):
    __tablename__ = "agent_conversations"
    __table_args__ = (
        CheckConstraint(
            "length(trim(title)) > 0",
            name="ck_agent_conversation_title_not_blank",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(100), nullable=False)

    user: Mapped["User"] = relationship(back_populates="agent_conversations")
    messages: Mapped[list["AgentConversationMessage"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class AgentConversationMessage(Base):
    __tablename__ = "agent_messages"
    __table_args__ = (
        CheckConstraint(
            "length(trim(content)) > 0",
            name="ck_agent_message_content_not_blank",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("agent_conversations.id", ondelete="CASCADE"),
        index=True,
    )
    role: Mapped[AgentConversationMessageRole] = mapped_column(
        Enum(
            AgentConversationMessageRole,
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            name="agent_conversation_message_role",
        ),
        nullable=False,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    conversation: Mapped[AgentConversation] = relationship(
        back_populates="messages"
    )


from app.models.user import User  # noqa: E402
