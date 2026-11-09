from __future__ import annotations

import re
from functools import lru_cache

import jieba
from rank_bm25 import BM25Okapi
from app.rag.reference_policy import lexical_eligible

BUSINESS_WORDS = (
    "派车",
    "未分配",
    "载重",
    "回单",
    "签收",
    "出勤",
    "草稿",
    "幂等",
    "配送需求",
    "资源冲突",
    "人工确认",
    "线路白名单",
    "超重",
    "补传",
    "调度员",
    "温控",
    "派车方案",
    "自动派车",
    "智能派车",
    "未分配需求",
    "车辆出勤",
    "司机任务",
    "人工调整",
    "方案发布",
    "地形限制",
    "车辆载重",
    "线路管理",
    "签收回单",
    "异常工作台",
    "审计日志",
)

LEXICAL_POLICY = 'jieba-search-v2'


@lru_cache(maxsize=1)
def tokenizer():
    engine = jieba.Tokenizer()
    for word in BUSINESS_WORDS:
        engine.add_word(word)
    return engine


def tokenize(text):
    normalized = text.lower()
    identifiers = re.findall(
        r"/[a-z0-9_/-]+|\b[a-z][a-z0-9]*(?:[_-][a-z0-9]+)*\b|\bv\d+\b|\b\d{2,}\b",
        normalized,
    )
    words = [
        word.lower() for word in tokenizer().cut(normalized) if re.search(r"[\w]", word)
    ]
    return words + [identifier for identifier in identifiers if identifier not in words]


def tokenize_search(text):
    """Keep compound subwords for lexical recall and preserve exact identifiers.

    No query labels, synonym answers or document-specific boosts are used.
    The embedding adapter and existing tokenize() contract remain unchanged.
    """
    words = [word.lower() for word in tokenizer().cut_for_search(text.lower())
             if re.search(r'\w', word)]
    return words + [word for word in tokenize(text) if word not in words]


class BM25Index:
    def __init__(self, chunks, *, reference_policy='legacy'):
        self.reference_policy = reference_policy
        self.chunks = chunks
        self.tokens = [tokenize_search(c.content + " " + c.section) for c in chunks]
        self.index = BM25Okapi(self.tokens) if chunks else None

    def search(self, query, allowed_ids, limit):
        if self.index is None:
            return []
        words = tokenize_search(query)
        scores = self.index.get_scores(words)
        # Zero/negative IDF still represents lexical overlap in tiny collections.
        hits = [
            (c, float(score))
            for c, tokens, score in zip(self.chunks, self.tokens, scores)
            if c.chunk_id in allowed_ids and lexical_eligible(query, words, tokens, policy=self.reference_policy)
        ]
        return sorted(hits, key=lambda item: (-item[1], item[0].chunk_id))[:limit]
