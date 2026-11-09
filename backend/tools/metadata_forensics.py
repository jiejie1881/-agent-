"""Successor synthetic-only metadata reader; never wired to a real ledger.

R0 source and failed tests stay immutable. Keeps every original stat field and
records mismatches; directory-relative opens avoid repeated absolute traversal.
"""
import hashlib
import os
from pathlib import Path
import stat
import sys

FIELDS = ("st_dev", "st_ino", "st_mode", "st_nlink", "st_uid", "st_gid",
          "st_size", "st_atime_ns", "st_mtime_ns", "st_ctime_ns")


def metadata(info):
    return {key: getattr(info, key) for key in FIELDS}


class MetadataMismatch(RuntimeError):
    def __init__(self, stage, before, after):
        self.stage, self.before, self.after = stage, dict(before), dict(after)
        self.fields = {key: {"expected": before[key], "actual": after[key],
                             "delta": after[key] - before[key],
                             "changed": before[key] != after[key]} for key in FIELDS}
        super().__init__("metadata_changed:" + stage)


def assert_same(stage, before, after):
    if set(before) != set(FIELDS) or set(after) != set(FIELDS):
        raise ValueError("all_original_metadata_fields_required")
    if before != after:
        raise MetadataMismatch(stage, before, after)


def snapshot_fixture(source, destination, *, fixture_root, names, quiescent=False):
    """Only caller-owned synthetic paths. Does not accept real-source access."""
    source, destination, fixture_root = map(lambda p: Path(p).absolute(), (source, destination, fixture_root))
    for path in (source, destination):
        if ".." in path.parts or not path.is_relative_to(fixture_root):
            raise ValueError("outside_synthetic_fixture_root")
    # Reject no-clobber errors before any source access, fixing R0-16 ordering.
    if destination.exists():
        raise FileExistsError(str(destination))
    if not quiescent:
        raise RuntimeError("synthetic_writer_quiescence_required")
    if not names or any(not name or Path(name).name != name or "/" in name or "\\" in name or name in {".", ".."} for name in names):
        raise ValueError("fixed_leaf_names_required")
    if sys.platform != "linux" or not hasattr(os, "O_NOATIME"):
        raise RuntimeError("O_NOATIME_unavailable_no_fallback")
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NOATIME
    directory = os.open(source, flags | os.O_DIRECTORY)
    try:
        directory_before = metadata(os.fstat(directory))
        result = {}
        for name in names:
            fd = os.open(name, flags, dir_fd=directory)
            try:
                before = metadata(os.fstat(fd))
                if not stat.S_ISREG(before["st_mode"]) or before["st_nlink"] != 1 or before["st_size"] > 16 * 1024 * 1024:
                    raise RuntimeError("unsafe_synthetic_file")
                chunks = []
                while data := os.read(fd, 65536):
                    chunks.append(data)
                    if sum(map(len, chunks)) > 16 * 1024 * 1024:
                        raise RuntimeError("synthetic_file_grew")
                assert_same("file:" + name, before, metadata(os.fstat(fd)))
                content = b"".join(chunks)
                if len(content) != before["st_size"]:
                    raise RuntimeError("synthetic_file_length_changed")
                result[name] = content
            finally:
                os.close(fd)
        assert_same("source_directory", directory_before, metadata(os.fstat(directory)))
        destination.mkdir(exist_ok=False)
        for name, content in result.items():
            with (destination / name).open("xb") as stream:
                stream.write(content)
        return {name: hashlib.sha256(content).hexdigest() for name, content in result.items()}
    finally:
        os.close(directory)
