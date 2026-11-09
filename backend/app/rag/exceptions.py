class KnowledgeBaseError(Exception):
    """Safe, user-facing RAG error without provider internals."""


class KnowledgeBaseConfigurationError(KnowledgeBaseError):
    pass


class KnowledgeBaseNotReadyError(KnowledgeBaseError):
    pass


class KnowledgeBaseEmbeddingError(KnowledgeBaseError):
    pass


class KnowledgeDocumentError(KnowledgeBaseError):
    pass
