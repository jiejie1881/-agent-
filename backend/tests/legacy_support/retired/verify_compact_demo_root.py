"""Run the opt-in real MySQL/API/AI check without exposing local connection secrets."""

if __name__ == "__main__":
    raise SystemExit("RETIRED_TEST_FIXTURE_ONLY: archived demonstration CLI is disabled")

import argparse
import json
import os
from pathlib import Path
import subprocess

from prepare_compact_demo import ROOT, LOCAL, compose


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True)
    parser.add_argument("--real-ai", action="store_true")
    parser.add_argument("--manual-fixtures", action="store_true")
    args = parser.parse_args()
    password = os.environ.get("DEMO_SEED_PASSWORD", "")
    if len(password) < 8:
        raise SystemExit("请设置本地DEMO_SEED_PASSWORD")
    override = json.loads((LOCAL / "logistics_dispatch_demo_verify.compose.json").read_text(encoding="utf-8"))
    url = override["services"]["backend"]["environment"]["DATABASE_URL"]
    compose("cp", str(ROOT / "backend" / "app" / "scripts" / "verify_compact_demo.py"), "backend:/app/app/scripts/verify_compact_demo.py")
    command = ["docker", "compose", "exec", "-T", "-e", "DATABASE_URL=" + url, "-e", "DEMO_SEED_PASSWORD=" + password,
               "backend", "python", "-m", "app.scripts.verify_compact_demo", "--date", args.date]
    if args.real_ai:
        command.append("--real-ai")
    if args.manual_fixtures:
        command.append("--manual-fixtures")
    result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, encoding="utf-8", errors="replace")
    # Server logging contains no credentials but store it locally rather than publish wholesale.
    (LOCAL / "verification.log").write_text(result.stdout + "\n" + result.stderr, encoding="utf-8")
    if result.returncode:
        print("验证未完成；查看 docs/local/compact-demo/verification.log 定位，未改写主演示库。")
        raise SystemExit(result.returncode)
    compose("cp", "backend:/tmp/compact-demo-validation.json", str(LOCAL / "validation.json"))
    report = json.loads((LOCAL / "validation.json").read_text(encoding="utf-8"))
    (LOCAL / f"validation-{args.date}.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"checks": report["checks"], "ai": [{"status": r["status"], "http_status": r.get("http_status")} for r in report["ai"]],
                      "agent": [{"status": r["status"], "http_status": r["http_status"], "used_tools": r["result"].get("used_tools")} for r in report["agent"]],
                      "final_version": report["final_plan"]["version"], "trips": len(report["final_plan"]["trips"]),
                      "unassigned": len(report["final_plan"]["unassigned_demands"]), "proof_url": report["proof_url"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
