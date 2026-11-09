"""Count exact unique collected test node IDs, preserving failed first attempts."""
import collections
import json
from pathlib import Path
import re

out = Path(__file__).resolve().parents[2] / 'docs/evidence/agent-v21-final-20261108-1705'
nodes = {line.strip() for line in (out / 'collection-current.log').read_text(encoding='utf-8').splitlines()
         if line.startswith('tests/') and '::' in line}
outcomes, attempts = {}, []
for name in ('backend-full.log', 'backend-remaining.log'):
    for node, status in re.findall(r'^(tests/.*?)\s+(PASSED|FAILED|SKIPPED|ERROR|XFAIL|XPASS)',
        (out / name).read_text(encoding='utf-8', errors='replace'), re.MULTILINE):
        attempts.append((node, status, name))
        # Failed/error attempts remain visible even if an overlapping retry passed.
        if outcomes.get(node) not in {'FAILED', 'ERROR'}:
            outcomes[node] = status
current = {node: status for node, status in outcomes.items() if node in nodes}
summary = {'collection_count': len(nodes), 'unique_result_count': len(current),
    'status_counts': dict(collections.Counter(current.values())),
    'missing_nodes': sorted(nodes - outcomes.keys()),
    'extra_nodes': sorted(outcomes.keys() - nodes), 'raw_attempt_count': len(attempts),
    'duplicate_attempt_count': len(attempts)-len(outcomes),
    'failed_nodes': {node: status for node, status in outcomes.items() if status in {'FAILED', 'ERROR'}},
    'note': 'Full first segment timed out at 900 seconds. Continuation selected unfinished nodes; counts deduplicate exact IDs. Failures are not replaced by later passes. Separate targeted rechecks are not added.'}
(out / 'TEST_SUMMARY.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({k: summary[k] for k in ('collection_count', 'unique_result_count', 'status_counts', 'duplicate_attempt_count', 'missing_nodes')}, ensure_ascii=False))
