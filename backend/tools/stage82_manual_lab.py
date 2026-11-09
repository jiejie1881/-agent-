"""Owned Compose browser lab; never inspects existing production resources."""

import hashlib
import json
import secrets
import socket
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
D = "docker"
BACK = "sha256:d027564198cbf5c1728f9c2316991e2d527e119f040f86c65085592ac941dbc3"
FRONT = "sha256:513a31d42fe0ccd586b22e4bac4c575b2b560ab3355621f0cc6a43c0438cb055"
MYSQL = "sha256:0744ee5ef89ce6ccfa13de3e579fe6b9e27f93dd70da9c06d2c908b1b193fb8d"


def cmd(*args, timeout=90, input=None):
    p = subprocess.run(
        [D, *args], input=input, capture_output=True, timeout=timeout, check=False
    )
    if p.returncode:
        raise RuntimeError(
            "Docker command failed: " + p.stderr.decode(errors="replace")[-1200:]
        )
    return p.stdout


def main():
    if len(sys.argv) > 1:
        if sys.argv[1] not in {"cleanup", "status"}:
            raise ValueError("Allowed modes: start (no arguments), status, cleanup")
        out = Path(sys.argv[2]).resolve()
        assert out.is_relative_to(ROOT / "docs/evidence")
        state = json.loads((out / "state.json").read_text())
        run = state["run"]
        proj = state["project"]
        lab = ROOT / "backend/tmp" / proj
        assert (
            proj == "codex-stage82-manual-" + run
            and len(run) == 12
            and all(c in "0123456789abcdef" for c in run)
        )
        if sys.argv[1] == "status":
            statuses = []
            for item in state.get("containers", []):
                inspected = json.loads(cmd("inspect", item["id"]))[0]
                assert inspected["Config"]["Labels"]["codex.run_id"] == run
                statuses.append(
                    {"role": item["role"], "running": inspected["State"]["Running"]}
                )
            print(
                json.dumps(
                    {
                        "url": state.get("url"),
                        "project": proj,
                        "live_containers": statuses,
                        "all_running": len(statuses) == 3
                        and all(r["running"] for r in statuses),
                    }
                )
            )
            return

        def owned():
            for cid in (
                cmd("ps", "-aq", "--filter", "label=com.docker.compose.project=" + proj)
                .decode()
                .split()
            ):
                obj = json.loads(cmd("inspect", cid))[0]
                assert obj["Config"]["Labels"]["codex.run_id"] == run
                saved = next(
                    (c for c in state.get("containers", []) if c["id"] == cid), None
                )
                if state.get("containers"):
                    assert saved is not None and sorted(saved["volumes"]) == sorted(
                        m["Name"] for m in obj["Mounts"] if m["Type"] == "volume"
                    )

        owned()
        recorded_volumes = [
            v for c in state.get("containers", []) for v in c.get("volumes", [])
        ]
        cmd(
            "compose",
            "-p",
            proj,
            "-f",
            str(lab / "compose.json"),
            "down",
            "--volumes",
            "--remove-orphans",
            timeout=90,
        )
        checks = {
            kind: cmd(*args, "--filter", "label=com.docker.compose.project=" + proj)
            .decode()
            .strip()
            for kind, args in [
                ("containers", ["ps", "-aq"]),
                ("volumes", ["volume", "ls", "-q"]),
                ("networks", ["network", "ls", "-q"]),
            ]
        }
        assert not any(checks.values())
        for volume in recorded_volumes:
            assert not cmd(
                "volume", "ls", "-q", "--filter", "name=^" + volume + "$"
            ).strip()
        (out / "cleanup.json").write_text(
            json.dumps(
                {
                    "verified_absent": checks,
                    "paid_calls": 0,
                    "production_operations": 0,
                },
                indent=2,
            )
        )
        # Only delete ephemeral credentials owned by this lab, retain compose and public evidence.
        for file in [lab / "env.json", lab / "compose.json"]:
            if file.exists():
                file.unlink()
        state["result"] = "CLEANED"
        (out / "state.json").write_text(
            json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(json.dumps({"cleanup": "PASS", "project": proj}))
        return
    run = uuid4().hex[:12]
    proj = "codex-stage82-manual-" + run
    out = ROOT / "docs/evidence" / proj
    out.mkdir(parents=True, exist_ok=False)
    lab = ROOT / "backend/tmp" / proj
    lab.mkdir(parents=True, exist_ok=False)
    state = {
        "run": run,
        "project": proj,
        "result": "STARTING",
        "production_operations": 0,
        "paid_calls": 0,
    }

    def save():
        (out / "state.json").write_text(
            json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    save()
    cmd("info", "--format", "{{.ServerVersion}}")
    for image in [BACK, FRONT, MYSQL]:
        assert json.loads(cmd("image", "inspect", image))[0]["Id"] == image
    expected = {
        p.relative_to(ROOT / "backend/app").as_posix(): hashlib.sha256(
            p.read_bytes()
        ).hexdigest()
        for p in (ROOT / "backend/app").rglob("*.py")
    }
    # Verify live image source independently of historical report.
    probe = "import hashlib,json;from pathlib import Path;r=Path('/app/app');print(json.dumps({p.relative_to(r).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in r.rglob('*.py')}))"
    actual = json.loads(
        cmd(
            "run",
            "--rm",
            "--network",
            "none",
            "--entrypoint",
            "python",
            BACK,
            "-c",
            probe,
        )
    )
    assert actual == expected
    state["source_files_match"] = len(expected)
    state["images"] = {"backend": BACK, "frontend": FRONT, "mysql": MYSQL}
    save()
    adapter = """import os\nfrom sqlalchemy import create_engine,text\nassert not os.environ.get("AGENT_API_KEY")\nwith create_engine(os.environ["DATABASE_URL"]).connect() as c:\n row=c.execute(text("SELECT @@server_uuid,DATABASE(),CURRENT_USER()")).one()\n assert row[0]==os.environ["LAB_MYSQL_UUID"] and row[1]=="codex_stage8_browser" and row[2]=="stage8_user@%"\nfrom app.main import app\nfrom app.api.dependencies import DbSession\nfrom app.api.shadow_dispatch_dependencies import get_shadow_dispatch\nfrom app.agent.dispatch_workflow import ShadowDispatchWorkflow\nfrom app.core.config import get_settings\nfrom app.services.dispatch_context_service import DispatchContextService\nfrom sqlalchemy.orm import Session\nfrom business_standin import BusinessStandIn\ndef workflow(db:DbSession):\n def load(day):\n  with Session(db.get_bind(),autoflush=False) as s:return DispatchContextService(s).load(day)\n return ShadowDispatchWorkflow(BusinessStandIn(),load,get_settings())\napp.dependency_overrides[get_shadow_dispatch]=workflow\n"""
    (lab / "browser_app.py").write_text(adapter)
    (lab / "business_standin.py").write_bytes(
        (ROOT / "backend/tools/business_standin.py").read_bytes()
    )
    rootpwd = secrets.token_urlsafe(32)
    dbpwd = secrets.token_urlsafe(32)
    env = {
        "DATABASE_URL": "mysql+pymysql://stage8_user:"
        + dbpwd
        + "@mysql:3306/codex_stage8_browser",
        "JWT_SECRET_KEY": secrets.token_urlsafe(48),
        "APP_ENVIRONMENT": "development",
        "API_DOCS_ENABLED": "true",
        "RUN_MIGRATIONS": "false",
        "SQL_ECHO": "false",
        "AGENT_WRITE_TOOLS_ENABLED": "false",
        "AGENT_DISPATCH_SHADOW_ENABLED": "true",
        "AGENT_DRAFT_ACCEPT_ENABLED": "true",
        "AGENT_DRAFT_ACCEPT_ADMIN_ENABLED": "true",
        "AGENT_PLAN_PUBLISH_ENABLED": "true",
        "AGENT_PLAN_PUBLISH_ADMIN_ENABLED": "true",
        "AGENT_DRAFT_RECEIPT_SECRET": secrets.token_urlsafe(48),
        "AGENT_PROVIDER": "",
        "AGENT_MODEL": "",
        "AGENT_API_KEY": "",
        "RAG_EMBEDDING_API_KEY": "",
        "PYTHONPATH": "/lab:/app",
    }
    (lab / "env.json").write_text(json.dumps(env))
    labels = {"codex.run_id": run, "codex.purpose": "stage82-manual-only"}

    def svc(image):
        return {"image": image, "labels": labels, "networks": ["lab"]}

    mysql = svc(MYSQL)
    mysql.update(
        environment={
            "MYSQL_ROOT_PASSWORD": rootpwd,
            "MYSQL_DATABASE": "codex_stage8_browser",
            "MYSQL_USER": "stage8_user",
            "MYSQL_PASSWORD": dbpwd,
        },
        volumes=[{"type": "volume", "target": "/var/lib/mysql"}],
        command=["--event-scheduler=OFF"],
    )
    backend = svc(BACK)
    backend.update(
        environment=env,
        volumes=[
            {"type": "bind", "source": str(lab), "target": "/lab", "read_only": True},
            {"type": "volume", "target": "/app/uploads"},
            {"type": "volume", "target": "/app/rag_data"},
            {"type": "volume", "target": "/app/agent_data"},
        ],
        entrypoint=[
            "python",
            "-m",
            "uvicorn",
            "browser_app:app",
            "--host",
            "0.0.0.0",
            "--port",
            "8000",
        ],
    )
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        api_port = sock.getsockname()[1]
    api_port = port
    front = svc(FRONT)
    front.update(ports=[f"127.0.0.1:{port}:80"], networks=["edge", "lab"])
    nginx = (ROOT / "frontend/nginx.conf").read_text()
    nginx = nginx.replace(
        "    location / {",
        "    location = /docs { proxy_pass http://backend:8000/docs; }\n    location = /openapi.json { proxy_pass http://backend:8000/openapi.json; }\n    location / {",
    )
    (lab / "nginx.conf").write_text(nginx)
    front["volumes"] = [
        {
            "type": "bind",
            "source": str(lab / "nginx.conf"),
            "target": "/etc/nginx/conf.d/default.conf",
            "read_only": True,
        }
    ]
    compose = {
        "services": {"mysql": mysql, "backend": backend, "frontend": front},
        "networks": {
            "lab": {"internal": True, "labels": labels},
            "edge": {"labels": labels},
        },
        "volumes": {},
    }
    cp = lab / "compose.json"

    def composewrite():
        cp.write_text(json.dumps(compose))

    composewrite()

    def co(*args, timeout=90):
        return cmd("compose", "-p", proj, "-f", str(cp), *args, timeout=timeout)

    co("up", "-d", "mysql")
    cid = co("ps", "-q", "mysql").decode().strip()
    deadline = time.monotonic() + 120
    while True:
        try:
            ident = (
                cmd(
                    "exec",
                    "-e",
                    "MYSQL_PWD=" + rootpwd,
                    cid,
                    "mysql",
                    "-uroot",
                    "-Nse",
                    "SELECT @@server_uuid,VERSION()",
                    timeout=6,
                )
                .decode()
                .split()
            )
            break
        except Exception:
            if time.monotonic() > deadline:
                raise
            time.sleep(2)
    assert ident[0] != "c719a759-ba36-11f1-827d-de3544d07304" and ident[1].startswith(
        "8.4."
    )
    grants = cmd(
        "exec",
        "-e",
        "MYSQL_PWD=" + dbpwd,
        cid,
        "mysql",
        "-ustage8_user",
        "-Nrse",
        "SELECT DATABASE(),CURRENT_USER();SHOW GRANTS;",
        "codex_stage8_browser",
    ).decode()
    assert "stage8_user@%" in grants
    from stage82_mysql_guard import check_grants

    check_grants(grants.splitlines()[1:], "stage8_user", "codex_stage8_browser")
    denials = []
    for sql in [
        "SELECT COUNT(*) FROM mysql.user",
        "CREATE DATABASE codex_stage82_forbidden",
    ]:
        check = subprocess.run(
            [
                D,
                "exec",
                "-e",
                "MYSQL_PWD=" + dbpwd,
                cid,
                "mysql",
                "-ustage8_user",
                "-Nse",
                sql,
            ],
            capture_output=True,
            timeout=10,
            check=False,
        )
        assert check.returncode != 0 and (
            b"ERROR 1142" in check.stderr or b"ERROR 1044" in check.stderr
        )
        denials.append({"sql": sql, "denied": True})
    (out / "grants-verified.json").write_text(
        json.dumps(
            {
                "raw_grants": grants.splitlines(),
                "denials": denials,
                "scope": "only exact isolated database",
            },
            indent=2,
        )
    )
    env["LAB_MYSQL_UUID"] = ident[0]
    composewrite()
    state.update(
        mysql_uuid=ident[0],
        mysql_version=ident[1],
        grant_scope="codex_stage8_browser only",
        url=f"http://127.0.0.1:{port}",
        api_url=f"http://127.0.0.1:{api_port}",
        database="codex_stage8_browser",
    )
    save()
    for index, args in enumerate(
        [("upgrade", "head"), ("downgrade", "-1"), ("upgrade", "head"), ("check",)]
    ):
        (out / f"migration-{index}.log").write_bytes(
            co(
                "run",
                "--rm",
                "--no-deps",
                "--entrypoint",
                "python",
                "backend",
                "-m",
                "alembic",
                *args,
                timeout=100,
            )
        )
    co("up", "-d", "backend", "frontend")
    api = co("ps", "-q", "backend").decode().strip()
    deadline = time.monotonic() + 70
    while True:
        try:
            cmd(
                "exec",
                api,
                "python",
                "-c",
                "import urllib.request;assert urllib.request.urlopen('http://127.0.0.1:8000/health/ready',timeout=3).status==200",
                timeout=5,
            )
            break
        except Exception:
            if time.monotonic() > deadline:
                raise
            time.sleep(1)
    seed = "from sqlalchemy.orm import Session;from app.infrastructure.database.session import engine;from app.services.auth_service import AuthService;from app.domain.enums import UserRole;\nwith Session(engine) as s:\n for username,role in [('stage8-admin',UserRole.ADMIN),('stage8-viewer',UserRole.VIEWER),('stage8-dispatcher',UserRole.DISPATCHER)]:AuthService(s).create_user(username,'Stage8Browser!2026',role)\nfrom app.agent.tool_registry import AgentToolRegistry;assert len(AgentToolRegistry().to_openai_tools())==7;print('3 synthetic accounts; 7 read-only tools')"
    state["seed"] = cmd("exec", api, "python", "-c", seed).decode().strip()
    state["containers"] = []
    for cid in co("ps", "-q").decode().split():
        obj = json.loads(cmd("inspect", cid))[0]
        assert obj["Config"]["Labels"]["codex.run_id"] == run
        assert all(m["Type"] in ["volume", "bind"] for m in obj["Mounts"])
        assert set(obj["NetworkSettings"]["Networks"]) == (
            {proj + "_lab", proj + "_edge"}
            if obj["Config"]["Labels"]["com.docker.compose.service"] == "frontend"
            else {proj + "_lab"}
        )
        state["containers"].append(
            {
                "id": cid,
                "role": obj["Config"]["Labels"]["com.docker.compose.service"],
                "volumes": [m["Name"] for m in obj["Mounts"] if m["Type"] == "volume"],
            }
        )
    state["result"] = "READY_FOR_MANUAL_HTTP_VALIDATION"
    save()
    print(
        json.dumps(
            {
                "state": str(out / "state.json"),
                "url": state["url"],
                "source_files_match": len(expected),
                "project": proj,
            }
        )
    )


if __name__ == "__main__":
    main()
