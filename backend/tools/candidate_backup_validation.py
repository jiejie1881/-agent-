"""Restore archive copies before validating SQLite; never attach a live volume."""

from contextlib import closing
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
from uuid import uuid4


VALIDATION_IMAGE = 'sha256:42b4f56af979d97649fa7f511b0239134780e8b9d7562a56045915d1866a5a05'

WINDOWS_RESERVED_STEMS = {'CON', 'PRN', 'AUX', 'NUL', 'CONIN$', 'CONOUT$'} | {
    prefix + digit for prefix in ('COM', 'LPT') for digit in '123456789¹²³'
}


def portable_archive_key(name):
    """Reject device names and aliases before any disposable-copy writes."""
    path = PurePosixPath(name)
    if (not name or not path.parts or path.is_absolute() or '..' in path.parts
            or path.as_posix() != name):
        raise ValueError('Unsafe or duplicate archive member')
    for part in path.parts:
        if (part.endswith((' ', '.'))
                or any(ord(char) < 32 or char in '<>:"\\|?*' for char in part)
                or part.split('.', 1)[0].rstrip(' ').upper() in WINDOWS_RESERVED_STEMS):
            raise ValueError('Unsafe nonportable archive member')
    return '/'.join(part.casefold() for part in path.parts)


def sqlite_fingerprint(db):
    """Hash typed cell values without emitting business contents."""
    result = {}
    for name, sql in db.execute("SELECT name,sql FROM sqlite_schema WHERE type='table' ORDER BY name"):
        quoted = '"' + name.replace('"', '""') + '"'
        rows = []
        for row in db.execute('SELECT * FROM ' + quoted):
            typed = [(type(v).__name__, v.hex() if isinstance(v, bytes) else v) for v in row]
            rows.append(json.dumps(typed, ensure_ascii=True, separators=(',', ':')))
        result[name] = {'rows': len(rows), 'sha256': hashlib.sha256('\n'.join(sorted(rows)).encode()).hexdigest(),
                        'schema_sha256': hashlib.sha256((sql or '').encode()).hexdigest()}
    return result


def archive_entries(data):
    """Inspect an uncompressed TAR; reject unsafe or ambiguous restores."""
    result, portable_members = {}, {}
    with tarfile.open(fileobj=io.BytesIO(data), mode='r:') as archive:
        for member in archive.getmembers():
            path = PurePosixPath(member.name)
            if (not member.name or path.is_absolute() or '..' in path.parts or '\\' in member.name
                    or ':' in member.name or path.as_posix() != member.name or member.name in result):
                raise ValueError('Unsafe or duplicate archive member')
            if not (member.isfile() or member.isdir()):
                raise ValueError('Archive links and special files need separate review')
            key = portable_archive_key(member.name)
            if key in portable_members:
                raise ValueError('Unsafe duplicate archive alias')
            portable_members[key] = member.isfile()
            row = {'size': member.size, 'mode': member.mode, 'uid': member.uid, 'gid': member.gid,
                   'mtime': member.mtime, 'type': member.type.decode()}
            if member.isfile():
                content = archive.extractfile(member).read()
                if len(content) != member.size:
                    raise ValueError('Truncated archive member')
                row['sha256'] = hashlib.sha256(content).hexdigest()
                if content.startswith(b'SQLite format 3\x00'):
                    row['sqlite_header'] = list(content[18:20])
            result[member.name] = row
    for key in portable_members:
        parts = key.split('/')
        if any(portable_members.get('/'.join(parts[:index]))
               for index in range(1, len(parts))):
            raise ValueError('Unsafe archive file/directory conflict')
    return result


def restore_archive(data, temporary_root):
    """Only write copies under a fresh temporary directory, then remove them.

    Production payloads use an isolated container tmpfs. Local tests use synthetic
    bytes. A WAL-mode online-backup snapshot is valid as a file, even though
    SQLite's deserialize API does not support its WAL header.
    """
    entries = archive_entries(data)
    with tempfile.TemporaryDirectory(prefix='restore-', dir=temporary_root) as directory:
        root = Path(directory)
        with tarfile.open(fileobj=io.BytesIO(data), mode='r:') as archive:
            for member in archive.getmembers():
                path = root.joinpath(*PurePosixPath(member.name).parts)
                path.parent.mkdir(parents=True, exist_ok=True)
                if member.isdir():
                    path.mkdir(exist_ok=True)
                else:
                    with path.open('xb') as target:
                        target.write(archive.extractfile(member).read())
        # Verify every restored byte before SQLite is allowed to open the copy.
        for name, row in entries.items():
            path = root.joinpath(*PurePosixPath(name).parts)
            if row['type'] in {tarfile.REGTYPE.decode(), tarfile.AREGTYPE.decode()}:
                content = path.read_bytes()
                if hashlib.sha256(content).hexdigest() != row['sha256']:
                    raise ValueError('Restored file digest mismatch')
                if 'sqlite_header' in row:
                    # No source sidecars: Online Backup API already merged the
                    # committed WAL state into this standalone snapshot.
                    if any(Path(str(path) + suffix).exists() for suffix in ('-wal', '-shm')):
                        raise ValueError('SQLite snapshot unexpectedly depends on sidecars')
                    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=3)) as db:
                        integrity = db.execute('PRAGMA integrity_check').fetchall()
                        if integrity != [('ok',)]:
                            raise ValueError('Restored SQLite integrity check failed')
                        row['sqlite_tables'] = sqlite_fingerprint(db)
                        row['sqlite_integrity'] = 'ok'
                    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=3)) as db:
                        if sqlite_fingerprint(db) != row['sqlite_tables']:
                            raise ValueError('SQLite reopen consistency check failed')
                    if hashlib.sha256(path.read_bytes()).hexdigest() != row['sha256']:
                        raise ValueError('SQLite check altered archived database bytes')
        # Check modes and ownership on the disposable copy, not a mounted volume.
        for name, row in reversed(list(entries.items())):
            path = root.joinpath(*PurePosixPath(name).parts)
            os.utime(path, (row['mtime'], row['mtime']))
            if os.name != 'nt':
                os.chmod(path, row['mode'])
                os.chown(path, row['uid'], row['gid'])
                stat = path.stat()
                if stat.st_mode & 0o7777 != row['mode']:
                    raise ValueError('Restored mode mismatch')
                if (stat.st_uid, stat.st_gid) != (row['uid'], row['gid']):
                    raise ValueError('Restored ownership mismatch')
                if abs(stat.st_mtime - row['mtime']) > 0.000001:
                    raise ValueError('Restored timestamp mismatch')
        result = {'entries': entries, 'restore': 'PASS', 'sqlite_version': sqlite3.sqlite_version,
                  'file_hashes_equal': True, 'metadata_verified': os.name != 'nt'}
    if root.exists():
        raise RuntimeError('Temporary restored copy was not removed')
    result['temporary_copy_removed'] = True
    return result


def verify_archive_isolated(data, *, image=VALIDATION_IMAGE, record=None):
    """File-based restore in RAM; no network, secrets, bind mounts, or volumes."""
    from stage82_manual_lab import D, cmd

    token = uuid4().hex
    label = 'codex.backup-wal-verify'
    cid = None
    metadata = {'run': token, 'image': image, 'cleanup': 'NOT RUN'}
    if record:
        record(metadata)
    try:
        image_info = json.loads(cmd('image', 'inspect', image))[0]
        if image_info['Id'] != image or image_info['Config'].get('Volumes'):
            raise ValueError('Validation image identity/implicit volumes unsafe')
        cid = cmd('create', '-i', '--network', 'none', '--read-only', '--user', '0:0',
                  '--tmpfs', '/verify:rw,noexec,nosuid,nodev,size=67108864,mode=0700',
                  '--cap-drop', 'ALL', '--cap-add', 'CHOWN', '--cap-add', 'FOWNER',
                  '--cap-add', 'DAC_OVERRIDE', '--security-opt', 'no-new-privileges',
                  '--label', label + '=' + token, '--entrypoint', 'python', image,
                  '-B', '-c', Path(__file__).read_text(encoding='utf-8'), '--restore-stdin').decode().strip()
        inspected = json.loads(cmd('inspect', cid))[0]
        mounts_safe = all(m['Type'] == 'tmpfs' and m['Destination'] == '/verify' for m in inspected['Mounts'])
        if (inspected['Config']['Labels'].get(label) != token or not mounts_safe
                or inspected['HostConfig']['NetworkMode'] != 'none'
                or not inspected['HostConfig']['ReadonlyRootfs']
                or inspected['HostConfig'].get('PortBindings')):
            raise ValueError('Disposable validation container isolation failed')
        metadata.update(container=cid, isolated=True, no_shared_mounts=True, network='none')
        if record:
            record(metadata)
        process = subprocess.run([D, 'start', '-a', '-i', cid], input=data,
                                 capture_output=True, timeout=60, check=False)
        metadata['exit'] = process.returncode
        state = json.loads(cmd('inspect', cid))[0]['State']
        if process.returncode or state['ExitCode'] or state['Running']:
            metadata['container_exit'] = state['ExitCode']
            try:
                failure = json.loads(process.stderr)
                metadata['failure'] = {k: failure[k] for k in ('type', 'line')}
            except (ValueError, KeyError):
                metadata['failure'] = 'Unstructured output suppressed'
            raise RuntimeError('Disposable archive restore failed; payload/output suppressed')
        result = json.loads(process.stdout)
        if not result['metadata_verified']:
            raise RuntimeError('Linux ownership/mode verification was not executed')
        return result
    finally:
        if cid:
            inspected = json.loads(cmd('inspect', cid))[0]
            mounts_safe = all(m['Type'] == 'tmpfs' and m['Destination'] == '/verify' for m in inspected['Mounts'])
            if inspected['Config']['Labels'].get(label) != token or not mounts_safe:
                raise RuntimeError('Cleanup ownership uncertain; stopped without removing resources')
            cmd('rm', '-f', cid)
            if cmd('ps', '-aq', '--filter', 'id=' + cid).strip():
                raise RuntimeError('Disposable validation container cleanup failed')
            metadata['cleanup'] = 'PASS'
        if record:
            record(metadata)


if __name__ == '__main__':
    if sys.argv[1:] != ['--restore-stdin']:
        raise SystemExit('Only --restore-stdin is supported inside the isolated verifier')
    try:
        print(json.dumps(restore_archive(sys.stdin.buffer.read(), '/verify')))
    except Exception as error:
        import traceback
        frames = traceback.extract_tb(error.__traceback__)
        print(json.dumps({'type': type(error).__name__, 'line': frames[-1].lineno}), file=sys.stderr)
        sys.exit(1)
