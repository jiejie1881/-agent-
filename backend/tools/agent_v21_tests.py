"""Full current-suite run with explicit historical fixture paths and a time bound."""
import os
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parents[2]
out = root / 'docs/evidence/agent-v21-final-20261108-1705'
for name in ('forensics', 'replay'):
    (out / name).mkdir(exist_ok=True)
env = dict(os.environ, R0_EVIDENCE_ROOT=str(out / 'forensics'),
    RAG_BATCH1_WORKSPACE=str(out / 'replay'),
    PYTHONPATH=str(root / 'docs/evidence/langsmith-ls11-final-20261103-01'))
with (out / 'backend-full.log').open('w', encoding='utf-8') as log:
    try:
        result = subprocess.run([sys.executable, '-m', 'pytest', '-vv', '-p', 'no:cacheprovider',
            '--continue-on-collection-errors', '--tb=short', '-o', 'faulthandler_timeout=90',
            '--junitxml=' + str(out / 'backend-full.xml')], cwd=root / 'backend', env=env,
            stdout=log, stderr=subprocess.STDOUT, timeout=900)
        (out / 'backend-full-exit.txt').write_text(str(result.returncode), encoding='utf-8')
    except subprocess.TimeoutExpired:
        (out / 'backend-full-exit.txt').write_text('TIMEOUT_900_SECONDS', encoding='utf-8')
