from app.core.config import Settings, get_settings
from app.rag.embedding_client import OpenAICompatibleEmbeddingClient
from app.rag.rag_service import RagService
from app.rag.vector_store import ChromaVectorStore


def build_rag_service(settings: Settings | None = None) -> RagService:
    config = settings or get_settings()
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
    )
