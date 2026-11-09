import re
import unicodedata
from difflib import SequenceMatcher
from app.repositories.ai_operations_repository import AIOperationsRepository


def normalize(value):
    return re.sub(r"[\s·•_-]", "", unicodedata.normalize("NFKC", value or "")).casefold()


class DemandEntityMatchingService:
    def __init__(self, repository: AIOperationsRepository):
        self.repository = repository

    def match(self, text, entities):
        if not text:
            return {"id": None, "method": "MISSING", "candidates": []}
        for method, test in [
            ("EXACT", lambda row: row.name == text),
            ("NORMALIZED", lambda row: normalize(row.name) == normalize(text)),
            ("EXISTING_CODE", lambda row: normalize(row.code) == normalize(text)),
        ]:
            matches = [row for row in entities if test(row)]
            if matches:
                return {"id": matches[0].id if len(matches) == 1 else None, "method": method if len(matches) == 1 else "AMBIGUOUS", "candidates": [{"id": r.id, "name": r.name, "code": r.code} for r in matches]}
        ranked = sorted(entities, key=lambda r: SequenceMatcher(None, normalize(text), normalize(r.name)).ratio(), reverse=True)
        candidates = [{"id": r.id, "name": r.name, "code": r.code} for r in ranked if SequenceMatcher(None, normalize(text), normalize(r.name)).ratio() >= .35][:5]
        return {"id": None, "method": "MANUAL_REQUIRED", "candidates": candidates}
