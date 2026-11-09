"""Summarize this run from terminal results. Keep dedicated reruns separate."""
import collections
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree


ROOT = Path(__file__).resolve().parent
REVISION = '49392f272c882ce464f5c4de990f7eb653a0b9f9'


def collect(paths):
    counts = collections.Counter(passed=0, failure=0, error=0, skipped=0)
    failures = []
    skips = []
    for path in paths:
        for case in ElementTree.parse(path).iter('testcase'):
            node = case.get('classname', '') + '::' + case.get('name', '')
            bad = next((item for item in case if item.tag in {'failure', 'error', 'skipped'}), None)
            result = bad.tag if bad is not None else 'passed'
            counts[result] += 1
            if result == 'skipped':
                skips.append({'node': node, 'reason': bad.get('message', '')})
            elif result != 'passed':
                failures.append({'node': node, 'status': result, 'evidence': path.name})
    return {'counts': dict(counts), 'skipped_cases': skips, 'failed_cases': failures}


def read(path):
    return path.read_text(encoding='utf-8-sig', errors='replace')


def main():
    generated = datetime.now(timezone.utc).isoformat()
    host = [ROOT / f'final-{i}.xml' for i in range(4)]
    missing = [item.name for item in host if not item.is_file()]
    base = ROOT / 'backend-baseline.xml'
    backend = {
        'revision': REVISION, 'generated_at_utc': generated,
        'final_host': collect([item for item in host if item.is_file()]),
        'missing_final_reports': missing,
        'baseline': collect([base]) if base.is_file() else {'status': 'INCOMPLETE'},
        'rag_batch2_guarded': collect([ROOT / 'batch2-final/junit.xml']),
        'landlock_forensics': {'passed': 24, 'evidence': 'forensics-final.log'},
        'mysql_chroma': {'passed': 13, 'evidence': 'mysql-memory-pytest.log',
                         'overlaps_host_skips': 'test_agent_memory_core.py'},
        'specialist': {'passed': 149, 'evidence': 'backend-specialist.xml', 'counted_in_total': False},
        'dependency_recheck': {'passed': 93, 'evidence': 'dependency-recheck.xml', 'counted_in_total': False},
    }
    assert re.search(r'Ran 24 tests', read(ROOT / 'forensics-final.log'))
    assert re.search(r'\bOK\b', read(ROOT / 'forensics-final.log'))
    assert re.search(r'\b13 passed\b', read(ROOT / 'mysql-memory-pytest.log'))
    combined = collections.Counter(backend['final_host']['counts'])
    combined.update(backend['rag_batch2_guarded']['counts'])
    combined.update({'passed': 24})
    mysql_replaced = sum('test_agent_memory_core' in case['node']
                         for case in backend['final_host']['skipped_cases'])
    if mysql_replaced == 13:
        combined['skipped'] -= 13
        combined['passed'] += 13
    backend['combined_disjoint_results'] = dict(combined)
    backend['mysql_host_skip_replaced_count'] = mysql_replaced if mysql_replaced == 13 else 0
    (ROOT / 'BACKEND_TEST_SUMMARY.json').write_text(json.dumps(backend, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    lines = read(ROOT / 'frontend-tests.log')
    counts = {key: int(re.search(rf'(?m)^. {key} (\d+)', lines).group(1))
              for key in ('tests', 'pass', 'fail', 'skipped')}
    build = read(ROOT / 'frontend-build.log')
    assert 'vue-tsc -b' in build and 'built in' in build
    (ROOT / 'FRONTEND_TEST_SUMMARY.json').write_text(json.dumps({
        'revision': REVISION, 'generated_at_utc': generated, 'counts': counts,
        'type_check': 'PASS', 'build': 'PASS',
        'evidence': ['frontend-tests.log', 'frontend-build.log'],
    }, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'backend': backend['combined_disjoint_results'], 'missing': missing,
                      'frontend': counts}, ensure_ascii=False))


if __name__ == '__main__':
    main()
