"""Versioned negative-evidence checks, never positive semantic entailment.

No question IDs, source-specific boosts, model scores or learned thresholds.
The generic words below are query scaffolding, not a topic blacklist.
"""
import re
from dataclasses import dataclass

POLICY_VERSION = 'reference-v1'
MODES = {'legacy', POLICY_VERSION}
SCAFFOLDING = frozenset({'一个', '这个', '那个', '这些', '那些', '具体', '相关', '一下'})
NORMATIVE = ('规则','规定','规范','制度','原则','手册','必须','应该','应当','要求')
TIME_QUESTION = re.compile(r'几点|何时|什么时候|什么时间|到货时间|签收时间|完成时间|收到时间')


def meaningful(tokens):
    return {t for t in tokens if t not in SCAFFOLDING and
            (len(t)>1 or re.search(r'[a-z0-9]',t) or t in {'吨','米','趟','元'})}


def instance_event_request(query, tokens):
    # Explicit object code + observed-event timestamp, not general rule advice.
    # ASCII boundaries deliberately allow adjacent Chinese text (TASK-09的),
    # where Unicode \b or tokenizer punctuation may lose the object code.
    codes = re.findall(r'(?<![a-z0-9_])[a-z][a-z0-9_-]*\d[a-z0-9_-]*(?![a-z0-9_])', query.lower())
    return bool(codes and TIME_QUESTION.search(query) and not any(x in query for x in NORMATIVE))


@dataclass(frozen=True)
class ReferenceDecision:
    reason: str
    refuse: bool
    policy: str = POLICY_VERSION


def decide(query, hits, *, policy=POLICY_VERSION):
    if policy not in MODES:raise ValueError('Unknown reference policy')
    if policy=='legacy':return ReferenceDecision('LEGACY_UNASSESSED',False,policy)
    from app.rag.bm25_index import tokenize_search
    words=tokenize_search(query)
    if instance_event_request(query,words):
        return ReferenceDecision('INSTANCE_EVENT_REQUIRES_BUSINESS_FACT',True)
    if not hits:return ReferenceDecision('NO_EVIDENCE',True)
    content=meaningful(words)
    if not content:return ReferenceDecision('QUERY_HAS_NO_CONTENT_TERMS',True)
    all_tokens=set()
    for hit in hits:
        text=hit.get('content') if isinstance(hit,dict) else getattr(hit,'content',None)
        if not isinstance(text,str):return ReferenceDecision('INSUFFICIENT_METADATA',False)
        section=hit.get('section','') if isinstance(hit,dict) else getattr(hit,'section','')
        all_tokens.update(tokenize_search(text+' '+section))
    if set(words)&all_tokens and not content&meaningful(all_tokens):
        return ReferenceDecision('SCAFFOLDING_ONLY_OVERLAP',True)
    return ReferenceDecision('CANDIDATES_NOT_SEMANTICALLY_VERIFIED',False)


def lexical_eligible(query, query_tokens, document_tokens, *, policy=POLICY_VERSION):
    if policy not in MODES:raise ValueError('Unknown reference policy')
    if policy=='legacy':return bool(set(query_tokens)&set(document_tokens))
    return not instance_event_request(query,query_tokens) and bool(meaningful(query_tokens)&meaningful(document_tokens))


def refusal_message(reason):
    if reason=='INSTANCE_EVENT_REQUIRES_BUSINESS_FACT':
        return '该问题需要核验具体业务对象的实际事件时间，规则文档不能确认。请使用有权限的业务查询或补充可核验记录。'
    return '当前候选仅有泛指词或缺少可用证据，无法从知识库确认答案。请明确问题或补充资料。'
