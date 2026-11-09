from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictKnowledgeInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class KnowledgeBaseInput(StrictKnowledgeInput):
    name: str = Field(min_length=1, max_length=120)
    business_scope: str = Field(default="", max_length=300)
    visibility: Literal["PUBLIC", "ROLES", "ADMIN"] = "ADMIN"
    read_roles: list[Literal["ADMIN", "DISPATCHER", "VIEWER"]] = Field(default_factory=list)


class KnowledgeBaseUpdate(KnowledgeBaseInput):
    expected_revision: int = Field(ge=0)
    status: Literal["ACTIVE", "ARCHIVED"] = "ACTIVE"


class KnowledgeBuildInput(StrictKnowledgeInput):
    idempotency_key: str = Field(min_length=8, max_length=100)


class KnowledgePublishInput(StrictKnowledgeInput):
    expected_active_id: int | None = Field(default=None, gt=0)
    expected_revision: int = Field(ge=0)
    confirmed: bool


class KnowledgeQueryInput(StrictKnowledgeInput):
    base_id: int = Field(gt=0)
    query: str = Field(min_length=1, max_length=500)
    strategy: Literal["vector", "bm25", "hybrid"] | None = None
    top_k: int | None = Field(default=None, ge=1, le=10)
    document_type: str | None = Field(default=None, min_length=1, max_length=50)
    index_id: int | None = Field(default=None, gt=0)


class KnowledgeValidationInput(StrictKnowledgeInput):
    dataset: Literal["development", "fixed", "document_smoke"] = "document_smoke"
    strategy: Literal["vector", "bm25", "hybrid"] = "bm25"


class KnowledgeDeleteInput(StrictKnowledgeInput):
    expected_revision: int = Field(ge=0)
    confirmed: bool


class KnowledgeDocumentAclInput(StrictKnowledgeInput):
    expected_revision: int = Field(ge=0)
    visibility: Literal["INHERIT", "ADMIN", "ROLES"] = "INHERIT"
    read_roles: list[Literal["ADMIN", "DISPATCHER", "VIEWER"]] = Field(default_factory=list)
