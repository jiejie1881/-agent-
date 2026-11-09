from app.rag.exceptions import KnowledgeBaseError
from app.rag.factory import build_rag_service


def main() -> None:
    try:
        result = build_rag_service().rebuild()
    except KnowledgeBaseError as exc:
        raise SystemExit(f"知识库构建失败：{exc}") from None
    print(f"知识库构建完成：{result.documents} 份文档，{result.chunks} 个 Chunk")


if __name__ == "__main__":
    main()
