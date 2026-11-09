from app.core.config import Settings, get_settings
from app.rag.embedding_client import OpenAICompatibleEmbeddingClient
from app.rag.rag_service import RagService
from app.rag.reranker import build_reranker
from app.rag.vector_store import ChromaVectorStore


def build_rag_service(settings: Settings | None = None, *, db=None):
    config = settings or get_settings()
    if config.rag_governance_enabled:
        from app.rag.exceptions import KnowledgeBaseConfigurationError
        from app.rag.governed import GovernedRagFacade
        if db is None:
            raise KnowledgeBaseConfigurationError("知识治理需要授权数据库上下文，禁止退回旧知识库")
        return GovernedRagFacade(db, config)
    return RagService(
        OpenAICompatibleEmbeddingClient(config),
        ChromaVectorStore(
            config.rag_vector_store_dir,
            config.rag_collection_name,
        ),
        knowledge_base_dir=config.rag_knowledge_base_dir,
        chunk_size=config.rag_chunk_size,
        chunk_overlap=config.rag_chunk_overlap,
        default_top_k=config.rag_default_top_k,
        retrieval_mode=config.rag_retrieval_mode,
        reference_policy=config.rag_reference_policy,
        vector_candidates=config.rag_vector_candidates,
        bm25_candidates=config.rag_bm25_candidates,
        rrf_k=config.rag_rrf_k,
        reranker=build_reranker(config),
        reranker_candidate_k=config.rag_reranker_candidate_k,
    )
