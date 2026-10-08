from pydantic import BaseModel, ConfigDict, Field


class KnowledgeSection(BaseModel):
    model_config = ConfigDict(frozen=True)

    content: str = Field(min_length=1)
    source: str = Field(min_length=1)
    document_name: str = Field(min_length=1)
    document_type: str = Field(min_length=1)
    section: str = Field(min_length=1)


class KnowledgeChunk(KnowledgeSection):
    chunk_index: int = Field(ge=0)


class KnowledgeSearchResult(KnowledgeChunk):
    score: float = Field(ge=0.0, le=1.0)


class KnowledgeBuildResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    documents: int = Field(ge=0)
    chunks: int = Field(ge=0)


class KnowledgeBaseStatus(BaseModel):
    model_config = ConfigDict(frozen=True)

    ready: bool
    documents: int = Field(ge=0)
    chunks: int = Field(ge=0)
