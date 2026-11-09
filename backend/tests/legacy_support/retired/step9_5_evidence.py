"""Hash business tables in a Step 9.5 SQLite database without exporting row values."""

if __name__ == "__main__":
    raise SystemExit("RETIRED_TEST_FIXTURE_ONLY: archived demonstration CLI is disabled")

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path

from tests.legacy_support.step9_5_local import AREA, DAYS


def snapshot(folder):
    folder = Path(folder).resolve()
    if not folder.is_relative_to(AREA.resolve()):
        raise ValueError("Not a Step 9.5 isolated folder")
    database = (folder / "demo.sqlite3").resolve()
    marker = json.loads((folder / "step9-5-marker.json").read_text(encoding="utf-8"))
    if marker != {"database": str(database), "synthetic": True,
                  "days": [d.isoformat() for d in DAYS]}:
        raise ValueError("Database attestation failed")
    result = {}
    with sqlite3.connect("file:" + database.as_posix() + "?mode=ro", uri=True) as db:
        tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
                  if r[0] not in {"audit_logs", "agent_conversations", "agent_messages", "agent_pending_actions"}]
        for name in tables:
            rows = db.execute(f'SELECT * FROM "{name}" ORDER BY rowid').fetchall()
            data = json.dumps(rows, default=str, ensure_ascii=False, separators=(",", ":")).encode()
            result[name] = {"rows": len(rows), "sha256": hashlib.sha256(data).hexdigest()}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path)
    parser.add_argument("--compare", type=Path)
    args = parser.parse_args()
    current = snapshot(args.folder)
    if args.compare:
        before = json.loads(args.compare.read_text(encoding="utf-8"))
        changed = [name for name in current if current[name] != before.get(name)]
        print(json.dumps({"business_tables": len(current), "changed": changed,
                          "zero_business_write": not changed}, ensure_ascii=False))
        return 1 if changed else 0
    output = args.folder / "business-baseline.json"
    output.write_text(json.dumps(current, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"baseline": str(output), "business_tables": len(current),
                      "dispatch_plans": current["dispatch_plans"]["rows"]}, ensure_ascii=False))


if __name__ == "__main__":
    raise SystemExit(main())
