"""R0 only: isolated synthetic validation and fail-closed ledger forensics.

No application imports, credentials, business services or source SQLite connections.
Run with --help. The live acquisition gate deliberately requires independent host
quiescence evidence; Docker's stopped consumers alone cannot satisfy that gate.
"""
from __future__ import annotations

import argparse
import ctypes
from datetime import datetime, timezone, timedelta
import errno
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import platform
import sqlite3
import stat
import subprocess
import sys
import unittest
from uuid import uuid4

HEAD = "8276cc2e165951513b084ba5a1a6abd68ae96d72"
IMAGE = "sha256:42b4f56af979d97649fa7f511b0239134780e8b9d7562a56045915d1866a5a05"
VOLUME = "24eb8c9bc44f41da277977580c5897bc4bfc536ca9c0270eea06aa6dbf498863"
OWNER = "5902aae0c11697603dd05ac1a3791671353f32cd29835472e3fbd4cee469a075"
CONTAINERS = (
    OWNER,
    "2c2a477ae10aef766bef284d95b9afa8def19873a2bca9a031081f7af3eeb70b",
    "801ad934503a9c1ca39a438707901e4617b0cc4389610d7b8d6f1bb796c397c1",
    "699a6b434d0624d8c772e70985458b5d22019d13a8cb2539118d9213dfe96be5",
    "e562cf5fc1ba377bf8b05135756b3015f2f2602598093608e43c0eb7caa44360",
    "1b183c65428f2f04cc95be5e739ccf8d0838b89323d6803e13aa427c360ec081",
)
TOOL = "backend/tools/read_budget_ledger_forensics.py"
TEST = "backend/tests/test_budget_ledger_forensics.py"
EVIDENCE = "docs/evidence/local-ready-budget-forensics-20261026"
LEDGER = "yuelu-manual-model-budget.sqlite3"
SOURCE_NAMES = (LEDGER, LEDGER + "-wal", LEDGER + "-shm", LEDGER + "-journal")
MAX_BYTES = 16 * 1024 * 1024
META = ("st_dev", "st_ino", "st_mode", "st_nlink", "st_uid", "st_gid",
        "st_size", "st_atime_ns", "st_mtime_ns", "st_ctime_ns")


class GateBlocked(RuntimeError):
    """A missing safety precondition; never retry with weaker settings."""


def now():
    return datetime.now(timezone(timedelta(hours=8))).isoformat()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def metadata(value):
    return {key: getattr(value, key) for key in META}


def save_new(path, value):
    """Evidence files are append-only/new; never silently replace an artifact."""
    path = Path(path)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def safe_directory(path, root, *, create=False):
    path, root = Path(path).absolute(), Path(root).resolve(strict=True)
    if ".." in path.parts or not path.is_relative_to(root):
        raise GateBlocked("evidence_path_outside_approved_root")
    for ancestor in reversed((path, *path.parents)):
        if not ancestor.exists():
            continue
        info = ancestor.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise GateBlocked("symlink_or_reparse_point_in_evidence_path")
    if path.resolve(strict=False) != path:
        raise GateBlocked("noncanonical_evidence_path")
    if create:
        path.mkdir(exist_ok=False)
    if path.resolve(strict=True) != path:
        raise GateBlocked("noncanonical_evidence_path")
    return path


def strict_open(path, *, directory=False, opener=None):
    """No O_CREAT, no write flags, no ordinary-read fallback, no source SQL."""
    if sys.platform != "linux" or not hasattr(os, "O_NOATIME"):
        raise GateBlocked("O_NOATIME_unavailable")
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NOATIME
    if directory:
        flags |= os.O_DIRECTORY
    try:
        return (opener or os.open)(path, flags)
    except OSError as exc:
        raise GateBlocked("safe_open_failed_errno_" + str(exc.errno)) from None


def safe_read(path, *, opener=None, reader=None):
    fd = strict_open(path, opener=opener)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise GateBlocked("source_not_single_link_regular_file")
        if before.st_size > MAX_BYTES:
            raise GateBlocked("source_too_large")
        chunks, size = [], 0
        while True:
            data = (reader or os.read)(fd, 65536)
            if not data:
                break
            size += len(data)
            if size > MAX_BYTES:
                raise GateBlocked("source_grew_too_large")
            chunks.append(data)
        after = os.fstat(fd)
        if metadata(before) != metadata(after) or size != before.st_size:
            raise GateBlocked("source_metadata_changed_during_read")
        return b"".join(chunks), metadata(before)
    finally:
        os.close(fd)


def acquire_files(source, destination, *, quiescence_proven):
    """Copies only a closed, attested file group. SQL is never run on source.

    The caller must prove *all* writers quiescent outside this function. Stable
    repeated hashes supplement that proof; they do not manufacture it.
    """
    if quiescence_proven is not True:
        raise GateBlocked("all_source_writers_quiescent_NOT_PROVEN")
    source, destination = Path(source), Path(destination)
    directory = strict_open(source, directory=True)
    try:
        directory_before = metadata(os.fstat(directory))
        existence, first = {}, {}
        for name in SOURCE_NAMES:
            try:
                value = os.stat(name, dir_fd=directory, follow_symlinks=False)
            except FileNotFoundError:
                existence[name] = None
                continue
            if not stat.S_ISREG(value.st_mode):
                raise GateBlocked("source_link_or_special_file")
            existence[name] = metadata(value)
        if existence[LEDGER] is None:
            raise GateBlocked("source_ledger_missing")
        if existence[LEDGER + "-journal"] is not None:
            raise GateBlocked("rollback_journal_present_requires_separate_review")
        for name, before in existence.items():
            if before is None:
                continue
            data, seen = safe_read(source / name)
            if seen != before:
                raise GateBlocked("source_changed_before_read")
            first[name] = (data, before)
        for name in SOURCE_NAMES:
            try:
                current = metadata(os.stat(name, dir_fd=directory, follow_symlinks=False))
            except FileNotFoundError:
                current = None
            if current != existence[name]:
                raise GateBlocked("source_group_changed")
            if current is not None:
                again, seen = safe_read(source / name)
                if seen != current or digest(again) != digest(first[name][0]):
                    raise GateBlocked("source_second_read_changed")
        if directory_before != metadata(os.fstat(directory)):
            raise GateBlocked("source_directory_metadata_changed")
        destination.mkdir(exist_ok=False)
        result = {}
        for name, (data, seen) in first.items():
            with (destination / name).open("xb") as target:
                target.write(data)
            result[name] = {"sha256": digest(data), "bytes": len(data), "metadata": seen}
        return {"files": result, "source_directory_metadata": directory_before}
    finally:
        os.close(directory)


def inspect_copy(path):
    """Fixed inherited query subset. Only a private evidence copy is allowed."""
    path = Path(path).resolve(strict=True)
    evidence = Path(os.environ["R0_EVIDENCE_ROOT"]).resolve(strict=True)
    if not path.is_relative_to(evidence) or path.name != LEDGER:
        raise GateBlocked("SQL_target_not_approved_private_copy")
    queries = (
        "PRAGMA database_list", "PRAGMA journal_mode", "PRAGMA integrity_check",
        "PRAGMA table_list", "PRAGMA user_version", "PRAGMA application_id",
        "SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name",
        "PRAGMA table_info(gate)", "PRAGMA table_info(calls)",
        "PRAGMA table_info(sqlite_sequence)", "PRAGMA index_list(gate)",
        "PRAGMA index_list(calls)", "PRAGMA foreign_key_list(gate)",
        "PRAGMA foreign_key_list(calls)",
        "SELECT id,model,expires,stopped FROM gate ORDER BY id",
        "SELECT status,COUNT(*) FROM calls GROUP BY status ORDER BY status",
        "SELECT COUNT(*) FROM calls WHERE status='IN_FLIGHT'",
        "SELECT name,seq FROM sqlite_sequence ORDER BY name",
        "SELECT MAX(id) FROM calls",
    )
    outputs = []
    connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=2)
    try:
        # Connection-local guard; no persistent PRAGMA setters are exposed.
        connection.execute("PRAGMA query_only=ON")
        allowed = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ,
                   sqlite3.SQLITE_FUNCTION, sqlite3.SQLITE_PRAGMA}

        def authorizer(action, arg1, arg2, database, origin):
            if action not in allowed:
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK

        connection.set_authorizer(authorizer)
        for sql in queries:
            rows = connection.execute(sql).fetchall()
            if sql == "PRAGMA integrity_check" and rows != [("ok",)]:
                raise GateBlocked("copy_integrity_failed")
            outputs.append({"sql": sql, "rows": rows, "row_count": len(rows)})
    finally:
        connection.close()
    return outputs


def apply_landlock(evidence):
    """Allow new filesystem writes only inside /evidence, including /dev denial."""
    if sys.platform != "linux" or platform.machine() not in {"x86_64", "aarch64"}:
        raise GateBlocked("landlock_platform_not_supported")
    libc = ctypes.CDLL(None, use_errno=True)
    libc.syscall.restype = ctypes.c_long
    abi = libc.syscall(444, 0, 0, 1)
    if abi < 3:
        raise GateBlocked("landlock_ABI_3_required")
    write_access = sum(1 << bit for bit in (1, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14))

    class Ruleset(ctypes.Structure):
        _fields_ = [("handled_access_fs", ctypes.c_uint64),
                    ("handled_access_net", ctypes.c_uint64)]

    class Rule(ctypes.Structure):
        _pack_ = 1
        _fields_ = [("allowed_access", ctypes.c_uint64), ("parent_fd", ctypes.c_int32)]

    spec = Ruleset(write_access, 3 if abi >= 4 else 0)
    size = ctypes.sizeof(spec) if abi >= 4 else 8
    ruleset = libc.syscall(444, ctypes.byref(spec), size, 0)
    if ruleset < 0:
        raise GateBlocked("landlock_ruleset_create_failed")
    directory = os.open(evidence, os.O_PATH | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        rule = Rule(write_access, directory)
        if libc.syscall(445, ruleset, 1, ctypes.byref(rule), 0) != 0:
            raise GateBlocked("landlock_add_path_failed")
        if libc.prctl(38, 1, 0, 0, 0) != 0:
            raise GateBlocked("no_new_privileges_failed")
        if libc.syscall(446, ruleset, 0) != 0:
            raise GateBlocked("landlock_restrict_failed")
    finally:
        os.close(directory)
        os.close(ruleset)
    # /dev/null would otherwise be writable: opening for write must be denied.
    try:
        fd = os.open("/dev/null", os.O_WRONLY)
    except OSError as exc:
        if exc.errno != errno.EACCES:
            raise GateBlocked("landlock_write_probe_unexpected_errno") from None
    else:
        os.close(fd)
        raise GateBlocked("write_outside_evidence_not_denied")
    return {"abi": abi, "handled_write_access": write_access,
            "tcp_bind_connect_denied": abi >= 4,
            "dev_null_write_open": "EACCES", "writable_rule": str(evidence)}


def executor(evidence):
    evidence = Path(evidence).resolve(strict=True)
    os.environ["R0_EVIDENCE_ROOT"] = str(evidence)
    result = {"started": now(), "status": "BLOCKED", "source_open_count": 0,
              "source_sql_count": 0, "real_copy_count": 0, "model_calls": 0}
    try:
        result["landlock"] = apply_landlock(evidence)
        status = Path("/proc/self/status").read_text()
        fields = dict(line.split(":", 1) for line in status.splitlines() if ":" in line)
        result["process"] = {key: fields.get(key, "").strip()
                             for key in ("Uid", "Gid", "CapEff", "NoNewPrivs", "Seccomp")}
        result["network_devices"] = Path("/proc/net/dev").read_text()
        result["routes"] = Path("/proc/net/route").read_text()
        result["docker_socket_present"] = any(Path(p).exists() for p in (
            "/var/run/docker.sock", "/run/docker.sock", "/var/run/containerd/containerd.sock"))
        if (result["process"]["CapEff"] != "0000000000000000"
                or result["process"]["NoNewPrivs"] != "1"
                or result["docker_socket_present"]):
            raise GateBlocked("runtime_privilege_gate_failed")
        module_spec = importlib.util.spec_from_file_location("r0_tests", "/opt/r0/test.py")
        module = importlib.util.module_from_spec(module_spec)
        module_spec.loader.exec_module(module)
        buffer = io.StringIO()
        tests = unittest.defaultTestLoader.loadTestsFromModule(module)
        executed = unittest.TextTestRunner(stream=buffer, verbosity=2).run(tests)
        with (evidence / "synthetic-tests.log").open("x", encoding="utf-8") as log:
            log.write(buffer.getvalue())
        result["synthetic"] = {"tests": executed.testsRun, "failures": len(executed.failures),
                               "errors": len(executed.errors), "skipped": len(executed.skipped),
                               "result": "PASS" if executed.wasSuccessful() and not executed.skipped else "FAIL"}
        if result["synthetic"]["result"] != "PASS":
            raise GateBlocked("synthetic_validation_not_PASS")
        attestation = json.loads((evidence / "acquisition-gate.json").read_text())
        result["source_gate"] = attestation
        # This execution supplies no independent VM/host quiescence evidence.
        # Do not substitute stopped Docker consumers or stable hashes for it.
        if attestation.get("all_source_writers_quiescent") is not True:
            raise GateBlocked("all_source_writers_quiescent_NOT_PROVEN")
        raise GateBlocked("live_acquisition_requires_separately_reviewed_attestation")
    except GateBlocked as exc:
        result["blocking_reason"] = str(exc)
    except Exception as exc:
        # Avoid exception text, paths, database contents or credentials.
        result["blocking_reason"] = "unexpected_" + type(exc).__name__
    result["finished"] = now()
    save_new(evidence / "executor-result.json", result)
    print(json.dumps(result, ensure_ascii=False))
    return 3 if result["status"] == "BLOCKED" else 0


def clean_container(value):
    return {
        "id": value["Id"], "name": value["Name"], "image": value["Image"],
        "state": value["State"]["Status"], "started": value["State"]["StartedAt"],
        "finished": value["State"]["FinishedAt"],
        "mounts": sorted([{k: m.get(k) for k in ("Type", "Name", "Source", "Destination", "RW")}
                          for m in value["Mounts"]], key=lambda m: m["Destination"]),
        "networks": {k: v["NetworkID"] for k, v in value["NetworkSettings"]["Networks"].items()},
    }


def validate_executor(value, paths, label):
    host = value["HostConfig"]
    checks = {
        "created_not_started": value["State"]["Status"] == "created",
        "fixed_image": value["Image"] == IMAGE,
        "owned_label": value["Config"]["Labels"].get("codex.r0.run") == label,
        "network_none": host["NetworkMode"] == "none",
        "root_readonly": host["ReadonlyRootfs"] is True,
        "unprivileged": host["Privileged"] is False,
        "caps_dropped": host["CapDrop"] == ["ALL"] and not host.get("CapAdd"),
        "no_new_privileges": "no-new-privileges" in host["SecurityOpt"],
        "nonroot": value["Config"]["User"] == "999:999",
        "no_host_namespaces": host["PidMode"] != "host" and host["IpcMode"] == "none",
        "no_ports": not host.get("PortBindings") and not host.get("PublishAllPorts"),
        "no_devices": not host.get("Devices") and not host.get("DeviceRequests"),
        "no_volumes_from": not host.get("VolumesFrom"),
        "no_tmpfs": not host.get("Tmpfs"),
        "no_restart": host["RestartPolicy"]["Name"] == "no",
        "mount_count": len(value["Mounts"]) == 4,
    }
    mounts = {m["Destination"]: m for m in value["Mounts"]}
    checks["source_exact_ro"] = (mounts.get("/source", {}).get("Name") == VOLUME
                                    and mounts["/source"]["RW"] is False)
    checks["evidence_only_rw"] = [m["Destination"] for m in value["Mounts"] if m["RW"]] == ["/evidence"]
    for destination, source in paths.items():
        actual = mounts.get(destination, {})
        checks["bind_" + destination] = (actual.get("Type") == "bind"
                                             and bind_matches(source, actual.get("Source", ""))
                                             and actual.get("RW") == (destination == "/evidence"))
    return checks


def bind_matches(expected, actual):
    """Exact Docker Desktop drive translation, not suffix/path-prefix matching."""
    def normalized(value):
        value = str(value).replace("\\", "/")
        while "//" in value:
            value = value.replace("//", "/")
        return value.rstrip("/")
    expected, actual = normalized(expected), normalized(actual)
    if ".." in expected.split("/") or ".." in actual.split("/"):
        return False
    choices = {expected}
    if len(expected) > 3 and expected[1:3] == ":/" and expected[0].isalpha():
        choices.add("/run/desktop/mnt/host/" + expected[0].lower() + "/" + expected[3:])
    return actual in choices


def resume(root):
    """Re-attest the SAME never-started executor after path-check correction.

    Does not create/reconfigure resources, remove evidence or overwrite the first
    blocked attempt. Used only when the original failures were bind comparisons.
    """
    root = Path(root).resolve(strict=True)
    evidence = safe_directory(root / EVIDENCE, root)
    initial = json.loads((evidence / "summary.json").read_text(encoding="utf-8"))
    prestart = json.loads((evidence / "executor-prestart.json").read_text(encoding="utf-8"))
    if (initial.get("blocking_reason") != "executor_prestart_isolation_failed"
            or initial.get("created_executors") != 1
            or any(not result for name, result in prestart["checks"].items() if not name.startswith("bind_"))):
        raise GateBlocked("resume_outside_original_path_comparison_failure")
    cid = initial["executor_id"]
    commands = []

    def command(argv, *, decode_json=False, expected_exit=None):
        completed = subprocess.run(argv, cwd=root, capture_output=True, timeout=120)
        row = {"argv": argv, "cwd": str(root), "exit_code": completed.returncode,
               "finished": now(), "stdout_sha256": digest(completed.stdout),
               "stderr_sha256": digest(completed.stderr)}
        if not decode_json:
            row.update(stdout=completed.stdout.decode("utf-8", errors="replace"),
                       stderr=completed.stderr.decode("utf-8", errors="replace"))
        commands.append(row)
        if expected_exit is None and completed.returncode != 0:
            raise GateBlocked("resume_command_failed_" + str(completed.returncode))
        return json.loads(completed.stdout) if decode_json else completed

    reason = "resume_not_completed"
    try:
        if command(["git", "rev-parse", "HEAD"]).stdout.decode().strip() != HEAD:
            raise GateBlocked("HEAD_changed")
        values = command(["docker", "inspect", cid, *CONTAINERS], decode_json=True)
        executor_value, originals = values[0], [clean_container(v) for v in values[1:]]
        original_before = json.loads((evidence / "resources-before.json").read_text(encoding="utf-8"))
        if originals != original_before["containers"]:
            raise GateBlocked("protected_resources_changed_before_resume")
        consumers = command(["docker", "ps", "-a", "--filter", "volume=" + VOLUME,
                             "--no-trunc", "--format", "{{.ID}}|{{.State}}"])
        if set(consumers.stdout.decode().splitlines()) != {OWNER + "|exited", cid + "|created"}:
            raise GateBlocked("unexpected_source_consumer")
        paths = {"/evidence": str(evidence), "/opt/r0/tool.py": str(root / TOOL), "/opt/r0/test.py": str(root / TEST)}
        checks = validate_executor(executor_value, paths, executor_value["Config"]["Labels"]["codex.r0.run"])
        save_new(evidence / "executor-prestart-rechecked.json", {"id": cid, "checks": checks,
                 "mounts": clean_container(executor_value)["mounts"],
                 "tool_sha256": digest((root / TOOL).read_bytes()),
                 "test_sha256": digest((root / TEST).read_bytes()),
                 "note": "Same created executor, unchanged security/mounts; exact Desktop drive translation recognized."})
        if not all(checks.values()):
            raise GateBlocked("executor_prestart_recheck_failed")
        attached = command(["docker", "start", "--attach", cid], expected_exit="record_actual")
        ended = command(["docker", "inspect", cid], decode_json=True)[0]
        save_new(evidence / "executor-after.json", {"id": cid, "state": ended["State"],
                 "mounts": clean_container(ended)["mounts"], "docker_start_exit": attached.returncode})
        if not (evidence / "executor-result.json").is_file():
            raise GateBlocked("executor_produced_no_result")
        result = json.loads((evidence / "executor-result.json").read_text(encoding="utf-8"))
        reason = result.get("blocking_reason", "unclassified")
    except GateBlocked as exc:
        reason = str(exc)
    finally:
        after = command(["docker", "inspect", *CONTAINERS], decode_json=True)
        protected_equal = [clean_container(v) for v in after] == original_before["containers"]
        volume = command(["docker", "volume", "inspect", VOLUME], decode_json=True)[0]
        volume_equal = {k: volume[k] for k in original_before["volume"]} == original_before["volume"]
        base = json.loads((evidence / "workspace-before.json").read_text(encoding="utf-8"))
        current = {rel: digest((root / rel).read_bytes()) for rel in base["protected_files"]}
        # Record exact native bytes without adding raw diff or sensitive config.
        diff = command(["git", "diff", "--binary"])
        staged = command(["git", "diff", "--cached", "--binary"])
        workspace_equal = (current == base["protected_files"] and digest(diff.stdout) == base["tracked_diff_sha256"]
                           and digest(staged.stdout) == base["staged_diff_sha256"])
        for row in commands:
            if row["argv"][:2] == ["git", "diff"]:
                row.pop("stdout", None)
        save_new(evidence / "resume-preservation.json", {"protected_resources_equal": protected_equal,
                 "volume_metadata_equal": volume_equal, "protected_workspace_equal": workspace_equal})
        if not all((protected_equal, volume_equal, workspace_equal)):
            reason = "protected_state_changed"
        save_new(evidence / "resume-commands.json", commands)
        save_new(evidence / "resume-summary.json", {"status": "BLOCKED", "blocking_reason": reason,
                 "executor_id": cid, "total_executors_created": 1, "existing_business_containers_started": 0,
                 "source_content_reads": 0, "source_SQL": 0, "real_copies": 0, "real_copy_SQL": 0,
                 "model_calls": 0, "existing_reports_modified": 0})
    print(json.dumps({"status": "BLOCKED", "reason": reason, "evidence": str(evidence), "executor": cid}, ensure_ascii=False))
    return 3


def run(root):
    root = Path(root).resolve(strict=True)
    approved = root / EVIDENCE
    if approved.exists():
        raise GateBlocked("evidence_directory_already_exists_no_overwrite")
    safe_directory(approved.parent, root)
    approved.mkdir(exist_ok=False)
    evidence = approved
    commands = []

    def command(argv, *, json_output=False):
        started = now()
        completed = subprocess.run(argv, cwd=root, capture_output=True, timeout=120)
        entry = {"argv": argv, "cwd": str(root), "started": started,
                 "finished": now(), "exit_code": completed.returncode,
                 "stdout_sha256": digest(completed.stdout), "stderr_sha256": digest(completed.stderr)}
        # Raw inspect/environment outputs are never persisted.
        if not json_output:
            entry["stdout"] = completed.stdout.decode("utf-8", errors="replace")
            entry["stderr"] = completed.stderr.decode("utf-8", errors="replace")
        commands.append(entry)
        if completed.returncode:
            raise GateBlocked("command_exit_" + str(completed.returncode))
        return json.loads(completed.stdout) if json_output else completed.stdout

    def workspace():
        tracked = command(["git", "diff", "--binary"])
        staged = command(["git", "diff", "--cached", "--binary"])
        untracked = command(["git", "ls-files", "--others", "--exclude-standard", "-z"])
        old = [p for p in untracked.split(b"\0") if p and p.decode("utf-8").replace("\\", "/") not in {TOOL, TEST}
               and not p.decode("utf-8").replace("\\", "/").startswith(EVIDENCE + "/")]
        manifest = {}
        for base in ("backend/app", "backend/alembic", "frontend/src", "miniprogram/pages", "miniprogram/services", "miniprogram/utils"):
            for path in (root / base).rglob("*"):
                if path.is_file() and "__pycache__" not in path.parts:
                    manifest[path.relative_to(root).as_posix()] = digest(path.read_bytes())
        for rel in ("docs/LOCAL_READY_ACCEPTANCE_REPORT.md", "docs/FUTURE_PRODUCTION_READINESS_PLAN.md",
                    "backend/tmp/codex-stage82-manual-e08d3456a45a/manual_real_app.py",
                    "backend/tmp/codex-stage82-manual-e08d3456a45a/yuelu_manual_model_budget.py"):
            manifest[rel] = digest((root / rel).read_bytes())
        return {"head": command(["git", "rev-parse", "HEAD"]).decode().strip(),
                "tracked_diff_sha256": digest(tracked), "staged_diff_sha256": digest(staged),
                "untracked_excluding_authorized_sha256": digest(b"\0".join(old) + b"\0"),
                "untracked_excluding_authorized_count": len(old), "protected_files": manifest}

    def resources():
        values = command(["docker", "inspect", *CONTAINERS], json_output=True)
        volume = command(["docker", "volume", "inspect", VOLUME], json_output=True)[0]
        consumers = command(["docker", "ps", "-a", "--filter", "volume=" + VOLUME,
                             "--no-trunc", "--format", "{{.ID}}|{{.State}}"])
        return {"containers": [clean_container(v) for v in values],
                "volume": {k: volume[k] for k in ("Name", "Driver", "Scope", "Options", "Mountpoint")},
                "consumers": consumers.decode().splitlines()}

    status, block, cid = "BLOCKED", None, None
    try:
        before_workspace = workspace()
        save_new(evidence / "workspace-before.json", before_workspace)
        if before_workspace["head"] != HEAD:
            raise GateBlocked("HEAD_changed")
        before_resources = resources()
        save_new(evidence / "resources-before.json", before_resources)
        if before_resources["consumers"] != [OWNER + "|exited"]:
            raise GateBlocked("source_volume_consumers_changed")
        for value in before_resources["containers"][:3]:
            if value["state"] != "exited":
                raise GateBlocked("candidate_not_stopped")
        image = command(["docker", "image", "inspect", IMAGE], json_output=True)[0]
        if image["Id"] != IMAGE or image["Os"] != "linux" or image["Architecture"] != "amd64":
            raise GateBlocked("fixed_image_identity_changed")
        if any(any(term in item.split("=", 1)[0].lower() for term in ("secret", "token", "api_key", "password"))
               for item in image["Config"].get("Env", [])):
            raise GateBlocked("image_contains_credential_environment")
        save_new(evidence / "acquisition-gate.json", {
            "all_docker_consumers_stopped": True, "all_source_writers_quiescent": False,
            "reason": "No independent Docker-VM/host quiescence attestation; do not widen namespace/capabilities.",
            "source_metadata_zero_change_proven": False, "source_sql_permitted": False,
            "live_acquisition_allowed": False, "inherited_copy_SQL_authorization": "retained_not_re_requested"})
        label = "r0-20261026-" + uuid4().hex[:12]
        paths = {"/evidence": str(evidence), "/opt/r0/tool.py": str(root / TOOL), "/opt/r0/test.py": str(root / TEST)}
        argv = ["docker", "create", "--pull", "never", "--name", label, "--label", "codex.r0.run=" + label,
                "--network", "none", "--read-only", "--user", "999:999", "--cap-drop", "ALL",
                "--security-opt", "no-new-privileges", "--ipc", "none", "--pids-limit", "64",
                "--memory", "256m", "--cpus", "1", "--restart", "no", "--workdir", "/evidence",
                "--env", "PYTHONDONTWRITEBYTECODE=1", "--env", "PYTHONNOUSERSITE=1",
                "--env", "R0_EVIDENCE_ROOT=/evidence", "--env", "HOME=/evidence", "--env", "TMPDIR=/evidence",
                "--mount", "type=volume,src=" + VOLUME + ",dst=/source,readonly,volume-nocopy"]
        for destination, source in paths.items():
            argv += ["--mount", "type=bind,src=" + source + ",dst=" + destination + (",readonly" if destination != "/evidence" else "")]
        argv += ["--entrypoint", "python", IMAGE, "-I", "-S", "-B", "/opt/r0/tool.py", "executor", "--evidence-root", "/evidence"]
        cid = command(argv).decode().strip()
        inspected = command(["docker", "inspect", cid], json_output=True)[0]
        checks = validate_executor(inspected, paths, label)
        save_new(evidence / "executor-prestart.json", {"id": cid, "checks": checks,
                 "mounts": clean_container(inspected)["mounts"], "image": inspected["Image"],
                 "security": {k: inspected["HostConfig"].get(k) for k in (
                     "NetworkMode", "ReadonlyRootfs", "Privileged", "CapAdd", "CapDrop", "SecurityOpt",
                     "PidMode", "IpcMode", "PortBindings", "Devices", "Tmpfs", "PidsLimit", "Memory", "NanoCpus")}})
        if not all(checks.values()):
            raise GateBlocked("executor_prestart_isolation_failed")
        # Start exactly this new executor, never any pre-existing container.
        try:
            command(["docker", "start", "--attach", cid])
        except GateBlocked:
            if not (evidence / "executor-result.json").is_file():
                raise
        ended = command(["docker", "inspect", cid], json_output=True)[0]
        save_new(evidence / "executor-after.json", {"id": cid, "state": ended["State"],
                                                  "mounts": clean_container(ended)["mounts"]})
        outcome = json.loads((evidence / "executor-result.json").read_text(encoding="utf-8"))
        block = outcome.get("blocking_reason")
        if outcome.get("synthetic", {}).get("result") == "PASS":
            status = "BLOCKED" if outcome["status"] == "BLOCKED" else "PARTIAL"
    except GateBlocked as exc:
        block = str(exc)
    finally:
        try:
            after_workspace = workspace()
            after_resources = resources()
            save_new(evidence / "workspace-after.json", after_workspace)
            save_new(evidence / "resources-after.json", after_resources)
            preserved = {"workspace_equal": before_workspace == after_workspace,
                         "protected_resources_equal": before_resources["containers"] == after_resources["containers"],
                         "volume_metadata_equal": before_resources["volume"] == after_resources["volume"]}
            save_new(evidence / "preservation.json", preserved)
            if not all(preserved.values()):
                status, block = "BLOCKED", "protected_state_changed"
        except Exception as exc:
            status, block = "BLOCKED", "final_preservation_check_" + type(exc).__name__
        # Source code diffs and paths are not business records, but keep the
        # command log concise: exact commands/exit/hash, no multi-MB git dumps.
        for item in commands:
            if item["argv"][:2] == ["git", "diff"] or "ls-files" in item["argv"]:
                item.pop("stdout", None)
        save_new(evidence / "commands.json", commands)
        save_new(evidence / "summary.json", {"status": status, "blocking_reason": block, "head": HEAD,
                 "executor_id": cid, "created_executors": int(cid is not None),
                 "business_containers_started": 0, "source_content_reads": 0, "source_SQL": 0,
                 "real_copies": 0, "real_copy_SQL": 0, "model_calls": 0, "model_cost": 0,
                 "existing_files_modified": 0, "existing_reports_modified": 0})
    print(json.dumps({"status": status, "reason": block, "evidence": str(evidence), "executor": cid}, ensure_ascii=False))
    return 3 if status == "BLOCKED" else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("run", "resume", "executor"))
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[2]))
    parser.add_argument("--evidence-root", default="/evidence")
    args = parser.parse_args()
    if args.mode == "run":
        return run(args.root)
    if args.mode == "resume":
        return resume(args.root)
    return executor(args.evidence_root)


if __name__ == "__main__":
    raise SystemExit(main())
