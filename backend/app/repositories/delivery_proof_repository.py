from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.dispatch_plan import DeliveryProof, DispatchOrderDetail


class DeliveryProofRepository:
    def __init__(self, session: Session):
        self.session = session

    def get(self, proof_id: int):
        return self.session.get(DeliveryProof, proof_id)

    def by_path(self, file_path: str):
        return self.session.scalar(select(DeliveryProof).where(DeliveryProof.file_path == file_path))

    def lock_stop(self, stop_id: int):
        # Serialize upload/review on the same stop; SQLite ignores FOR UPDATE in tests.
        return self.session.scalar(select(DispatchOrderDetail).where(
            DispatchOrderDetail.id == stop_id
        ).with_for_update().execution_options(populate_existing=True))

    def list_for_stop(self, stop_id: int):
        return list(self.session.scalars(select(DeliveryProof).where(
            DeliveryProof.dispatch_order_detail_id == stop_id
        ).with_for_update().execution_options(populate_existing=True)))

    def add(self, row):
        self.session.add(row)
        self.session.flush()
        return row
