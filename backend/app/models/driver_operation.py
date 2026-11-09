from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base


class DriverOperationReceipt(Base):
    __tablename__ = 'driver_operation_receipts'
    __table_args__ = (UniqueConstraint('actor_id','request_key',name='uq_driver_operation_key'),)

    id: Mapped[int] = mapped_column(primary_key=True)
    actor_id: Mapped[int] = mapped_column(ForeignKey('users.id',ondelete='RESTRICT'))
    request_key: Mapped[str] = mapped_column(String(32))
    operation: Mapped[str] = mapped_column(String(24))
    stop_id: Mapped[int] = mapped_column(ForeignKey('dispatch_order_details.id',ondelete='CASCADE'))
    request_sha256: Mapped[str] = mapped_column(String(64))
    proof_id: Mapped[int | None] = mapped_column(ForeignKey('delivery_proofs.id',ondelete='RESTRICT'),nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),server_default=func.now())
