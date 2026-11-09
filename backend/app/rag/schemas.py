from pydantic import BaseModel, ConfigDict, Field


class KnowledgeSection(BaseModel):
    model_config = ConfigDict(frozen=True)

    content: str = Field(min_length=1)
    source: str = Field(min_length=1)
    document_name: str = Field(min_length=1)
    document_type: str = Field(min_length=1)
    section: str = Field(min_length=1)
    access_scope: str = "public"
    document_id: str = ""


class KnowledgeChunk(KnowledgeSection):
    chunk_index: int = Field(ge=0)
    chunk_id: str = ""
    index_version: str | None = None


class KnowledgeSearchResult(KnowledgeChunk):
    score: float | None = Field(default=None, ge=0.0, le=1.0)
    vector_distance: float | None = None
    vector_rank: int | None = None
    bm25_score: float | None = None
    bm25_rank: int | None = None
    rrf_score: float | None = None
    fusion_rank: int | None = None
    final_rank: int | None = None
    index_version: str | None = None
    retrieval_sources: list[str] = Field(default_factory=list)
    reranker_score: float | None = None
    reranker_rank: int | None = None


class KnowledgeBuildResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    documents: int = Field(ge=0)
    chunks: int = Field(ge=0)


class KnowledgeBaseStatus(BaseModel):
    model_config = ConfigDict(frozen=True)

    ready: bool
    documents: int = Field(ge=0)
    chunks: int = Field(ge=0)
