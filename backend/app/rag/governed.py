"""Actor-aware facade; never silently falls back to an ungoverned knowledge base."""
from app.services.knowledge_retrieval_service import KnowledgeRetrievalService


class GovernedRagFacade(KnowledgeRetrievalService):
    def __init__(self, session, settings):
        super().__init__(session, settings.rag_governance_root,
            offline=settings.rag_governance_offline_enabled and settings.app_environment == "test",
            default_base_id=settings.rag_governance_default_base_id, default_strategy=settings.rag_retrieval_mode,
            settings=settings)
