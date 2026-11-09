"""Continue uncompleted test nodes after the bounded full run, without double counting."""
import os
from pathlib import Path
import re
import subprocess
import sys

root = Path(__file__).resolve().parents[2]
out = root / 'docs/evidence/agent-v21-final-20261108-1705'
env = dict(os.environ, R0_EVIDENCE_ROOT=str(out / 'forensics'),
    RAG_BATCH1_WORKSPACE=str(out / 'replay'),
    PYTHONPATH=str(root / 'docs/evidence/langsmith-ls11-final-20261103-01'))
collected = subprocess.run([sys.executable, '-m', 'pytest', '--collect-only', '-q', '-p', 'no:cacheprovider'],
    cwd=root / 'backend', env=env, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=120)
(out / 'collection-current.log').write_text(collected.stdout + collected.stderr, encoding='utf-8')
nodes = [line.strip() for line in collected.stdout.splitlines() if line.startswith('tests/') and '::' in line]
completed = set(re.findall(r'^(tests/.*?)\s+(?:PASSED|FAILED|SKIPPED|ERROR|XFAIL|XPASS)',
    (out / 'backend-full.log').read_text(encoding='utf-8', errors='replace'), re.MULTILINE))
remaining = [node for node in nodes if node not in completed]
args = out / 'remaining-nodes.txt'
args.write_text('\n'.join(remaining), encoding='utf-8')
print(f'collected={len(nodes)} completed={len(completed)} remaining={len(remaining)}')
if remaining:
    with (out / 'backend-remaining.log').open('w', encoding='utf-8') as log:
        try:
            result = subprocess.run([sys.executable, '-m', 'pytest', '@' + str(args), '-vv', '-p', 'no:cacheprovider',
                '--tb=short', '-o', 'faulthandler_timeout=90', '--junitxml=' + str(out / 'backend-remaining.xml')],
                cwd=root / 'backend', env=env, stdout=log, stderr=subprocess.STDOUT, timeout=1800)
            (out / 'backend-remaining-exit.txt').write_text(str(result.returncode), encoding='utf-8')
        except subprocess.TimeoutExpired:
            (out / 'backend-remaining-exit.txt').write_text('TIMEOUT_1800_SECONDS', encoding='utf-8')
