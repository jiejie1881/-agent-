"""Archive the old local Compose database; seed isolated schemas without deleting it.

Requires a RUNNING Docker daemon and DEMO_SEED_PASSWORD. Never launches Desktop.
Generated connection overrides, SQL backups and credentials stay under docs/local/.
"""

if __name__ == "__main__":
    raise SystemExit("RETIRED_TEST_FIXTURE_ONLY: archived demonstration CLI is disabled")

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / "docs" / "local" / "compact-demo"
DATABASES = ("logistics_dispatch_demo_compact", "logistics_dispatch_demo_verify")


def run(args, *, capture=True, input_text=None):
    result = subprocess.run(args, cwd=ROOT, text=True, input=input_text, capture_output=True, encoding="utf-8", errors="replace")
    if result.returncode:
        # Child commands can contain a connection URL. Do not echo commands or stderr.
        raise RuntimeError("操作失败（详情可能含密钥，未直接打印）：" + args[0] + " " + " ".join(args[1:3]))
    return result.stdout


def compose(*args, **kwargs):
    return run(["docker", "compose", *args], **kwargs)


def backend_python(code, url=None):
    args = ["exec", "-T"]
    if url:
        args += ["-e", "DATABASE_URL=" + url]
    return compose(*args, "backend", "python", "-c", code)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True)
    parser.add_argument("--activate", action="store_true", help="Switch backend only after seed succeeds")
    args = parser.parse_args()
    datetime.strptime(args.date, "%Y-%m-%d")
    password = os.environ.get("DEMO_SEED_PASSWORD", "")
    if len(password) < 8:
        raise SystemExit("请设置本地 DEMO_SEED_PASSWORD（至少8位），不会输出密码")
    compose("ps", "--format", "json")  # daemon check only, never start Desktop
    settings = json.loads(backend_python("import json; from app.core.config import get_settings; from sqlalchemy.engine import make_url; u=make_url(get_settings().database_url); print(json.dumps({'url':u.render_as_string(hide_password=False),'host':u.host,'database':u.database,'username':u.username}))"))
    if settings["host"] != "mysql" or settings["database"] not in ("logistics_dispatch", *DATABASES):
        raise SystemExit("目标并非已确认的本地Compose演示环境，停止")
    if not re.fullmatch(r"[A-Za-z0-9_]+", settings["username"] or ""):
        raise SystemExit("数据库用户名不符合安全白名单")
    LOCAL.mkdir(parents=True, exist_ok=True)
    # Protect secrets before generating local files.
    relative = str(LOCAL.relative_to(ROOT)).replace("\\", "/") + "/DEMO_ACCOUNTS.md"
    if subprocess.run(["git", "check-ignore", "-q", relative], cwd=ROOT).returncode:
        raise SystemExit("docs/local 未被Git忽略，停止生成本地配置")
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    remote_dump = f"/tmp/compact-demo-archive-{stamp}.sql"
    compose("exec", "-T", "mysql", "sh", "-c", 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysqldump -uroot --single-transaction --no-tablespaces --set-gtid-purged=OFF --databases logistics_dispatch --result-file=' + remote_dump)
    dump = LOCAL / f"logistics_dispatch-{stamp}.sql"
    compose("cp", "mysql:" + remote_dump, str(dump))
    if dump.stat().st_size < 1000:
        raise SystemExit("备份异常，禁止继续")
    compose("exec", "-T", "backend", "tar", "-czf", f"/tmp/delivery-proofs-{stamp}.tgz", "-C", "/app", "uploads")
    compose("cp", f"backend:/tmp/delivery-proofs-{stamp}.tgz", str(LOCAL / f"delivery-proofs-{stamp}.tgz"))
    backups = {"database": str(dump.relative_to(ROOT)), "bytes": dump.stat().st_size,
               "sha256": hashlib.sha256(dump.read_bytes()).hexdigest(), "old_database_preserved": True}
    print(json.dumps({"backup": backups}, ensure_ascii=False))
    seeds = {}
    for database in DATABASES:
        sql = f"CREATE DATABASE IF NOT EXISTS `{database}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci; GRANT ALL PRIVILEGES ON `{database}`.* TO '{settings['username']}'@'%';"
        compose("exec", "-T", "mysql", "sh", "-c", 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -uroot', input_text=sql)
        url = backend_python(f"from sqlalchemy.engine import make_url; from app.core.config import get_settings; print(make_url(get_settings().database_url).set(database={database!r}).render_as_string(hide_password=False))").strip()
        compose("exec", "-T", "-e", "DATABASE_URL=" + url, "backend", "alembic", "upgrade", "head")
        compose("cp", str(ROOT / "backend" / "app" / "scripts" / "seed_compact_demo.py"), "backend:/app/app/scripts/seed_compact_demo.py")
        raw = compose("exec", "-T", "-e", "DATABASE_URL=" + url, "-e", "DEMO_SEED_PASSWORD=" + password,
                      "backend", "python", "-m", "tests.legacy_support.seed_compact_demo", "--local-demo", "--expected-database", database, "--date", args.date, "--prepare-history")
        seeds[database] = json.loads(raw)
        override = {"services": {"backend": {"environment": {"DATABASE_URL": url}}}}
        (LOCAL / f"{database}.compose.json").write_text(json.dumps(override, indent=2), encoding="utf-8")
        print(json.dumps({"database": database, "seed": seeds[database]}, ensure_ascii=False))
    credentials = ["# 本地精简 Demo 测试账号", "", "仅限本机测试；禁止提交Git或用于生产。", "", "|账号|角色/姓名|测试密码|", "|---|---|---|"]
    for username, label in [("demo_admin", "管理员"), ("demo_dispatcher", "调度员"), *[(f"driver{i:02}", name) for i, name in enumerate(("张建军", "李志强", "王海波", "陈志远", "赵明远（代班）"), 1)]]:
        credentials.append(f"|{username}|{label}|{password}|")
    (LOCAL / "DEMO_ACCOUNTS.md").write_text("\n".join(credentials) + "\n", encoding="utf-8")
    (LOCAL / "initialization.json").write_text(json.dumps({"date": args.date, "backup": backups, "seeds": seeds}, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.activate:
        compose("-f", "docker-compose.yml", "-f", str(LOCAL / f"{DATABASES[0]}.compose.json"), "up", "-d", "--no-deps", "backend")
        print("已切换后端到独立精简Demo库；原库完整保留。")


if __name__ == "__main__":
    main()
