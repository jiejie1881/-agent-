from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, Enum, ForeignKey, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain.enums import AgentPendingActionStatus
from app.infrastructure.database.base import Base


class AgentPendingAction(Base):
    __tablename__ = "agent_pending_actions"
    __table_args__ = (
        CheckConstraint("length(trim(tool_name)) > 0", name="ck_agent_pending_action_tool_not_blank"),
        CheckConstraint("length(trim(summary)) > 0", name="ck_agent_pending_action_summary_not_blank"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("agent_conversations.id", ondelete="CASCADE"), index=True
    )
    tool_name: Mapped[str] = mapped_column(String(100), nullable=False)
    arguments: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    display_data: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    risk_level: Mapped[str] = mapped_column(String(20), nullable=False)
    risk_message: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[AgentPendingActionStatus] = mapped_column(
        Enum(
            AgentPendingActionStatus,
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            name="agent_pending_action_status",
        ),
        default=AgentPendingActionStatus.PENDING,
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped["User"] = relationship(back_populates="agent_pending_actions")
    conversation: Mapped["AgentConversation"] = relationship(back_populates="pending_actions")


from app.models.agent_conversation import AgentConversation  # noqa: E402
from app.models.user import User  # noqa: E402
