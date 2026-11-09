"""Negative probes with no database operations or source-directory writes."""

import importlib
import os
from pathlib import Path
import socket
import subprocess
import sys

import pytest

pytestmark = pytest.mark.usefixtures("batch2_guard_attestation")


@pytest.mark.parametrize(
    "probe", ["dns", "tcp", "udp", "process", "native-vector", "native-db"]
)
def test_worker_blocks_prohibited_operations(probe):
    with pytest.raises((PermissionError, ImportError)):
        if probe == "dns":
            socket.getaddrinfo("example.invalid", 443)
        elif probe in {"tcp", "udp"}:
            with socket.socket(
                type=socket.SOCK_STREAM if probe == "tcp" else socket.SOCK_DGRAM
            ) as sock:
                if probe == "tcp":
                    sock.connect(("127.0.0.1", 3306))
                else:
                    sock.sendto(b"denied", ("127.0.0.1", 3306))
        elif probe == "process":
            subprocess.run([sys.executable, "-c", "raise SystemExit(0)"])
        elif probe == "native-vector":
            importlib.import_module("chromadb")
        else:
            importlib.import_module("pymysql")


def test_runner_isolated_cwd_and_no_existing_environment():
    assert Path.cwd().is_relative_to(Path(os.environ["RAG_BATCH1_WORKSPACE"]))
    assert not list(Path.cwd().glob(".env*"))
    assert os.environ["MODEL_BUDGET_ENABLED"] == "false"


def test_same_resolved_windows_path_with_extended_spelling_stays_inside():
    from path_boundary import within

    root = Path(os.environ["RAG_BATCH1_WORKSPACE"]).resolve()
    assert within(root / "synthetic.json", root)
    assert within("\\\\?\\" + str(root / "synthetic.json"), root)


@pytest.mark.parametrize("suffix", ["../escape.json", "../../escape.json"])
def test_boundary_rejects_lexical_escape_without_attempting_any_write(suffix):
    from path_boundary import within

    root = Path(os.environ["RAG_BATCH1_WORKSPACE"]).resolve()
    assert not within(root / suffix, root)
    assert not within(root.parent / (root.name + "-other") / "synthetic.json", root)
    assert not within("\\\\.\\nul\\", root)
