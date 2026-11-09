"""Approved update for one attested manual candidate; never publishes business work."""
import argparse
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
import secrets
import shutil
import subprocess
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx

from stage82_manual_lab import D, ROOT, cmd
from candidate_backup_validation import archive_entries, verify_archive_isolated

RUN = 'd13c7ce19c3c'
PROJECT = 'codex-stage82-manual-e08d3456a45a'
OUT = ROOT / 'docs/evidence' / ('same-day-candidate-update-' + RUN)
WORK = ROOT / 'backend/tmp' / ('same-day-candidate-update-' + RUN)
BACKUP = ROOT / 'backups' / ('candidate-update-' + RUN)
STATE = ROOT / 'docs/evidence' / PROJECT / 'state.json'
COMPOSE = ROOT / 'backend/tmp' / PROJECT / 'compose.json'
FILES = ['app/services/dispatch_plan_service.py', 'app/repositories/driver_task_repository.py']
FOLDERS = ['/app/uploads', '/app/rag_data', '/app/agent_data']


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def sha(data):
    return hashlib.sha256(data).hexdigest()


class Blob(ctypes.Structure):
    _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]


def protect(data, decrypt=False):
    """Windows current-user DPAPI; no plaintext key or plaintext backup on disk."""
    array = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
    source = Blob(len(data), array)
    target = Blob()
    crypt = ctypes.windll.crypt32
    function = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    function.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                         ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    function.restype = wintypes.BOOL
    assert function(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)), 'DPAPI failed'
    try:
        return ctypes.string_at(target.data, target.size)
    finally:
        free = ctypes.windll.kernel32.LocalFree
        free.argtypes = [ctypes.c_void_p]
        free.restype = ctypes.c_void_p
        free(ctypes.cast(target.data, ctypes.c_void_p))


def inspect_owned(state):
    assert state['project'] == PROJECT
    result = {}
    for item in state['containers']:
        x = json.loads(cmd('inspect', item['id']))[0]
        assert x['Config']['Labels']['codex.run_id'] == state['run']
        assert x['Config']['Labels']['com.docker.compose.project'] == PROJECT
        assert sorted(item['volumes']) == sorted(m['Name'] for m in x['Mounts'] if m['Type'] == 'volume')
        result[item['role']] = x
    return result


def env_of(container):
    return dict(v.split('=', 1) for v in container['Config']['Env'] if '=' in v)


def db_identity(api):
    script = """import os,json,sqlite3;from contextlib import closing;from sqlalchemy import create_engine,text
with create_engine(os.environ['DATABASE_URL']).connect() as c:
 c.exec_driver_sql('START TRANSACTION READ ONLY')
 identity=list(c.execute(text('SELECT @@server_uuid,DATABASE(),CURRENT_USER()')).one())
 version=c.execute(text('SELECT version_num FROM alembic_version')).scalar()
 demands=[list(r) for r in c.execute(text('SELECT id,date,period,quantity,status FROM delivery_demands WHERE id IN (9,10) ORDER BY id'))];c.rollback()
with closing(sqlite3.connect('file:/app/agent_data/yuelu-manual-model-budget.sqlite3?mode=ro',uri=True,timeout=3)) as c:
 flight=c.execute("SELECT COUNT(*) FROM calls WHERE status='IN_FLIGHT'").fetchone()[0]
print(json.dumps({'identity':identity,'migration':version,'demands':demands,'in_flight':flight},default=str))
"""
    value = json.loads(cmd('exec', api, 'python', '-B', '-c', script))
    assert value['identity'] == ['73b3b9ec-cc35-11f1-8dc8-16d56d05098c', 'codex_stage8_browser', 'stage8_user@%']
    assert value['migration'] == '20261015_28' and value['in_flight'] == 0
    return value


def mysql(cid, password, user, database, query=None, payload=None, dump=False):
    env = os.environ.copy()
    env['MYSQL_PWD'] = password
    args = [D, 'exec', '-i', '-e', 'MYSQL_PWD', cid]
    if dump:
        args += ['mysqldump', '-u', user, '--single-transaction', '--skip-lock-tables',
                 '--no-tablespaces', '--hex-blob', '--skip-comments', '--set-gtid-purged=OFF',
                 '--column-statistics=0', '--default-character-set=utf8mb4', database]
    else:
        args += ['mysql', '-u', user, '--default-character-set=utf8mb4', '-N', '-B', '-r']
        if database:
            args += ['-D', database]
        if query is not None:
            args += ['-e', query]
    p = subprocess.run(args, env=env, input=payload, capture_output=True, timeout=90, check=False)
    if p.returncode:
        raise RuntimeError('MySQL CLI failed; sensitive output suppressed')
    return p.stdout


def quote_identifier(value):
    return '`' + value.replace('`', '``') + '`'


def fingerprint(cid, password, user, database):
    tables = mysql(cid, password, user, database, 'SHOW TABLES').decode().splitlines()
    result = {}
    for table in tables:
        columns = [line.split('\t')[0] for line in mysql(cid, password, user, database,
                    'SHOW COLUMNS FROM ' + quote_identifier(table)).decode().splitlines()]
        values = ','.join(f'IF({quote_identifier(c)} IS NULL,NULL,HEX(CAST({quote_identifier(c)} AS CHAR)))' for c in columns)
        rows = sorted(mysql(cid, password, user, database,
            f'SELECT JSON_ARRAY({values}) FROM {quote_identifier(table)}').splitlines())
        schema = mysql(cid, password, user, database, 'SHOW CREATE TABLE ' + quote_identifier(table))
        result[table] = {'rows': len(rows), 'sha256': sha(b'\n'.join(rows)), 'columns': columns,
                         'schema_sha256': sha(schema)}
    return result


VOLUME_SCRIPT = r"""import io,os,sys,tarfile,sqlite3,time;from pathlib import Path;from contextlib import closing
root=Path(sys.argv[1]);buf=io.BytesIO();sqlite_names=set()
with tarfile.open(fileobj=buf,mode='w') as tar:
 for path in sorted(root.rglob('*')):
  if path.name.endswith(('-wal','-shm')) and str(path)[:-4] in sqlite_names:continue
  info=tar.gettarinfo(str(path),arcname=path.relative_to(root).as_posix())
  if path.is_symlink():
   assert path.resolve().is_relative_to(root.resolve());tar.addfile(info);continue
  if path.is_file():
   data=path.read_bytes()
   if data.startswith(b'SQLite format 3\x00'):
    started=time.monotonic()
    def progress(*args):
     if time.monotonic()-started>15:raise TimeoutError('SQLite backup deadline')
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=3)) as source,closing(sqlite3.connect(':memory:')) as target:
     source.backup(target,pages=128,progress=progress,sleep=0.01);data=target.serialize()
     assert target.execute('PRAGMA integrity_check').fetchall()==[('ok',)]
    sqlite_names.add(str(path))
   info.size=len(data);tar.addfile(info,io.BytesIO(data))
  else:tar.addfile(info)
sys.stdout.buffer.write(buf.getvalue())
"""


def archive(api, folder):
    return cmd('exec', api, 'python', '-B', '-c', VOLUME_SCRIPT, folder)


def archive_manifest(data, *, verifier=verify_archive_isolated):
    # SQLite deserialize cannot open WAL-header snapshots. Validate the original
    # bytes as restored files on an isolated tmpfs; never patch source headers.
    expected = archive_entries(data)
    restored = verifier(data)
    assert restored['restore'] == 'PASS' and restored['temporary_copy_removed']
    assert set(restored['entries']) == set(expected)
    for name, row in expected.items():
        assert all(restored['entries'][name][key] == value for key, value in row.items())
        if 'sqlite_header' in row:
            assert restored['entries'][name]['sqlite_integrity'] == 'ok'
    return restored['entries']


def image_manifest(image):
    script = "from pathlib import Path;import hashlib,json;print(json.dumps({p.relative_to('/app').as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for d in ['app','alembic/versions'] for p in Path('/app',d).rglob('*.py')}))"
    return json.loads(cmd('run', '--rm', '--network', 'none', '--label', 'codex.update='+RUN,
                          '--entrypoint', 'python', image, '-B', '-c', script))


def prepare(*, backup_only=False):
    state = json.loads(STATE.read_text())
    containers = inspect_owned(state)
    baseline = json.loads((OUT / 'preflight.json').read_text())
    assert all(containers[k]['Image'] == baseline['candidate'][k]['image'] for k in containers)
    assert sha(COMPOSE.read_bytes()) == baseline['compose_sha256']
    assert db_identity(containers['backend']['Id'])['in_flight'] == 0
    if not backup_only:
        WORK.mkdir(exist_ok=False)
    BACKUP.mkdir(exist_ok=False)
    assert subprocess.run(['git','check-ignore',str(BACKUP/'database.sql.dpapi')],
                          capture_output=True, check=False).returncode == 0
    from sqlalchemy.engine import make_url
    url = make_url(env_of(containers['backend'])['DATABASE_URL'])
    user, password, database = url.username, url.password, url.database
    dbid = containers['mysql']['Id']
    before = fingerprint(dbid, password, user, database)
    extra = mysql(dbid, password, user, database,
        "SELECT (SELECT COUNT(*) FROM information_schema.ROUTINES WHERE ROUTINE_SCHEMA=DATABASE()) + "
        "(SELECT COUNT(*) FROM information_schema.EVENTS WHERE EVENT_SCHEMA=DATABASE()) + "
        "(SELECT COUNT(*) FROM information_schema.TRIGGERS WHERE TRIGGER_SCHEMA=DATABASE())")
    assert extra.strip() == b'0', 'Unreviewed routines/events/triggers: stop backup'
    sql = mysql(dbid, password, user, database, dump=True)
    assert b'CREATE TABLE' in sql and b'alembic_version' in sql
    payloads = {'database.sql': sql}
    manifests = {}
    for folder in FOLDERS:
        name = folder.rsplit('/',1)[1] + '.tar'
        payloads[name] = archive(containers['backend']['Id'], folder)
        manifests[name] = archive_manifest(payloads[name])
    assert fingerprint(dbid, password, user, database) == before, 'Business writes occurred during backup'
    for folder in FOLDERS:
        name = folder.rsplit('/',1)[1] + '.tar'
        assert archive_manifest(archive(containers['backend']['Id'], folder)) == manifests[name], 'Volume changed during backup'
    backup_info = {}
    for name, payload in payloads.items():
        encrypted = protect(payload)
        path = BACKUP / (name + '.dpapi')
        assert not path.exists()
        path.write_bytes(encrypted)
        assert protect(path.read_bytes(), decrypt=True) == payload
        backup_info[name] = {'path': str(path), 'plaintext_bytes': len(payload),
                             'sha256': sha(payload), 'encrypted_sha256': sha(encrypted)}
    save(OUT/'backup.json', {'status':'BACKUP_CAPTURED_RESTORE_PENDING', 'encryption':'Windows current-user DPAPI; no plaintext key/files',
         'files':backup_info, 'volumes':manifests, 'database':before, 'stable_during_capture':True})
    # Explicitly approved disposable restore: no network, no host ports, no shared volumes.
    restore_name = 'codex-candidate-restore-' + RUN
    root_password = secrets.token_urlsafe(40)
    env = os.environ.copy();env['MYSQL_ROOT_PASSWORD'] = root_password
    cid = volume = None
    try:
        assert not cmd('ps','-aq','--filter','name=^/'+restore_name+'$').strip()
        p = subprocess.run([D,'run','-d','--network','none','--name',restore_name,'--label','codex.restore='+RUN,
                            '-e','MYSQL_ROOT_PASSWORD',containers['mysql']['Image']],env=env,
                            capture_output=True,timeout=60,check=True)
        cid = p.stdout.decode().strip();x=json.loads(cmd('inspect',cid))[0]
        assert x['Config']['Labels']['codex.restore']==RUN and set(x['NetworkSettings']['Networks'])=={'none'}
        assert len(x['Mounts'])==1 and x['Mounts'][0]['Type']=='volume';volume=x['Mounts'][0]['Name']
        assert volume not in [m['Name'] for v in containers.values() for m in v['Mounts'] if m['Type']=='volume']
        save(OUT/'restore-resource.json',{'id':cid,'volume':volume,'network':'none','shared_volumes':False})
        deadline=time.monotonic()+120
        while True:
            try:
                mysql(cid,root_password,'root',None,'SELECT 1');break
            except RuntimeError:
                if time.monotonic()>=deadline:raise TimeoutError('Disposable restore MySQL not ready') from None
                time.sleep(2)
        clone_uuid=mysql(cid,root_password,'root',None,'SELECT @@server_uuid').decode().strip()
        assert clone_uuid!=state['mysql_uuid']
        mysql(cid,root_password,'root',None,'CREATE DATABASE '+quote_identifier(database)+' CHARACTER SET utf8mb4')
        mysql(cid,root_password,'root',database,payload=protect((BACKUP/'database.sql.dpapi').read_bytes(),decrypt=True))
        assert fingerprint(cid,root_password,'root',database)==before
        save(OUT/'restore.json',{'status':'PASS','clone_uuid':clone_uuid,'source_uuid':state['mysql_uuid'],
             'tables':len(before),'rows':sum(v['rows'] for v in before.values()),'all_table_rows_and_columns_equal':True,
             'volume_archives_dpapi_roundtrip':True,'sqlite_integrity_checked':True})
    finally:
        if cid:
            x=json.loads(cmd('inspect',cid))[0]
            assert x['Config']['Labels']['codex.restore']==RUN and [m['Name'] for m in x['Mounts']]==[volume]
            cmd('rm','-f','-v',cid)
            assert not cmd('ps','-aq','--filter','id='+cid).strip()
            assert volume not in cmd('volume','ls','-q').decode().splitlines()
            save(OUT/'restore-cleanup.json',{'status':'PASS','container_absent':True,'volume_absent':True})
    if backup_only:
        save(OUT/'backup-gate.json', {'status':'PASS', 'backup':str(BACKUP),
             'database_restore':'PASS', 'volume_restore':'PASS',
             'service_update':'NOT RUN', 'image_build':'NOT RUN'})
        print(json.dumps({'status':'BACKUP_GATE_PASS','evidence':str(OUT),'service_update':'NOT RUN'}))
        return
    # Build is strictly two files on the unchanged existing runtime.
    ctx=WORK/'context';ctx.mkdir()
    for relative in FILES:
        source=ROOT/'backend'/relative
        assert sha(source.read_bytes())==baseline['source']['backend/'+relative]
        target=ctx/relative;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,target)
    old_image=containers['backend']['Image']
    tags=json.loads(cmd('image','inspect',old_image))[0]['RepoTags']
    base=next(t for t in tags if t.startswith(PROJECT+'/backend:'))
    assert json.loads(cmd('image','inspect',base))[0]['Id']==old_image
    dockerfile='FROM '+base+'\n'+''.join('COPY --chown=app:app '+f+' /app/'+f+'\n' for f in FILES)+'LABEL codex.update="'+RUN+'"\n'
    (ctx/'Dockerfile').write_text(dockerfile,encoding='utf-8')
    tag=PROJECT+'/backend:replacement-'+RUN
    started=time.monotonic()
    p=subprocess.run([D,'build','--pull=false','--network=none','-t',tag,str(ctx)],capture_output=True,timeout=180,check=False)
    (OUT/'build.log').write_bytes(p.stdout+p.stderr)
    assert p.returncode==0,'Image build failed: service untouched'
    new=json.loads(cmd('image','inspect',tag))[0]['Id']
    expected={p.relative_to(ROOT/'backend').as_posix():sha(p.read_bytes()) for d in ['app','alembic/versions'] for p in (ROOT/'backend'/d).rglob('*.py')}
    assert image_manifest(new)==expected
    assert image_manifest(old_image)!=expected
    candidate={'new_image':new,'old_image':old_image,'tag':tag,'files':expected,
        'compose_sha256':baseline['compose_sha256'],'backup':str(BACKUP),'database_fingerprint':before,
        'volume_manifests':manifests,'build_exit':p.returncode,'build_seconds':round(time.monotonic()-started,3)}
    save(OUT/'prepared.json',candidate)
    print(json.dumps({'status':'PREPARED','image':new,'backup_restore':'PASS','evidence':str(OUT)}))


def switch():
    candidate=json.loads((OUT/'prepared.json').read_text())
    assert json.loads((OUT/'restore.json').read_text())['status']=='PASS'
    state=json.loads(STATE.read_text());before=inspect_owned(state);baseline=json.loads((OUT/'preflight.json').read_text())
    assert before['backend']['Image']==candidate['old_image']
    assert sha(COMPOSE.read_bytes())==candidate['compose_sha256']
    identity=db_identity(before['backend']['Id'])
    from sqlalchemy.engine import make_url
    u=make_url(env_of(before['backend'])['DATABASE_URL'])
    assert fingerprint(before['mysql']['Id'],u.password,u.username,u.database)==candidate['database_fingerprint']
    for folder in FOLDERS:
        assert archive_manifest(archive(before['backend']['Id'],folder))==candidate['volume_manifests'][folder.rsplit('/',1)[1]+'.tar']
    assert all(sha((ROOT/p).read_bytes())==v for p,v in baseline['source'].items())
    assert image_manifest(candidate['new_image'])==candidate['files']
    env=env_of(before['backend']);assert env['RUN_MIGRATIONS']=='false' and env['AGENT_WRITE_TOOLS_ENABLED']=='false'
    volumes={m['Destination']:m['Name'] for m in before['backend']['Mounts'] if m['Type']=='volume'}
    declarations={};mounts=[]
    for index,folder in enumerate(FOLDERS):
        alias='preserved_'+str(index);declarations[alias]={'external':True,'name':volumes[folder]}
        mounts.append({'type':'volume','source':alias,'target':folder})
    override={'services':{'backend':{'image':candidate['new_image'],'volumes':mounts}},'volumes':declarations}
    override_path=WORK/'update.override.json';save(override_path,override)
    # Render only in RAM: actual secrets are neither logged nor copied to files.
    def compose(*args):
        return cmd('compose','-p',PROJECT,'-f',str(COMPOSE),'-f',str(override_path),*args,timeout=120)
    rendered=json.loads(compose('config','--format','json'))
    assert rendered['services']['backend']['environment']['DATABASE_URL']==env['DATABASE_URL']
    assert str(rendered['services']['backend']['environment']['RUN_MIGRATIONS']).lower()=='false'
    assert str(rendered['services']['backend']['environment']['AGENT_WRITE_TOOLS_ENABLED']).lower()=='false'
    for alias in declarations:
        assert rendered['volumes'][alias]['name']==declarations[alias]['name']
    record={'status':'UPDATING','operations':[],'frontend_reloaded':False}
    def log(operation):
        record['operations'].append({'operation':operation,'exit':0,'time':datetime.now(ZoneInfo('Asia/Shanghai')).isoformat()});save(OUT/'deployment.json',record)
    def update_state():
        new_id=compose('ps','-q','backend').decode().strip()
        next(v for v in state['containers'] if v['role']=='backend')['id']=new_id
        inspect_owned(state)
        return new_id
    stopped=False
    try:
        # Backups, actual restore validation and build all PASS before any stop.
        cmd('stop','--time','30',before['backend']['Id'],timeout=60);stopped=True;log('stop exact attested candidate backend')
        compose('up','-d','--no-build','--no-deps','--pull','never','backend');log('compose up backend only; external existing volumes pinned')
        new_id=update_state();new=json.loads(cmd('inspect',new_id))[0]
        assert new['Image']==candidate['new_image'] and env_of(new)==env
        assert set(new['NetworkSettings']['Networks'])==set(before['backend']['NetworkSettings']['Networks'])
        # First use an internal read-only health check; no model/provider invoked.
        health_script="import urllib.request;print(urllib.request.urlopen('http://127.0.0.1:8000/health/ready',timeout=3).status)"
        for _ in range(25):
            try:
                if cmd('exec',new_id,'python','-B','-c',health_script).strip()==b'200':break
            except RuntimeError:pass
            time.sleep(1)
        else:raise RuntimeError('New candidate not ready')
        log('new backend internal readiness HTTP200')
        # Reuse cached front upstream if still healthy, otherwise graceful reload only.
        response=httpx.get('http://127.0.0.1:62112/health/ready',timeout=5)
        if response.status_code!=200:
            frontend=before['frontend']['Id']
            assert json.loads(cmd('inspect',frontend))[0]['Config']['Labels']['com.docker.compose.project']==PROJECT
            cmd('exec',frontend,'nginx','-t');log('candidate nginx syntax test')
            cmd('exec',frontend,'nginx','-s','reload');record['frontend_reloaded']=True;log('candidate nginx graceful reload; no config change')
            for _ in range(15):
                if httpx.get('http://127.0.0.1:62112/health/ready',timeout=5).status_code==200:break
                time.sleep(1)
            else:raise RuntimeError('Candidate frontend upstream failed')
        assert db_identity(new_id)==identity
        assert fingerprint(before['mysql']['Id'],u.password,u.username,u.database)==candidate['database_fingerprint']
        # Verify loaded function source identity without importing the model adapter.
        code="import inspect,json,hashlib;import app.services.dispatch_plan_service as s;import app.repositories.driver_task_repository as d;print(json.dumps({m.__file__:hashlib.sha256(open(m.__file__,'rb').read()).hexdigest() for m in [s,d]}))"
        loaded=json.loads(cmd('exec',new_id,'python','-B','-c',code))
        assert sorted(loaded.values())==sorted(baseline['source']['backend/'+f] for f in FILES)
        after=inspect_owned(state)
        assert after['frontend']['Id']==before['frontend']['Id'] and after['mysql']['Id']==before['mysql']['Id']
        state['same_day_replacement_update']={'image':candidate['new_image'],'evidence':str(OUT),'override':str(override_path)}
        save(STATE,state)
        record.update(status='PASS',old_backend=before['backend']['Id'],new_backend=new_id,
            old_image=candidate['old_image'],new_image=candidate['new_image'],loaded_source=loaded,
            database_identity=identity,mysql_and_frontend_container_unchanged=True,
            all_database_rows_unchanged=True,paid_model_requests=0,manual_acceptance='NOT RUN')
        log('identity, source, all-table fingerprint and no-business-writes checks passed')
        print(json.dumps({'status':'PASS','url':'http://127.0.0.1:62112/login','evidence':str(OUT),'new_backend':new_id}))
    except Exception as error:
        record.update(status='FAIL',failure_type=type(error).__name__)
        save(OUT/'deployment.json',record)
        if stopped:
            # Software only: same database and volumes, no snapshot restoration.
            override['services']['backend']['image']=candidate['old_image'];save(override_path,override)
            compose('up','-d','--no-build','--no-deps','--pull','never','backend')
            update_state();save(STATE,state)
            cmd('exec',before['frontend']['Id'],'nginx','-t')
            cmd('exec',before['frontend']['Id'],'nginx','-s','reload')
            record['software_rollback']='completed; database/volumes retained'
            save(OUT/'deployment.json',record)
        raise


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase',choices=['backup','prepare','switch'])
    args=parser.parse_args()
    if args.phase in {'backup','prepare'}:prepare(backup_only=args.phase=='backup')
    else:switch()
