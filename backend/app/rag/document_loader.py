from __future__ import annotations

import logging
import re
from pathlib import Path

from app.rag.exceptions import KnowledgeDocumentError
from app.rag.schemas import KnowledgeSection

DOCUMENT_TYPES = {
    "dispatch_rules": "dispatch_rule",
    "cold_chain_rules": "cold_chain",
    "cargo_transport_rules": "cargo_rule",
    "exception_handling": "exception_manual",
}
SUPPORTED_SUFFIXES = {".md", ".txt"}
_HEADING_PATTERN = re.compile(r"^#{1,6}\s+(.+?)\s*$")
logger = logging.getLogger(__name__)


class KnowledgeDocumentLoader:
    def load_directory(self, directory: str | Path) -> list[KnowledgeSection]:
        root = Path(directory)
        if not root.is_dir():
            raise KnowledgeDocumentError(f"知识库文档目录不存在：{root}")
        sections: list[KnowledgeSection] = []
        for path in sorted(root.iterdir(), key=lambda item: item.name):
            if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES:
                try:
                    sections.extend(self.load_file(path))
                except KnowledgeDocumentError as exc:
                    logger.warning(
                        "Skipping invalid knowledge document %s: %s", path.name, exc
                    )
        if not sections:
            raise KnowledgeDocumentError("知识库目录中没有可用的 Markdown 或 TXT 文档")
        return sections

    def load_file(self, path: str | Path) -> list[KnowledgeSection]:
        document_path = Path(path)
        if document_path.suffix.lower() not in SUPPORTED_SUFFIXES:
            raise KnowledgeDocumentError(
                f"不支持的知识文档格式：{document_path.suffix}"
            )
        try:
            text = document_path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise KnowledgeDocumentError(
                f"无法读取知识文档：{document_path.name}"
            ) from exc
        text = self._clean(text)
        if not text:
            raise KnowledgeDocumentError(f"知识文档为空：{document_path.name}")
        document_type = DOCUMENT_TYPES.get(document_path.stem, "system_manual")
        if document_path.suffix.lower() == ".txt":
            return [self._section(document_path, document_type, "正文", text)]
        return self._markdown_sections(document_path, document_type, text)

    def _markdown_sections(
        self, path: Path, document_type: str, text: str
    ) -> list[KnowledgeSection]:
        sections: list[KnowledgeSection] = []
        heading = "正文"
        buffer: list[str] = []
        for line in text.splitlines():
            match = _HEADING_PATTERN.match(line)
            if match:
                self._append_section(sections, path, document_type, heading, buffer)
                heading = match.group(1).strip()
                buffer = []
            else:
                buffer.append(line)
        self._append_section(sections, path, document_type, heading, buffer)
        return sections or [self._section(path, document_type, "正文", text)]

    def _append_section(
        self,
        sections: list[KnowledgeSection],
        path: Path,
        document_type: str,
        heading: str,
        lines: list[str],
    ) -> None:
        content = self._clean("\n".join(lines))
        if content:
            sections.append(self._section(path, document_type, heading, content))

    @staticmethod
    def _section(
        path: Path, document_type: str, heading: str, content: str
    ) -> KnowledgeSection:
        return KnowledgeSection(
            content=content,
            source=path.name,
            document_name=path.stem,
            document_id=path.name,
            document_type=document_type,
            section=heading,
        )

    @staticmethod
    def _clean(text: str) -> str:
        lines = [line.rstrip() for line in text.replace("\r\n", "\n").split("\n")]
        cleaned = "\n".join(lines).strip()
        return re.sub(r"\n{3,}", "\n\n", cleaned)
