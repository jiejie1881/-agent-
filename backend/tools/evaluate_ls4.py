"""One offline closure entry: fresh memory RAG + verified Agent observation replay.

No cloud SDK, real models, database access or business service initialization.
Exit 2 is a BLOCKED quality gate, never an implicit business deployment block.
"""
from pathlib import Path
import argparse,hashlib,json,sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.evaluation.metrics import agent,performance,compare
from app.evaluation.closure import answer_outcomes,trace_quality,admission,JUDGE_PROMPT,JUDGE_VERSION
from evaluate_ls2 import run_memory
ROOT=Path(__file__).resolve().parents[2]
AGENT_SOURCE_FILES=('backend/app/agent/agent_service.py','backend/app/agent/graph_workflow.py',
                    'backend/app/agent/task_workflow.py','backend/app/agent/task_plan.py',
                    'backend/app/agent/knowledge_tools.py','backend/app/rag/evidence_binding.py',
                    'backend/app/rag/answer_contract.py',
                    'backend/app/rag/semantic_judge.py','backend/app/rag/semantic_contract.py',
                    'backend/app/core/config.py')


def agent_source_version(root=ROOT):
    payload={name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in AGENT_SOURCE_FILES}
    return hashlib.sha256(json.dumps(payload,sort_keys=True).encode()).hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--source-evidence',type=Path,default=ROOT/'docs/evidence/langsmith-ls3-20261102-01')
    parser.add_argument('--dataset',type=Path,default=ROOT/'backend/tests/fixtures/stage3_rag_holdout.json')
    parser.add_argument('--answers',type=Path)
    parser.add_argument('--trace',type=Path)
    args=parser.parse_args()
    folder=args.output.resolve()
    if not folder.is_relative_to(ROOT/'docs/evidence'):parser.error('New project evidence directory required')
    source=args.source_evidence.resolve()
    manifest=json.loads((source/'SHA256_MANIFEST.json').read_text(encoding='utf-8'))
    def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
    for base,entries in [(source,manifest['files']),(ROOT,manifest['source_files'])]:
        for name,digest in entries.items():
            target=(base/name).resolve()
            if not target.is_relative_to(base) or sha(target)!=digest:raise ValueError('Evidence/source integrity mismatch')
    folder.mkdir(parents=True,exist_ok=False)
    labels=json.loads((ROOT/'backend/tests/fixtures/ls2_agent_benchmark.json').read_text(encoding='utf-8'))
    observed=json.loads((source/'AGENT_BEFORE_AFTER.json').read_text(encoding='utf-8'))['observations']
    agent_metrics=agent(labels,observed)
    versions=dict(model='NOT_RUN',prompt=sha(ROOT/'backend/app/agent/prompts/system_prompt.py'),agent=sha(ROOT/'backend/app/agent/task_plan.py'),embedding='HASH192_NOT_SEMANTIC',reranker='NOT_RUN',retrieval='memory-RRF60',dataset=sha(args.dataset))
    # Replayed observations belong to their sealed source run, not today's
    # workflow. A task_plan-only hash missed graph and evidence-gate changes.
    versions['agent']='REPLAY:'+sha(source/'SHA256_MANIFEST.json')
    versions['current_agent_source']=agent_source_version()
    rag=run_memory(args.dataset,folder,versions)
    # Reviewed answer behaviour cannot be inferred from retrieval candidates.
    payload=json.loads(args.answers.read_text(encoding='utf-8')) if args.answers else dict(cases=[dict(id=r['id'],answerable=bool(r.get('expected')) if 'expected' in r else bool(r.get('source'))) for r in json.loads(args.dataset.read_text(encoding='utf-8'))],observations=[])
    expected={r['id']:bool(r.get('expected')) if 'expected' in r else bool(r.get('source')) for r in json.loads(args.dataset.read_text(encoding='utf-8'))}
    if {c['id']:c['answerable'] for c in payload['cases']} != expected:
        raise ValueError('Answer review dataset/labels mismatch')
    answers=answer_outcomes(payload['cases'],payload['observations'])
    trace_payload=json.loads(args.trace.read_text(encoding='utf-8')) if args.trace else dict(runs=[],required_nodes=['intent','planner','tools','finish'])
    trace=trace_quality(trace_payload['runs'],set(trace_payload['required_nodes'])|{'intent','planner','tools','finish'})
    gate=admission(agent_metrics,answers,trace)
    result=dict(schema='ls4-closure-v1',scope='OFFLINE_HASH_PLUS_SYNTHETIC_AGENT_REPLAY',versions=versions,
                agent=agent_metrics,rag=rag,answers=answers,trace=trace,gate=gate,
                performance=performance(observed),comparison=compare(rag[0],rag[2]),
                judge=dict(version=JUDGE_VERSION,prompt=JUDGE_PROMPT,status='NOT RUN'),
                real_models='NOT RUN',cloud='NOT RUN',source_manifest_sha256=sha(source/'SHA256_MANIFEST.json'))
    (folder/'RESULTS.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    (folder/'REPORT.md').write_text('# LS4 unified offline evaluation\n\nGate: '+gate['status']+'\n\nAgent is verified LS3 synthetic-service replay, not new model execution. RAG is fresh BM25/Hash/RRF memory execution. Answers, real models and cloud remain NOT RUN when missing.\n\n'+ '\n'.join(f"- {c['name']}: {c['status']} ({c['actual']})" for c in gate['checks']),encoding='utf-8')
    (folder/'SHA256_MANIFEST.json').write_text(json.dumps({p.name:sha(p) for p in folder.iterdir() if p.is_file()},indent=2),encoding='utf-8')
    print(json.dumps(dict(gate=gate['status'],output=str(folder),real_models='NOT RUN')))
    return 0 if gate['status']=='PASS' else 2


if __name__=='__main__':raise SystemExit(main())
