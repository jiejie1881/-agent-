from sqlalchemy.orm import Session

from app.domain.exceptions import ConflictError, NotFoundError
from app.models.cargo_category import CargoCategory
from app.repositories.cargo_category_repository import CargoCategoryRepository
from app.schemas.cargo_category import CargoCategoryCreate, CargoCategoryUpdate
from app.services.base import BaseService


class CargoCategoryService(BaseService):
    def __init__(self, session: Session) -> None:
        super().__init__(session)
        self.repository = CargoCategoryRepository(session)

    def list(self, offset: int = 0, limit: int = 100) -> list[CargoCategory]:
        return self.repository.list(offset, limit)

    def get(self, category_id: int) -> CargoCategory:
        category = self.repository.get(category_id)
        if category is None:
            raise NotFoundError("货物分类不存在")
        return category

    def create(self, data: CargoCategoryCreate) -> CargoCategory:
        if self.repository.get_by_code(data.code):
            raise ConflictError("货物分类编码已存在")
        category = CargoCategory(**data.model_dump())
        return self._commit(
            lambda: self.repository.add(category), "货物分类编码已存在"
        )

    def update(
        self, category_id: int, data: CargoCategoryUpdate
    ) -> CargoCategory:
        category = self.get(category_id)
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(category, field, value)
        return self._commit(
            lambda: self.repository.add(category), "货物分类编码已存在"
        )

    def deactivate(self, category_id: int) -> CargoCategory:
        category = self.get(category_id)
        category.is_active = False
        return self._commit(
            lambda: self.repository.add(category), "货物分类停用失败"
        )
