"""Offline-only CLI. No SDK client, database, model HTTP or persistent index.

Creates a NEW output directory. Existing evidence is never overwritten.
Replay uses complete rankings, not a new retrieval/model experiment.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.evaluation.metrics import compare, fingerprint, performance, retrieval
from app.rag.evaluation import (DeterministicHashEmbedding, EvalCase,
                                resolve_expected_cases, resolve_source_section_cases)

ROOT = Path(__file__).resolve().parents[2]
VERSIONS = ('model', 'prompt', 'agent', 'embedding', 'reranker', 'retrieval', 'dataset')


def write(path, value):
    with path.open('x', encoding='utf-8') as stream:
        stream.write(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False))


def prepare_dataset(path, chunks):
    rows = json.loads(path.read_text(encoding='utf-8-sig'))
    if not rows or len({r['id'] for r in rows}) != len(rows):
        raise ValueError('Empty dataset or duplicate IDs')
    if 'expected' in rows[0]:
        cases = resolve_expected_cases(rows, chunks)
    else:
        cases = resolve_source_section_cases(rows, chunks)
    return cases, hashlib.sha256(path.read_bytes()).hexdigest()


def run_memory(path, folder, version):
    from app.rag import bm25_index
    from app.rag.document_loader import KnowledgeDocumentLoader
    from app.rag.splitter import KnowledgeTextSplitter
    from app.rag.fusion import reciprocal_rank_fusion
    from app.rag.schemas import KnowledgeSearchResult
    import jieba
    # Own tokenizer/cache only; do not touch existing global cache/index.
    tokenizer = jieba.Tokenizer()
    tokenizer.tmp_dir = str(folder)
    for word in bm25_index.BUSINESS_WORDS:
        tokenizer.add_word(word)
    original = bm25_index.tokenizer
    bm25_index.tokenizer = lambda: tokenizer
    try:
        sections = KnowledgeDocumentLoader().load_directory(ROOT/'backend/knowledge_base')
        chunks = KnowledgeTextSplitter(800, 120).split(sections)
        chunks = [c.model_copy(update={'chunk_id': c.chunk_id or f'{c.source}:{c.chunk_index}'}) for c in chunks]
        cases, digest = prepare_dataset(path, chunks)
        corpus = fingerprint([c.model_dump() for c in chunks])
        lexical = bm25_index.BM25Index(chunks)
        embedder = DeterministicHashEmbedding()
        vectors = [embedder.embed_query(c.content) for c in chunks]
        reports = []
        for strategy in ('bm25', 'vector', 'hybrid', 'rrf'):
            rows = []
            for case in cases:
                start = perf_counter()
                # Same historical public-only policy: private requests fail closed.
                allowed = {c.chunk_id for c in chunks if c.access_scope == 'public'} if case.access_scope == 'public' else set()
                lex = lexical.search(case.query, allowed, 20)
                query = embedder.embed_query(case.query)
                cosines = sorted([(c, sum(a*b for a,b in zip(query, vector)))
                                  for c, vector in zip(chunks, vectors) if c.chunk_id in allowed],
                                 key=lambda x: (-x[1], x[0].chunk_id))[:20]
                ranked = [KnowledgeSearchResult(**c.model_dump(), score=max(0., min(1., score)))
                          for c, score in cosines if score >= .35]
                fused = reciprocal_rank_fusion(ranked, lex, version=corpus, constant=60)
                found = [c.chunk_id for c, _ in lex] if strategy == 'bm25' else [c.chunk_id for c in ranked] if strategy == 'vector' else [c.chunk_id for c in fused]
                elapsed = (perf_counter() - start) * 1000
                rows.append(dict(id=case.id, status='COMPLETED', retrieved=found, total_ms=elapsed,
                                 retrieval_ms=elapsed, vector_candidates=[c.chunk_id for c in ranked],
                                 bm25_candidates=[c.chunk_id for c,_ in lex],
                                 fusion=[dict(id=c.chunk_id, vector_rank=c.vector_rank, bm25_rank=c.bm25_rank,
                                              score=c.rrf_score) for c in fused]))
            reports.append(build_report(cases, rows, digest, corpus, strategy,
                                        version | {'retrieval': strategy}, scope='OFFLINE_HASH_DIAGNOSTIC'))
        reports.append(dict(status='NOT RUN', strategy='rrf+reranker', reason='No authorized real/local reranker used; no fabricated scores'))
        return reports
    finally:
        bm25_index.tokenizer = original


def build_report(cases, rows, digest, corpus, strategy, versions, scope, ks=(1, 3, 4, 5)):
    return dict(schema='ls2-v1', metric_version='frozen-retrieval-plus-explicit-observations-v1',
                dataset_sha256=digest, corpus_sha256=corpus, scope=scope, ks=list(ks),
                strategy=strategy, versions=versions, status='PARTIAL',
                retrieval=retrieval(cases, rows, ks), performance=performance(rows),
                context_relevance_kind='QREL_RELEVANT_FRACTION; not semantic answer sufficiency',
                cases=rows, gate='REPORT_ONLY; historical quality gates not changed')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', type=Path, default=ROOT/'backend/tests/fixtures/stage3_rag_holdout.json')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--replay', type=Path, help='JSON {cases, observations, corpus_sha256, strategy, scope, versions}')
    parser.add_argument('--baseline', type=Path)
    for key in VERSIONS:
        parser.add_argument('--'+key+'-version', default='UNKNOWN')
    args = parser.parse_args()
    out = args.output.resolve()
    if not out.is_relative_to(ROOT/'docs/evidence'):
        parser.error('Output must be a NEW project evidence subdirectory')
    out.mkdir(exist_ok=False, parents=True)
    versions = {key: getattr(args, key+'_version') for key in VERSIONS}
    if args.replay:
        payload = json.loads(args.replay.read_text(encoding='utf-8-sig'))
        cases = [EvalCase(c['id'], c['query'], frozenset(c['relevant_ids']), c.get('access_scope','public')) for c in payload['cases']]
        digest = fingerprint(payload['cases'])
        reports = [build_report(cases, payload['observations'], digest, payload['corpus_sha256'],
                                payload['strategy'], versions, 'OFFLINE_OBSERVATION_REPLAY')]
    else:
        reports = run_memory(args.dataset.resolve(), out, versions)
    write(out/'RESULTS.json', reports)
    comparison = compare(reports[0], reports[1]) if len(reports)>1 else {'status':'NOT RUN'}
    if args.baseline:
        base = json.loads(args.baseline.read_text(encoding='utf-8-sig'))
        comparison = compare(base[0] if isinstance(base,list) else base, reports[0])
    write(out/'COMPARISON.json', comparison)
    text = '# LS-2 offline benchmark\n\nScope: offline memory retrieval or observation replay. No real models or cloud.\n\n'
    text += '|Strategy|Recall@5|MRR@5|nDCG@5|No-answer candidates|Status|\n|---|---:|---:|---:|---:|---|\n'
    for r in reports:
        m = r.get('retrieval',{}).get('at_k',{}).get('5',{})
        text += f"|{r['strategy']}|{m.get('recall_at_k','UNKNOWN')}|{m.get('mrr','UNKNOWN')}|{m.get('ndcg','UNKNOWN')}|{r.get('retrieval',{}).get('no_answer',{}).get('false_candidate_count','UNKNOWN')}|{r['status']}|\n"
    text += '\nHybrid and RRF are aliases for the existing equal-weight fusion, not independent algorithms. Hash vector is not semantic Embedding. TTFT/cost/answer quality remain UNKNOWN without observations.\n'
    (out/'REPORT.md').write_text(text,encoding='utf-8')
    write(out/'SHA256_MANIFEST.json', {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(out.iterdir()) if p.is_file()})
    print(json.dumps({'output':str(out),'reports':len(reports),'cloud':'NOT RUN','models':'NOT RUN'}))


if __name__ == '__main__':
    main()
