from __future__ import annotations

from typing import Any

from app.agent.exceptions import AgentToolExecutionError
from app.agent.schemas.tool import SearchKnowledgeBaseArgs
from app.agent.tool_execution import AgentToolContext, AgentToolExecutor
from app.rag.exceptions import KnowledgeBaseError
from app.rag.rag_service import RagService


class SearchKnowledgeBaseTool(AgentToolExecutor[SearchKnowledgeBaseArgs]):
    name = "search_knowledge_base"
    arguments_type = SearchKnowledgeBaseArgs

    def __init__(self, service: RagService) -> None:
        self.service = service

    def _execute(
        self,
        arguments: SearchKnowledgeBaseArgs,
        context: AgentToolContext,
    ) -> dict[str, Any]:
        try:
            results = self.service.search(
                arguments.query,
                arguments.top_k,
                arguments.document_type,
            )
        except (KnowledgeBaseError, ValueError) as exc:
            raise AgentToolExecutionError(
                self.name,
                str(exc),
                status_code=503 if isinstance(exc, KnowledgeBaseError) else 400,
            ) from exc
        return {
            "query": arguments.query,
            "result_count": len(results),
            "results": [item.model_dump() for item in results],
            "message": (
                None
                if results
                else "知识库未找到足够的相关信息"
            ),
        }
