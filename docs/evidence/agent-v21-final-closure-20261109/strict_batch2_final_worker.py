"""Recreate the original no-SQL/no-network guard, not a dummy attestation."""
import json,os,sys
from pathlib import Path
E=Path(__file__).resolve().parent;R=E.parents[2];W=E/(sys.argv[1] if len(sys.argv)>1 else 'batch2-final')
assert W.is_dir()
sys.path[:0]=[str(E),str(R/'backend')];os.chdir(W)
for key in list(os.environ):
    if key.startswith(('AGENT_','RAG_','OPENAI_','LANGSMITH_','LANGCHAIN_','MODEL_','DB_','JWT_','OTEL_','HF_')) or any(s in key.upper() for s in ('API_KEY','PASSWORD','SECRET','TOKEN','DATABASE','PROXY')):
        os.environ.pop(key)
os.environ.update(DATABASE_URL='blocked-by-ls12://no-database',MODEL_BUDGET_ENABLED='false',
    JWT_SECRET_KEY='synthetic-ls12-strict-at-least-32-characters',
    LANGSMITH_TRACING='false',LANGCHAIN_TRACING_V2='false',HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',
    PYTHONDONTWRITEBYTECODE='1',PYTEST_DISABLE_PLUGIN_AUTOLOAD='1',RAG_BATCH1_WORKSPACE=str(W),
    TMP=str(W),TEMP=str(W),TMPDIR=str(W))
from path_boundary import within
denied=[]
def refuse(reason):
    denied.append(reason)
    raise PermissionError('LS12 strict guard: '+reason)
def owned(path):
    if not isinstance(path,int) and not within(Path(os.fsdecode(path)).absolute().resolve(),W.resolve()):
        refuse('write_outside_workspace')
def audit(event,args):
    if event=='open':
        path,mode,flags=args
        if flags & (os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_APPEND|os.O_TRUNC):owned(path)
        if not isinstance(path,int):
            p=Path(os.fsdecode(path))
            if p.name.startswith('.env') or p.suffix.lower() in {'.db','.db3','.sqlite','.sqlite3'}:refuse('database_or_env_file')
    elif event in {'os.mkdir','os.remove','os.rmdir','os.chmod','os.utime'}:owned(args[0])
    elif event in {'os.rename','os.link','os.symlink'}:owned(args[0]);owned(args[1])
    elif event.startswith('sqlite3.'):refuse('SQL')
    elif event in {'subprocess.Popen','os.system','os.startfile','os.posix_spawn'}:refuse('child_process')
    elif event in {'socket.connect','socket.sendto','socket.getaddrinfo','socket.bind'}:refuse('network')
sys.addaudithook(audit)
class NoNative:
    def find_spec(self,fullname,path=None,target=None):
        if fullname.split('.')[0] in {'chromadb','onnxruntime','torch','transformers','sentence_transformers','pymysql','MySQLdb','psycopg','psycopg2','duckdb'}:
            refuse('native_provider_import:'+fullname)
sys.meta_path.insert(0,NoNative())
from memory_collection import install
install(W)
from app.rag import versioned_index
original_read=versioned_index.read_text_shared
original_replace=versioned_index.atomic_replace
original_manifest=versioned_index.VersionedIndex._read
diagnostics=[]
def safe_read(path):
    owned(path)
    try:return original_read(path)
    except Exception as error:
        import traceback
        diagnostics.append(dict(stage='pointer_read',type=type(error).__name__,traceback=traceback.format_exc()))
        raise
def manifest_read(self,path):
    try:return original_manifest(self,path)
    except Exception as error:
        import traceback
        diagnostics.append(dict(stage='manifest_read',type=type(error).__name__,traceback=traceback.format_exc()))
        raise
versioned_index.VersionedIndex._read=manifest_read
def safe_replace(source,target):owned(source);owned(target);return original_replace(source,target)
versioned_index.read_text_shared=safe_read
versioned_index.atomic_replace=safe_replace
import pytest
class Guard:
    @pytest.fixture
    def batch2_guard_attestation(self):
        return {'workspace':str(W),'SQL':'DENY','network':'DENY','subprocess':'DENY'}
    def pytest_sessionfinish(self,session,exitstatus):
        (W/'GUARD.json').write_text(json.dumps(dict(denied=denied,no_SQL=True,no_network=True,
            no_child_processes=True,native_chroma='NOT RUN',vector='Python memory protocol',diagnostics=diagnostics),indent=2),encoding='utf-8')
names=['test_rag_batch2_pointer.py','test_rag_batch2_ranking.py','test_rag_batch2_safety.py']
selection=[str(R/'backend/tests/test_rag_batch2_pointer.py')+'::test_readers_pin_versions_during_twenty_reads_and_four_switches[1]'] if len(sys.argv)>1 else [str(R/'backend/tests'/n) for n in names]
sys.exit(pytest.main([*selection,'-q','--noconftest','-p','no:cacheprovider',
    '--basetemp',str(W/'tmp'),'--log-file',str(W/'pytest.log'),'--junitxml',str(W/'junit.xml')],plugins=[Guard()]))
