from app.rag.schemas import KnowledgeChunk, KnowledgeSection


class KnowledgeTextSplitter:
    def __init__(self, chunk_size: int = 800, chunk_overlap: int = 120) -> None:
        if chunk_size < 1:
            raise ValueError("chunk_size must be positive")
        if chunk_overlap < 0 or chunk_overlap >= chunk_size:
            raise ValueError("chunk_overlap must be between 0 and chunk_size - 1")
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def split(self, sections: list[KnowledgeSection]) -> list[KnowledgeChunk]:
        chunks: list[KnowledgeChunk] = []
        indexes: dict[str, int] = {}
        for section in sections:
            start = 0
            content = section.content
            while start < len(content):
                end = min(start + self.chunk_size, len(content))
                if end < len(content):
                    boundary = max(
                        content.rfind("\n", start, end),
                        content.rfind("。", start, end),
                    )
                    if boundary > start + self.chunk_size // 2:
                        end = boundary + 1
                piece = content[start:end].strip()
                if piece:
                    index = indexes.get(section.source, 0)
                    data = section.model_dump()
                    data["content"] = piece
                    chunks.append(
                        KnowledgeChunk(
                            **data,
                            chunk_index=index,
                        )
                    )
                    indexes[section.source] = index + 1
                if end >= len(content):
                    break
                start = max(end - self.chunk_overlap, start + 1)
        return chunks
